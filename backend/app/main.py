from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import workouts, activity_detail, coach, athlete, biometrics, sync, plan, debug, analysis, training_plans, admin

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)

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
