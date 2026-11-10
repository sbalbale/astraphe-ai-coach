import asyncio
import base64
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from httpcore import RemoteProtocolError
from httpx import ConnectError, ReadTimeout, RemoteProtocolError as HttpxRemoteProtocolError
from supabase import create_client, Client
from app.config import settings
from app.core.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

T = TypeVar("T")

_admin_db_client: Client | None = None
_TRANSIENT_DB_RETRIES = 3
_TRANSIENT_DB_BACKOFF_S = (0.25, 0.75, 1.5)

security = HTTPBearer()

# Per-tier default rate limits for AI endpoints (requests per minute / per hour).
# Individual users can be given overrides via app_metadata.rate_limit_rpm / rate_limit_rph.
# One coach turn makes several model calls, and the whole server shares one model
# budget (services/gemini_quota.py), so a single account must stay well below it.
TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "free":    {"rpm": 5,  "rph": 20,  "rpd": 40},
    "trial":   {"rpm": 6,  "rph": 60,  "rpd": 150},
    "premium": {"rpm": 10, "rph": 150, "rpd": 400},
}

VALID_TIERS = frozenset(TIER_DEFAULTS.keys())

# Max seconds per Supabase auth/DB call (sync SDK runs in a thread pool).
SUPABASE_CALL_TIMEOUT_SECONDS = 10.0
# Backoff when PostgREST is reloading schema (PGRST002).
_PGRST002_RETRY_DELAYS = [1.0, 2.0, 3.0]


@dataclass
class UserConfig:
    """All admin-controlled per-user settings, read from app_metadata in one auth call."""
    user_id: str
    tier: str                  # free | trial | premium
    gemini_model: str          # model for coach chat
    gemini_analysis_model: str # model for analysis endpoints
    rate_limit_rpm: int        # AI requests per minute
    rate_limit_rph: int        # AI requests per hour
    is_admin: bool


_rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db() -> Client:
    # Per-request client: JWT is applied via postgrest.auth(token) and must not be shared.
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def get_admin_db() -> Client:
    """Shared service-role client (safe to reuse across requests)."""
    global _admin_db_client
    if _admin_db_client is None:
        _admin_db_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY,
        )
    return _admin_db_client


def _is_transient_db_error(exc: BaseException) -> bool:
    if isinstance(exc, (RemoteProtocolError, HttpxRemoteProtocolError, ConnectError, ReadTimeout)):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "connectionterminated",
            "connection terminated",
            "server disconnected",
            "connection reset",
            "broken pipe",
            "eof occurred",
        )
    )


async def run_supabase_call(
    fn: Callable[[], T],
    *,
    timeout: float = SUPABASE_CALL_TIMEOUT_SECONDS,
    retries: int = _TRANSIENT_DB_RETRIES,
) -> T:
    """Run a blocking supabase call off the event loop with timeout and transient retries."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise HTTPException(
                status_code=503,
                detail="Database request timed out, please retry.",
            ) from e
        except Exception as e:
            last_exc = e
            if attempt < retries - 1 and _is_transient_db_error(e):
                await asyncio.sleep(_TRANSIENT_DB_BACKOFF_S[min(attempt, len(_TRANSIENT_DB_BACKOFF_S) - 1)])
                continue
            break
    if last_exc and _is_transient_db_error(last_exc):
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable, please retry.",
        ) from last_exc
    raise last_exc  # type: ignore[misc]

def _with_auth_token(db: Client, token: str) -> Client:
    try:
        db.postgrest.auth(token)
    except Exception:
        try:
            db.postgrest.session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception:
            pass
    return db

# Building a supabase client costs ~300 ms (fresh httpx clients, each loading the CA
# bundle), and every authenticated request built one. A client carries exactly one
# user's JWT, so it's reused for that same token only; tokens rotate about hourly, so
# the cache holds the recently active sessions and the oldest are dropped.
_USER_DB_CACHE_MAX = 256
_user_db_cache: "OrderedDict[str, Client]" = OrderedDict()
_user_db_lock = threading.Lock()


def _user_db_for_token(token: str) -> Client:
    with _user_db_lock:
        db = _user_db_cache.get(token)
        if db is not None:
            _user_db_cache.move_to_end(token)
            return db
    db = _with_auth_token(get_db(), token)
    with _user_db_lock:
        _user_db_cache[token] = db
        _user_db_cache.move_to_end(token)
        while len(_user_db_cache) > _USER_DB_CACHE_MAX:
            _user_db_cache.popitem(last=False)
    return db


async def get_user_db(credentials: HTTPAuthorizationCredentials = Security(security)) -> Client:
    return _user_db_for_token(credentials.credentials)


async def _run_supabase_call(fn, *args, timeout: float = SUPABASE_CALL_TIMEOUT_SECONDS):
    """Run a blocking supabase-py call off the event loop with a hard timeout."""
    return await run_supabase_call(lambda: fn(*args), timeout=timeout)


def _is_pgrst002(exc: BaseException) -> bool:
    return "PGRST002" in str(exc)


# ---------------------------------------------------------------------------
# Athlete identity
# ---------------------------------------------------------------------------

async def _auth_get_user(db: Client, token: str):
    return await _run_supabase_call(db.auth.get_user, token)


def unverified_jwt_claims(token: str) -> dict:
    """
    Decode a JWT payload WITHOUT verifying it. Only call this after GoTrue has
    verified the token (auth.get_user); it's for reading claims GoTrue doesn't
    surface on the user object, such as the OAuth `client_id`.
    """
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        data = json.loads(base64.urlsafe_b64decode(part))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reject_third_party_oauth_token(token: str) -> None:
    """
    Tokens minted by Supabase's OAuth server for third-party (MCP) clients carry a
    `client_id` claim and are otherwise ordinary user JWTs. They're meant for the
    read-only MCP server, not this API, where they'd allow writes, account
    deletion and (for admins) admin routes.
    """
    if unverified_jwt_claims(token).get("client_id"):
        raise HTTPException(status_code=403, detail="Third-party app tokens can't be used with this API")


def _dev_auth_fallback_allowed() -> bool:
    """The TEST_ATHLETE_ID fallback only ever applies to a local Supabase in development."""
    url = (settings.SUPABASE_URL or "").lower()
    return (
        settings.APP_ENV == "development"
        and bool(settings.TEST_ATHLETE_ID)
        and url.startswith(("http://127.0.0.1", "http://localhost"))
    )


async def _fetch_athlete_id_for_user(db: Client, user_id: str) -> str:
    athlete_res = await _run_supabase_call(
        lambda: db.table("athletes").select("id").eq("user_id", user_id).execute()
    )
    if settings.APP_ENV == "development":
        print(f"Auth DEBUG: athlete_res={athlete_res.data}")
    if not athlete_res.data:
        raise HTTPException(status_code=404, detail="Athlete profile not found")
    return athlete_res.data[0]["id"]


async def get_current_user_email(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str | None:
    """Returns the authenticated user's email address, or None on failure."""
    try:
        user_res = await _auth_get_user(db, credentials.credentials)
        return getattr(user_res.user, "email", None)
    except HTTPException:
        return None
    except Exception:
        return None


async def get_current_athlete(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str:
    """Extracts athlete_id from Supabase JWT."""
    token = credentials.credentials
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0.0] + _PGRST002_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        try:
            user = await _auth_get_user(db, token)
            reject_third_party_oauth_token(token)
            user_id = user.user.id
            if settings.APP_ENV == "development":
                print(f"Auth DEBUG: user_id={user_id}")
            return await _fetch_athlete_id_for_user(db, user_id)
        except HTTPException:
            raise
        except Exception as e:
            if _is_pgrst002(e) and attempt < len(_PGRST002_RETRY_DELAYS):
                logger.warning(
                    "Auth: PGRST002 schema cache miss (attempt %s), retrying in %ss…",
                    attempt + 1,
                    _PGRST002_RETRY_DELAYS[attempt],
                )
                last_exc = e
                continue
            last_exc = e
            break

    logger.error("Auth error: %s", last_exc)
    if last_exc and _is_pgrst002(last_exc):
        raise HTTPException(
            status_code=503,
            detail="Database schema cache unavailable, please retry.",
        )
    if _dev_auth_fallback_allowed():
        print(f"WARNING: Falling back to TEST_ATHLETE_ID: {settings.TEST_ATHLETE_ID}")
        try:
            exists = await _run_supabase_call(
                lambda: db.table("athletes")
                .select("id")
                .eq("id", settings.TEST_ATHLETE_ID)
                .maybe_single()
                .execute()
            )
            if exists and exists.data and exists.data.get("id"):
                return settings.TEST_ATHLETE_ID
        except Exception:
            pass
        raise HTTPException(
            status_code=401,
            detail="Invalid or stale auth token (local Supabase was likely reset). Please sign out and sign in again.",
        )
    raise HTTPException(status_code=401, detail="Invalid or missing token")


# ---------------------------------------------------------------------------
# User config — all admin-controlled fields in a single auth.get_user() call
# ---------------------------------------------------------------------------

# Users whose expired trial this process has already written back as free.
_trial_expiry_written: set[str] = set()


def _apply_trial_expiry(tier: str, app_meta: dict, user: Any) -> str:
    """
    New accounts get a 14-day trial (app_metadata.trial_ends_at). Once it passes the
    account is free from the very next request; the downgrade is also written back to
    app_metadata and athletes.tier in the background so the app and admin views agree.
    """
    from app.services.tiers import effective_tier, persist_trial_expiry

    effective = effective_tier(tier, app_meta, getattr(user, "created_at", None))
    user_id = getattr(user, "id", None)
    if effective != tier and user_id and user_id not in _trial_expiry_written:
        _trial_expiry_written.add(user_id)
        from app.services.background import spawn as spawn_background

        async def _persist() -> None:
            try:
                await asyncio.to_thread(persist_trial_expiry, get_admin_db(), user_id)
            except Exception as e:  # noqa: BLE001 - retried by the next process/request
                _trial_expiry_written.discard(user_id)
                logger.warning("trial expiry write-back failed for user_id=%s: %s", user_id, e)

        try:
            spawn_background(_persist())
        except RuntimeError:  # no running loop
            _trial_expiry_written.discard(user_id)
    return effective


def _resolve_rate_limits(app_meta: dict, tier: str) -> tuple[int, int]:
    defaults = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["free"])
    try:
        rpm = int(app_meta["rate_limit_rpm"]) if app_meta.get("rate_limit_rpm") is not None else defaults["rpm"]
    except (TypeError, ValueError):
        rpm = defaults["rpm"]
    try:
        rph = int(app_meta["rate_limit_rph"]) if app_meta.get("rate_limit_rph") is not None else defaults["rph"]
    except (TypeError, ValueError):
        rph = defaults["rph"]
    return max(1, rpm), max(1, rph)


async def get_user_config(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> UserConfig:
    """
    Single dependency that reads all admin-controlled fields from app_metadata.
    Source of truth is always app_metadata — user_metadata is never consulted
    for tier, model, or rate-limit values because users can write user_metadata
    themselves via the Supabase client SDK.
    """
    token = credentials.credentials
    fallback_model = (settings.GEMINI_MODEL or "").strip() or "gemini-3.5-flash-lite"
    fallback_analysis = (settings.GEMINI_ANALYSIS_MODEL or "").strip() or "gemini-3.1-flash-lite"

    try:
        user_res = await _auth_get_user(db, token)
        reject_third_party_oauth_token(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}

        tier_raw = str(app_meta.get("tier") or "free").strip().lower()
        tier = tier_raw if tier_raw in VALID_TIERS else "free"
        tier = _apply_trial_expiry(tier, app_meta, u)

        model_raw = app_meta.get("gemini_model")
        model = model_raw.strip() if isinstance(model_raw, str) and model_raw.strip() else fallback_model

        analysis_raw = app_meta.get("gemini_analysis_model")
        analysis_model = (
            analysis_raw.strip()
            if isinstance(analysis_raw, str) and analysis_raw.strip()
            else fallback_analysis
        )

        rpm, rph = _resolve_rate_limits(app_meta, tier)

        return UserConfig(
            user_id=u.id,
            tier=tier,
            gemini_model=model,
            gemini_analysis_model=analysis_model,
            rate_limit_rpm=rpm,
            rate_limit_rph=rph,
            is_admin=bool(app_meta.get("is_admin", False)),
        )
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e).lower()
        is_auth_error = any(k in err_str for k in ("invalid", "expired", "unauthorized", "jwt", "token"))
        if is_auth_error:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        defaults = TIER_DEFAULTS["free"]
        return UserConfig(
            user_id="",
            tier="free",
            gemini_model=fallback_model,
            gemini_analysis_model=fallback_analysis,
            rate_limit_rpm=defaults["rpm"],
            rate_limit_rph=defaults["rph"],
            is_admin=False,
        )


# ---------------------------------------------------------------------------
# Rate limiting dependency
# ---------------------------------------------------------------------------

async def require_ai_rate_limit(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
):
    """
    Enforces per-user sliding-window rate limits on AI endpoints.
    Limits come from app_metadata overrides or tier defaults.
    """
    await _rate_limiter.require(
        key=f"{athlete_id}:ai:minute",
        limit=config.rate_limit_rpm,
        window_seconds=60,
        detail=f"Rate limit exceeded: max {config.rate_limit_rpm} AI requests per minute.",
    )
    await _rate_limiter.require(
        key=f"{athlete_id}:ai:hour",
        limit=config.rate_limit_rph,
        window_seconds=3600,
        detail=f"Rate limit exceeded: max {config.rate_limit_rph} AI requests per hour.",
    )
    rpd = TIER_DEFAULTS.get(config.tier, TIER_DEFAULTS["free"])["rpd"]
    await _rate_limiter.require(
        key=f"{athlete_id}:ai:day",
        limit=max(rpd, config.rate_limit_rph),  # an admin rph override also lifts the daily cap
        window_seconds=86400,
        detail="Daily AI limit reached. It resets within 24 hours.",
    )


def action_rate_limit(name: str, limit: int, window_seconds: int, detail: str):
    """
    Per-athlete limit for expensive non-AI actions (provider backfills, reprocessing,
    third-party logins). Use as ``Depends(action_rate_limit(...))``.
    """

    async def _dep(athlete_id: str = Depends(get_current_athlete)) -> None:
        await _rate_limiter.require(
            key=f"{athlete_id}:{name}", limit=limit, window_seconds=window_seconds, detail=detail
        )

    return _dep


# ---------------------------------------------------------------------------
# Backward-compatible single-value helpers
# (used by analysis.py, plan.py — no changes needed in those routers)
# ---------------------------------------------------------------------------

async def get_current_user_tier(
    config: UserConfig = Depends(get_user_config),
) -> str:
    return config.tier

async def get_current_gemini_model(
    config: UserConfig = Depends(get_user_config),
) -> str:
    return config.gemini_model

async def get_current_gemini_analysis_model(
    config: UserConfig = Depends(get_user_config),
) -> str:
    return config.gemini_analysis_model
