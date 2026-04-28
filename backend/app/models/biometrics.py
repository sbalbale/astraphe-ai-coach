from pydantic import BaseModel
from typing import Optional
from datetime import date

class DailyBiometrics(BaseModel):
    date: date
    source: str
    hrv_rmssd: Optional[float]
    resting_hr: Optional[int]
    sleep_duration_min: Optional[int]
    sleep_score: Optional[int]
    sleep_deep_pct: Optional[float]
    sleep_rem_pct: Optional[float]
    sleep_need_min: Optional[int]
    sleep_debt_min: Optional[int]
    day_strain: Optional[float]
    skin_temp_deviation: Optional[float]
    spo2_pct: Optional[float]