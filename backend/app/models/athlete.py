from pydantic import BaseModel, Field, field_validator
from datetime import date
from typing import Any, Optional, List

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
    hrv_baseline_7d: Optional[float] = None
    hrv_sd_7d: Optional[float] = None
    hrv_z: Optional[float] = None
    resting_hr: Optional[int]
    rhr_baseline_7d: Optional[float] = None
    rhr_sd_7d: Optional[float] = None
    rhr_z: Optional[float] = None
    sleep_hours: Optional[float]
    sleep_score: Optional[int]
    sleep_debt_min: Optional[int] = None
    recovery_score: Optional[int]
    readiness_score: int
    readiness_label: str
    readiness_recommendation: str

class AthleteProfileUpdate(BaseModel):
    # Bounds keep nonsense out of zone/TSS maths and prompts (display_name is shown to
    # the coach), and stop a huge timezone offset from breaking webhook date maths.
    display_name: Optional[str] = Field(None, max_length=80)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, max_length=20)
    weight_kg: Optional[float] = Field(None, ge=20, le=350)
    height_cm: Optional[float] = Field(None, ge=80, le=260)
    ftp_watts: Optional[int] = Field(None, ge=20, le=800)
    max_hr: Optional[int] = Field(None, ge=80, le=250)
    resting_hr: Optional[int] = Field(None, ge=20, le=140)
    hr_zone_method: Optional[str] = Field(None, max_length=20)
    threshold_hr: Optional[int] = Field(None, ge=60, le=240)
    threshold_pace: Optional[str] = Field(None, max_length=12)  # e.g. "5:00"
    sport_focus: Optional[List[str]] = Field(None, max_length=10)
    notification_settings: Optional[dict[str, Any]] = None
    privacy_settings: Optional[dict[str, Any]] = None
    measurement_units: Optional[str] = Field(None, max_length=10)
    time_format: Optional[str] = Field(None, max_length=10)
    timezone_offset_min: Optional[int] = Field(None, ge=-840, le=840)

    @field_validator("sport_focus")
    @classmethod
    def _short_sports(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and any(len(str(x)) > 30 for x in v):
            raise ValueError("sport names must be 30 characters or fewer")
        return v

    @field_validator("notification_settings")
    @classmethod
    def _notification_settings(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """The nested v2 shape (types / quiet / texts). Stored normalized: unknown keys and
        bad values are dropped, so only what the app and the scheduler understand is kept."""
        if v is None:
            return v
        import json

        if len(json.dumps(v, default=str)) > 4000:
            raise ValueError("notification settings are too large")
        from app.services.notification_prefs import effective

        return effective(v)

    @field_validator("privacy_settings")
    @classmethod
    def _small_flat_settings(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if v is None:
            return v
        if len(v) > 30:
            raise ValueError("too many settings")
        for key, val in v.items():
            if len(str(key)) > 40 or not isinstance(val, (bool, int, float, str, type(None))):
                raise ValueError("settings must be flat key/value pairs")
            if isinstance(val, str) and len(val) > 200:
                raise ValueError("setting values must be short")
        return v