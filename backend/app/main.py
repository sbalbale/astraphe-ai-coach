from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="ASTRAPE Backend API",
    description="Mathematical and AI orchestration core for the ASTRAPE Coach",
    version="1.0.0"
)

# Set up CORS so the Svelte mobile client can communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A simple health check route
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ASTRAPE API"}
