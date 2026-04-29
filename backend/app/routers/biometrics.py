from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Optional
from datetime import date, timedelta
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_biometrics
from app.dependencies import get_current_athlete, get_user_db

router = APIRouter(prefix="/v1/biometrics", tags=["Biometrics"])

@router.get("")
async def get_biometrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 60,
    before: Optional[date] = None,
    all: bool = False,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """
    Returns daily biometric readings.

    Defaults to a paginated window for performance:
    - `limit` (default 60) days, ending at `before` (exclusive) or today.

    You can still request explicit ranges with `start_date`/`end_date`,
    or set `all=true` to return the full series (not recommended for very large histories).
    """
    safe_limit = max(1, min(int(limit or 60), 3650))

    # Resolve range
    if all:
        resolved_start = start_date  # may be None (meaning: no lower bound)
        resolved_end = end_date      # may be None (meaning: no upper bound)
    elif start_date or end_date:
        resolved_start = start_date
        resolved_end = end_date or date.today()
    else:
        # Default: most recent `limit` days
        resolved_end = (before - timedelta(days=1)) if before else date.today()
        resolved_start = resolved_end - timedelta(days=safe_limit - 1)

    q = db.table("biometrics").select("*").eq("athlete_id", athlete_id)
    if resolved_start:
        q = q.gte("date", resolved_start.isoformat())
    if resolved_end:
        q = q.lte("date", resolved_end.isoformat())

    # If not explicitly asking for "all", cap the response size
    if not all and not (start_date or end_date):
        # Desc + limit, then reverse to preserve oldest->newest order for charts.
        bio_res = q.order("date", desc=True).limit(safe_limit + 1).execute()
        bio_rows = bio_res.data or []
        has_more = len(bio_rows) > safe_limit
        bio_rows = bio_rows[:safe_limit]
        bio_rows.reverse()
        next_before = bio_rows[0]["date"] if has_more and bio_rows else None
    else:
        bio_res = q.order("date").execute()
        bio_rows = bio_res.data or []
        has_more = False
        next_before = None
    
    # Fetch individual sleep periods for the range
    periods_q = db.table("sleep_periods").select("*").eq("athlete_id", athlete_id)
    if resolved_start:
        periods_q = periods_q.gte("date", resolved_start.isoformat())
    if resolved_end:
        periods_q = periods_q.lte("date", resolved_end.isoformat())
    periods_res = periods_q.order("started_at").execute()
    periods_by_date = {}
    for p in periods_res.data:
        d = p["date"]
        if d not in periods_by_date:
            periods_by_date[d] = []
        periods_by_date[d].append(p)

    hrv_data = []
    sleep_data = []
    sleep_scores = []
    series = []

    for row in bio_rows:
        if row.get("hrv_rmssd"):
            hrv_data.append(row["hrv_rmssd"])
        
        # Sleep Duration
        if row.get("sleep_duration_min"):
            sleep_data.append(row["sleep_duration_min"] / 60.0)
        
        # Sleep Score
        s_score = row.get("sleep_score") or 0
        sleep_scores.append(s_score)
        
        # Attach individual periods to the daily row for easy consumption
        row["periods"] = periods_by_date.get(row["date"], [])
        series.append(row)

    return {
        "hrvData": hrv_data,
        "sleepData": sleep_data,
        "sleepScores": sleep_scores,
        "series": series,
        "page": {
            "limit": safe_limit,
            "start_date": resolved_start.isoformat() if resolved_start else None,
            "end_date": resolved_end.isoformat() if resolved_end else None,
            "has_more": has_more,
            "next_before": next_before,
        },
    }

@router.post("/daily")
async def ingest_daily_biometrics(
    payload: DailyBiometrics,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Ingest a daily biometric summary and calculate recovery score in the background."""
    background_tasks.add_task(process_and_save_biometrics, payload, athlete_id, db)
    return {"status": "success", "message": "Biometrics recorded and recovery analysis queued", "date": payload.date}