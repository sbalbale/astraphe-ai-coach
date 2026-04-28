from pydantic import BaseModel
from datetime import date
from typing import Optional, Dict, Any

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
    display_name: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    ftp_watts: Optional[int] = None
    max_hr: Optional[int] = None
    threshold_hr: Optional[int] = None
    threshold_pace: Optional[str] = None # Using string for pace like '5:00'
    primary_sport: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None