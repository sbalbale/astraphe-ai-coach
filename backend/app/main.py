from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import your routers
from app.routers import workouts, chat

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register both routers
app.include_router(workouts.router)
app.include_router(chat.router) # <-- Added this line

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ASTRAPE API"}