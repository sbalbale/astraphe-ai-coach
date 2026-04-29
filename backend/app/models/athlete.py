from pydantic import BaseModel
from datetime import date
from typing import Optional, List

class AthleteState(BaseModel):
    athlete_id: str
    display_name: str
    date: date
    days_on_platform: int
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
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    ftp_watts: Optional[int] = None
    max_hr: Optional[int] = None
    threshold_hr: Optional[int] = None
    threshold_pace: Optional[str] = None # String format like "5:00"
    sport_focus: Optional[List[str]] = None
    notification_settings: Optional[dict] = None
    privacy_settings: Optional[dict] = None
    measurement_units: Optional[str] = None
    time_format: Optional[str] = None
    timezone_offset_min: Optional[int] = None