from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

class DailyBiometrics(BaseModel):
    date: date
    source: str
    external_id: Optional[str] = None
    hrv_rmssd: Optional[float] = None
    resting_hr: Optional[int] = None
    sleep_duration_min: Optional[int] = None
    sleep_in_bed_min: Optional[int] = None
    sleep_score: Optional[int] = None # Astrape proprietary
    sleep_deep_pct: Optional[float] = None
    sleep_rem_pct: Optional[float] = None
    sleep_light_pct: Optional[float] = None
    sleep_awake_pct: Optional[float] = None
    sleep_bedtime: Optional[datetime] = None
    sleep_wakeup: Optional[datetime] = None
    sleep_need_min: Optional[int] = None
    sleep_debt_min: Optional[int] = None
    strain_score: Optional[int] = None # Astrape proprietary
    skin_temp: Optional[float] = None
    spo2_pct: Optional[float] = None
    recovery_score: Optional[int] = None # Astrape proprietary
    readiness_score: Optional[int] = None # Astrape proprietary
    is_nap: Optional[bool] = False

class SleepPeriodPayload(BaseModel):
    athlete_id: str
    date: date
    started_at: datetime
    ended_at: datetime
    duration_min: int
    in_bed_min: Optional[int] = None
    score: Optional[int] = None
    deep_pct: Optional[float] = None
    rem_pct: Optional[float] = None
    light_pct: Optional[float] = None
    awake_pct: Optional[float] = None
    is_nap: bool = False
    source: str
    external_id: Optional[str] = None