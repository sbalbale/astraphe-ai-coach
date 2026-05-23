from dataclasses import dataclass

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.core.rate_limiter import RateLimiter

security = HTTPBearer()

# Per-tier default rate limits for AI endpoints (requests per minute / per hour).
# Individual users can be given overrides via app_metadata.rate_limit_rpm / rate_limit_rph.
TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "free":    {"rpm": 5,  "rph": 20},
    "trial":   {"rpm": 15, "rph": 75},
    "premium": {"rpm": 40, "rph": 200},
}

VALID_TIERS = frozenset(TIER_DEFAULTS.keys())


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
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def get_admin_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY)

def _with_auth_token(db: Client, token: str) -> Client:
    try:
        db.postgrest.auth(token)
    except Exception:
        try:
            db.postgrest.session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception:
            pass
    return db

async def get_user_db(credentials: HTTPAuthorizationCredentials = Security(security)) -> Client:
    token = credentials.credentials
    return _with_auth_token(get_db(), token)


# ---------------------------------------------------------------------------
# Athlete identity
# ---------------------------------------------------------------------------

async def get_current_user_email(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str | None:
    """Returns the authenticated user's email address, or None on failure."""
    try:
        user_res = db.auth.get_user(credentials.credentials)
        return getattr(user_res.user, "email", None)
    except Exception:
        return None


async def get_current_athlete(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str:
    """Extracts athlete_id from Supabase JWT."""
    import asyncio as _asyncio
    token = credentials.credentials
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            user = db.auth.get_user(token)
            user_id = user.user.id
            if settings.APP_ENV == "development":
                print(f"Auth DEBUG: user_id={user_id}")

            athlete_res = db.table("athletes").select("id").eq("user_id", user_id).execute()
            if settings.APP_ENV == "development":
                print(f"Auth DEBUG: athlete_res={athlete_res.data}")

            if not athlete_res.data:
                raise HTTPException(status_code=404, detail="Athlete profile not found")
            return athlete_res.data[0]["id"]
        except HTTPException:
            raise
        except Exception as e:
            # PGRST002 = PostgREST schema cache not yet loaded (transient on cold start).
            # Retry once after a short wait; on second failure fall through to 401.
            if "PGRST002" in str(e) and attempt == 0:
                print(f"Auth: PostgREST schema cache miss, retrying… ({e})")
                await _asyncio.sleep(0.5)
                last_exc = e
                continue
            last_exc = e
            break

    print(f"Auth error: {last_exc}")
    if settings.APP_ENV == "development" and settings.TEST_ATHLETE_ID:
        print(f"WARNING: Falling back to TEST_ATHLETE_ID: {settings.TEST_ATHLETE_ID}")
        try:
            exists = (
                db.table("athletes")
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
    raise HTTPException(status_code=401, detail=f"Invalid or missing token: {last_exc}")


# ---------------------------------------------------------------------------
# User config — all admin-controlled fields in a single auth.get_user() call
# ---------------------------------------------------------------------------

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
    fallback_model = (settings.GEMINI_MODEL or "").strip() or "gemma-4-31b-it"
    fallback_analysis = (settings.GEMINI_ANALYSIS_MODEL or "").strip() or "gemini-flash-lite-latest"

    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}

        tier_raw = str(app_meta.get("tier") or "free").strip().lower()
        tier = tier_raw if tier_raw in VALID_TIERS else "free"

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
        # If get_user returned None the token is invalid — fail hard.
        # For other transient errors (network blip, Supabase unavailable) fall
        # back to free-tier defaults so the request isn't silently granted
        # elevated access, but we do NOT suppress a definitive auth failure.
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
