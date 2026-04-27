from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class WorkoutPayload(BaseModel):
    athlete_id: str
    source: str = Field(..., description="e.g., garmin, apple_health")
    workout_type: str = Field(..., description="e.g., cycling, running")
    start_time: datetime
    duration_seconds: int
    normalized_power: Optional[int] = None
    average_hr: Optional[int] = None
    ftp_at_time: int = Field(default=250, description="The athlete's FTP at the time of the workout")
    
class ChatMessage(BaseModel):
    athlete_id: str
    message: str
    recent_tss: Optional[float] = 0.0