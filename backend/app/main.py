from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.routers import workouts, activity_detail, coach, athlete, biometrics, sync, plan, debug, analysis, training_plans, admin
from app.config import settings

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)


@app.on_event("startup")
async def validate_production_config():
    if settings.APP_ENV == "production" and settings.TEST_ATHLETE_ID:
        raise RuntimeError(
            "TEST_ATHLETE_ID must not be set when APP_ENV=production. "
            "Remove it from your environment before starting the server."
        )
    if (
        settings.APP_ENV == "production"
        and settings.WHOOP_CLIENT_SECRET
        and settings.WHOOP_WEBHOOK_SECRET
        and settings.WHOOP_CLIENT_SECRET == settings.WHOOP_WEBHOOK_SECRET
    ):
        import warnings
        warnings.warn(
            "WHOOP_CLIENT_SECRET and WHOOP_WEBHOOK_SECRET are identical. "
            "These should be distinct secrets.",
            stacklevel=1,
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

# Enumerate the actual origins that should be allowed.
# allow_origins=["*"] is incompatible with allow_credentials=True per the CORS spec.
ALLOWED_ORIGINS = [
    "https://astrape.app",
    "capacitor://localhost",   # Capacitor iOS webview
    "http://localhost",        # Capacitor Android webview
    "http://localhost:5173",   # local dev (vite)
    "http://localhost:4173",   # local preview
    "http://127.0.0.1:5173",
]

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(athlete.router)
app.include_router(workouts.router)
app.include_router(activity_detail.router)
app.include_router(biometrics.router)
app.include_router(coach.router)
app.include_router(sync.router)
app.include_router(plan.router)
app.include_router(training_plans.router)
app.include_router(debug.router)
app.include_router(analysis.router)
app.include_router(admin.router)

@app.get("/health")
async def health_check():
    print("[health] Checked")
    return {"status": "healthy", "service": "ASTRAPE API"}
