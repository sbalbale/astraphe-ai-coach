from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class WorkoutPayload(BaseModel):
    source: str = Field(..., description="e.g., garmin, apple_health")
    external_id: Optional[str] = None
    workout_type: str = Field(alias="sport", description="e.g., cycling, running")
    start_time: datetime = Field(alias="started_at")
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None
    normalized_power: Optional[int] = Field(None, alias="norm_power_w")
    average_hr: Optional[int] = Field(None, alias="avg_hr")
    max_hr: Optional[int] = None
    avg_pace_sec_km: Optional[int] = None
    ftp_at_time: int = Field(default=250)
    
    # HR Zones
    hr_zone_1_pct: Optional[int] = None
    hr_zone_2_pct: Optional[int] = None
    hr_zone_3_pct: Optional[int] = None
    hr_zone_4_pct: Optional[int] = None
    hr_zone_5_pct: Optional[int] = None