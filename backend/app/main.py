import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.routers import workouts, activity_detail, coach, athlete, biometrics, sync, garmin_sync, plan, debug, analysis, training_plans, admin, notifications, messaging, weight
from app.config import settings
from app.core.rate_limiter import RateLimiter
from app.core.redis import close_redis, describe_redis_url, ping_redis
from app.core.supabase_health import ping_supabase
from app.services.token_refresh import token_refresh_loop
from app.services.garmin import poll_loop as garmin_poll_loop

logger = logging.getLogger(__name__)
_ip_rate_limiter = RateLimiter()

_docs_enabled = settings.APP_ENV != "production"

app = FastAPI(
    title="ASTRAPHE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPHE Coach",
    version=settings.APP_VERSION,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)


# Strong references so the event loop can't garbage-collect running loops.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.on_event("startup")
async def start_token_refresh_loop():
    if not settings.BACKGROUND_LOOPS_ENABLED:
        return
    _spawn(token_refresh_loop())


@app.on_event("startup")
async def start_strava_startup_backfill():
    if not (settings.BACKGROUND_LOOPS_ENABLED and settings.STRAVA_STARTUP_BACKFILL_ENABLED):
        return
    from app.services.strava import backfill_recent

    _spawn(backfill_recent(hours=settings.STRAVA_STARTUP_BACKFILL_HOURS))


@app.on_event("startup")
async def start_whoop_startup_backfill():
    if not (settings.BACKGROUND_LOOPS_ENABLED and settings.WHOOP_STARTUP_BACKFILL_ENABLED):
        return
    from app.services.whoop_backfill import backfill_recent

    _spawn(backfill_recent(hours=settings.WHOOP_STARTUP_BACKFILL_HOURS))


@app.on_event("startup")
async def start_garmin_poll_loop():
    # Garmin has no webhook (see docs/GARMIN_INTEGRATION.md), so this loop is
    # the only sync path — it also self-heals on restart since its first
    # tick runs immediately, before the first sleep.
    if not settings.BACKGROUND_LOOPS_ENABLED:
        return
    _spawn(garmin_poll_loop())


@app.on_event("startup")
async def start_notification_loop():
    # Morning readiness, evening digest, weekly summary, sync problems.
    # Every send is claimed in notification_log, so running in each replica is safe.
    if not (settings.BACKGROUND_LOOPS_ENABLED and settings.NOTIFICATION_SCHEDULER_ENABLED):
        return
    from app.services.notification_scheduler import notification_loop

    _spawn(notification_loop())


@app.on_event("shutdown")
async def shutdown_redis():
    await close_redis()


@app.on_event("startup")
async def validate_production_config():
    logger.warning(
        "[startup] APP_ENV=%s SUPABASE_URL=%s REDIS_URL=%s",
        settings.APP_ENV,
        settings.SUPABASE_URL,
        describe_redis_url(settings.REDIS_URL),
    )
    if settings.APP_ENV == "development" and "host.docker.internal:8001" in settings.SUPABASE_URL:
        logger.warning(
            "[startup] WARNING: backend is using stale Supabase URL %s; expected backend/.env dev URL.",
            settings.SUPABASE_URL,
        )

    if settings.APP_ENV == "production" and settings.TEST_ATHLETE_ID:
        raise RuntimeError(
            "TEST_ATHLETE_ID must not be set when APP_ENV=production. "
            "Remove it from your environment before starting the server."
        )
    if settings.APP_ENV == "production":
        # Without a valid key, provider refresh tokens would be written in plaintext.
        from app.services.token_crypto import _fernet

        if _fernet() is None:
            raise RuntimeError(
                "OAUTH_TOKEN_ENCRYPTION_KEY is missing or invalid; refusing to start in production "
                "(provider tokens would be stored unencrypted)."
            )
    # WHOOP uses the OAuth client secret as the HMAC key for webhook signatures.
    # WHOOP_WEBHOOK_SECRET must equal WHOOP_CLIENT_SECRET — this is correct by design.
    if settings.APP_ENV == "production" and not settings.WHOOP_WEBHOOK_SECRET:
        import warnings
        warnings.warn(
            "WHOOP_WEBHOOK_SECRET is not set. Webhook signature verification will reject all WHOOP events.",
            stacklevel=1,
        )

    # Diagnostic: log which secret is used for WHOOP HMAC so misconfigs are obvious at startup.
    from app.services.whoop import _whoop_hmac_key
    _hmac_key = _whoop_hmac_key()
    if _hmac_key:
        _source = "WHOOP_WEBHOOK_SECRET" if settings.WHOOP_WEBHOOK_SECRET else "WHOOP_CLIENT_SECRET"
        logger.info("[startup] WHOOP HMAC key from %s (len=%s)", _source, len(_hmac_key))
        if settings.WHOOP_WEBHOOK_SECRET and settings.WHOOP_CLIENT_SECRET:
            ws = settings.WHOOP_WEBHOOK_SECRET.strip()
            cs = settings.WHOOP_CLIENT_SECRET.strip()
            if ws != cs:
                logger.warning(
                    "[startup] WARNING: WHOOP_WEBHOOK_SECRET and WHOOP_CLIENT_SECRET differ. "
                    "WHOOP signs webhooks with the client_secret from your Developer Dashboard. "
                    "Set WHOOP_WEBHOOK_SECRET to the same value as WHOOP_CLIENT_SECRET."
                )
    else:
        logger.warning("[startup] WARNING: No WHOOP HMAC key — webhook signatures will be rejected")

    if settings.APP_ENV == "production":
        _wc = (settings.WHOOP_CLIENT_SECRET or "").strip()
        if not _wc:
            logger.warning("[startup] WARNING: WHOOP_CLIENT_SECRET is unset — WHOOP OAuth token exchange will fail")
        elif settings.WHOOP_WEBHOOK_SECRET and settings.WHOOP_CLIENT_SECRET:
            _ws = settings.WHOOP_WEBHOOK_SECRET.strip()
            _cs = settings.WHOOP_CLIENT_SECRET.strip()
            if _ws != _cs:
                logger.warning(
                    "[startup] WARNING: WHOOP_WEBHOOK_SECRET and WHOOP_CLIENT_SECRET differ — "
                    "token exchange uses CLIENT_SECRET; webhooks use WEBHOOK_SECRET (or CLIENT_SECRET fallback)."
                )

    if settings.APP_ENV == "development":
        from app.services.strava_webhook_sub import subscription_matches_app_base

        ok, detail = subscription_matches_app_base()
        if ok:
            logger.info("[startup] %s", detail)
        else:
            logger.warning("[startup] WARNING: %s", detail)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


def _valid_ip(value: str | None) -> str | None:
    import ipaddress

    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    """
    The caller's IP, for per-IP rate limiting.

    The API is reached through Cloudflare, then the cluster ingress. Cloudflare sets
    CF-Connecting-IP to the real client and overwrites any value the client sends,
    so it's the trustworthy source here. (The right-most X-Forwarded-For hop, used
    before, is whichever proxy sits closest to us, so every user shared one bucket.)
    Only traffic that can reach the origin without Cloudflare (the LAN) could set it
    itself.

    Without the header (local dev, direct-to-origin), fall back to the right-most
    X-Forwarded-For entry, never the first, which anyone can forge.
    """
    cf_ip = _valid_ip(request.headers.get("CF-Connecting-IP"))
    if cf_ip:
        return cf_ip
    forwarded_for = request.headers.get("X-Forwarded-For") or ""
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # /health is exempt — uptime monitors shouldn't consume quota. Provider webhooks
        # are exempt too: they come from a handful of provider IPs (so they'd hit the
        # per-IP limit at scale and get dropped) and are verified by signature/ownership.
        path = request.url.path
        if path == "/health" or (path.startswith(f"{settings.API_PREFIX}/sync/") and path.endswith("/webhook")):
            return await call_next(request)

        ip = client_ip(request)

        allowed = await _ip_rate_limiter.check(ip, settings.IP_RATE_LIMIT_RPM, 60)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and try again."},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

# Enumerate the actual origins that should be allowed.
# allow_origins=["*"] is incompatible with allow_credentials=True per the CORS spec.
ALLOWED_ORIGINS = [
    "https://app.astrapheai.com",
    "capacitor://localhost",   # Capacitor iOS webview
    "http://localhost",        # Capacitor Android webview
    "https://astrapheai.web.app",
    "https://astrapheai.firebaseapp.com",
    "https://astraphe-ai-coach.web.app",
    "https://astraphe-ai-coach.firebaseapp.com",
]
_DEV_CORS = settings.APP_ENV != "production"
if _DEV_CORS:
    ALLOWED_ORIGINS += [
        "http://localhost:5173",   # local dev (vite)
        "http://localhost:4173",   # local preview
        "http://127.0.0.1:5173",
    ]

# Middleware order matters — Starlette wraps in reverse add order, so the last
# add_middleware call becomes the outermost layer (first to see incoming requests).
# Desired request flow: CORS → IPRateLimit → SecurityHeaders → app routes
# This ensures 429 responses still carry CORS headers, and OPTIONS preflights
# are resolved by CORS before they ever reach the rate limiter.
app.add_middleware(SecurityHeadersMiddleware)   # innermost
app.add_middleware(IPRateLimitMiddleware)        # middle
app.add_middleware(                             # outermost
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Any LAN IP (192.168.x.x / 10.x.x.x) for local iOS/device testing; dev only, since
    # in production it would let any page on the user's own network call the API.
    allow_origin_regex=r'https?://(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?' if _DEV_CORS else None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(athlete.router)
app.include_router(workouts.router)
app.include_router(activity_detail.router)
app.include_router(biometrics.router)
app.include_router(weight.router)
app.include_router(coach.router)
app.include_router(sync.router)
app.include_router(garmin_sync.router)
app.include_router(plan.router)
app.include_router(training_plans.router)
if settings.APP_ENV != "production":
    app.include_router(debug.router)
app.include_router(analysis.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(messaging.router)

@app.get("/health")
async def health_check():
    redis_ok = await ping_redis()
    supabase_ok = await ping_supabase()
    overall = "healthy" if supabase_ok else "degraded"
    return {
        "status": overall,
        "service": "ASTRAPHE API",
        "version": settings.APP_VERSION,
        "redis": "connected" if redis_ok else "unavailable",
        "supabase": "connected" if supabase_ok else "unavailable",
    }
