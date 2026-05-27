from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime

class WorkoutPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str = Field(..., description="e.g., garmin, apple_health")
    external_id: Optional[str] = None
    strava_activity_id: Optional[int] = None
    workout_type: str = Field(alias="sport", description="e.g., cycling, running")
    start_time: datetime = Field(alias="started_at")
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None
    average_power: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("avg_power_w", "average_watts", "avg_power"),
    )
    normalized_power: Optional[int] = Field(None, alias="norm_power_w")
    average_hr: Optional[int] = Field(None, alias="avg_hr")
    max_hr: Optional[int] = None
    avg_pace_sec_km: Optional[int] = None
    tss: Optional[float] = None
    title: Optional[str] = None
    ftp_at_time: int = Field(default=250)
    
    # HR Zones
    hr_zone_0_pct: Optional[int] = None
    hr_zone_1_pct: Optional[int] = None
    hr_zone_2_pct: Optional[int] = None
    hr_zone_3_pct: Optional[int] = None
    hr_zone_4_pct: Optional[int] = None
    hr_zone_5_pct: Optional[int] = None


class WorkoutUpdatePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workout_type: Optional[str] = Field(None, alias="sport")
    start_time: Optional[datetime] = Field(None, alias="started_at")
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None
    average_power: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("avg_power_w", "average_watts", "avg_power"),
    )
    normalized_power: Optional[int] = Field(None, alias="norm_power_w")
    average_hr: Optional[int] = Field(None, alias="avg_hr")
    max_hr: Optional[int] = None
    avg_pace_sec_km: Optional[int] = None
    tss: Optional[float] = None
    title: Optional[str] = None

    # HR Zones
    hr_zone_0_pct: Optional[int] = None
    hr_zone_1_pct: Optional[int] = None
    hr_zone_2_pct: Optional[int] = None
    hr_zone_3_pct: Optional[int] = None
    hr_zone_4_pct: Optional[int] = None
    hr_zone_5_pct: Optional[int] = None