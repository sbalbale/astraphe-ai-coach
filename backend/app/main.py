import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.routers import workouts, activity_detail, coach, athlete, biometrics, sync, plan, debug, analysis, training_plans, admin, notifications
from app.config import settings
from app.core.rate_limiter import RateLimiter
from app.core.redis import close_redis, ping_redis
from app.services.token_refresh import token_refresh_loop

_ip_rate_limiter = RateLimiter()

_docs_enabled = settings.APP_ENV != "production"

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
)


@app.on_event("startup")
async def start_token_refresh_loop():
    asyncio.create_task(token_refresh_loop())


@app.on_event("shutdown")
async def shutdown_redis():
    await close_redis()


@app.on_event("startup")
async def validate_production_config():
    if settings.APP_ENV == "production" and settings.TEST_ATHLETE_ID:
        raise RuntimeError(
            "TEST_ATHLETE_ID must not be set when APP_ENV=production. "
            "Remove it from your environment before starting the server."
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
        _preview = _hmac_key[:4].decode("utf-8", errors="replace") + "..." + _hmac_key[-4:].decode("utf-8", errors="replace")
        print(f"[startup] WHOOP HMAC key from {_source}: '{_preview}' (len={len(_hmac_key)})")
        if settings.WHOOP_WEBHOOK_SECRET and settings.WHOOP_CLIENT_SECRET:
            ws = settings.WHOOP_WEBHOOK_SECRET.strip()
            cs = settings.WHOOP_CLIENT_SECRET.strip()
            if ws != cs:
                print(
                    "[startup] WARNING: WHOOP_WEBHOOK_SECRET and WHOOP_CLIENT_SECRET differ. "
                    "WHOOP signs webhooks with the client_secret from your Developer Dashboard. "
                    "Set WHOOP_WEBHOOK_SECRET to the same value as WHOOP_CLIENT_SECRET."
                )
    else:
        print("[startup] WARNING: No WHOOP HMAC key — webhook signatures will be rejected")

    if settings.APP_ENV == "development":
        from app.services.strava_webhook_sub import subscription_matches_app_base

        ok, detail = subscription_matches_app_base()
        if ok:
            print(f"[startup] {detail}")
        else:
            print(f"[startup] WARNING: {detail}")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # /health is exempt — uptime monitors shouldn't consume quota
        if request.url.path == "/health":
            return await call_next(request)

        # Real IP: Cloud Run and ngrok both set X-Forwarded-For; take the first (client) address.
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

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
    "https://app.astrapeai.com",
    "capacitor://localhost",   # Capacitor iOS webview
    "http://localhost",        # Capacitor Android webview
    "http://localhost:5173",   # local dev (vite)
    "http://localhost:4173",   # local preview
    "http://127.0.0.1:5173",
    "https://astrape-ai-coach.web.app",
    "https://astrape-ai-coach.firebaseapp.com",
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(athlete.router)
app.include_router(workouts.router)
app.include_router(activity_detail.router)
app.include_router(biometrics.router)
app.include_router(coach.router)
app.include_router(sync.router)
app.include_router(plan.router)
app.include_router(training_plans.router)
if settings.APP_ENV != "production":
    app.include_router(debug.router)
app.include_router(analysis.router)
app.include_router(admin.router)
app.include_router(notifications.router)

@app.get("/health")
async def health_check():
    redis_ok = await ping_redis()
    return {
        "status": "healthy",
        "service": "ASTRAPE API",
        "redis": "connected" if redis_ok else "unavailable",
    }
