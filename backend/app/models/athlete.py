from pydantic import BaseModel
from datetime import date
from typing import Optional

class AthleteState(BaseModel):
    athlete_id: str
    display_name: str
    date: date
    ctl: float
    atl: float
    tsb: float
    hrv_rmssd: Optional[float]
    hrv_delta_7d: Optional[float]
    resting_hr: Optional[int]
    sleep_hours: Optional[float]
    sleep_score: Optional[int]
    recovery_score: Optional[int]
    readiness_score: int
    readiness_label: str
    readiness_recommendation: str

class AthleteProfileUpdate(BaseModel):
    weight_kg: Optional[float]
    ftp_watts: Optional[int]
    max_hr: Optional[int]
    threshold_hr: Optional[int]
    threshold_pace: Optional[float]