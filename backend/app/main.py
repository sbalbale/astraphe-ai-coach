from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import workouts, coach, athlete, biometrics, sync, plan

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(athlete.router)
app.include_router(workouts.router)
app.include_router(biometrics.router)
app.include_router(coach.router)
app.include_router(sync.router)
app.include_router(plan.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ASTRAPE API"}