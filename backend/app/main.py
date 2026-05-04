from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import workouts, coach, athlete, biometrics, sync, plan, debug, analysis, training_plans

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(athlete.router)
app.include_router(workouts.router)
app.include_router(biometrics.router)
app.include_router(coach.router)
app.include_router(sync.router)
app.include_router(plan.router)
app.include_router(training_plans.router)
app.include_router(debug.router)
app.include_router(analysis.router)

@app.get("/health")
async def health_check():
    print("[health] Checked")
    return {"status": "healthy", "service": "ASTRAPE API"}