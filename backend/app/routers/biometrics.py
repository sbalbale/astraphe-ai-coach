from fastapi import APIRouter, Depends, BackgroundTasks, Query
from typing import Optional
import asyncio
from datetime import date, datetime, timedelta, timezone
import math

from app.core.cache_invalidation import invalidate_athlete_caches
from app.models.biometrics import DailyBiometrics
from app.services.processing import fetch_rows_newest_first, process_and_save_biometrics
from app.dependencies import get_current_athlete, get_user_db

router = APIRouter(prefix="/v1/biometrics", tags=["Biometrics"])


def _attach_running_zscores(rows: list[dict], field: str, z_field: str, span: int = 7) -> None:
    """
    Single-pass EWMA + EWMVar over `rows` (oldest -> newest), writing `z_field` on
    each row. The z-score on row i is computed against the EWMA *just before* i
    so today's value isn't allowed to influence its own baseline.
    """
    if not rows:
        return
    alpha = 2.0 / (float(span) + 1.0)
    ewma: Optional[float] = None
    ewmvar: float = 0.0
    seen = 0
    for row in rows:
        raw = row.get(field)
        try:
            v = float(raw) if raw is not None else None
        except Exception:
            v = None
        if v is None or v == 0:
            row[z_field] = None
            continue

        if ewma is None or seen < 2:
            row[z_field] = 0.0 if seen == 0 else None
        else:
            sd = math.sqrt(max(ewmvar, 0.0))
            row[z_field] = 0.0 if sd <= 1e-9 else (v - ewma) / sd

        if ewma is None:
            ewma = v
            ewmvar = 0.0
        else:
            diff = v - ewma
            ewma = ewma + alpha * diff
            ewmvar = (1.0 - alpha) * (ewmvar + alpha * (diff ** 2))
        seen += 1

def _iso_utc(value) -> str:
    """Normalise a PostgREST timestamptz string (e.g. '...+00:00') to ISO UTC with 'Z'."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    if not all and not end_date:
        # The athlete's local today, so east-of-UTC athletes see this morning's sleep.
        from app.services.time_utils import athlete_local_date

        today = await asyncio.to_thread(athlete_local_date, db, athlete_id)
    else:
        today = date.today()

    # Resolve range
    if all:
        resolved_start = start_date  # may be None (meaning: no lower bound)
        resolved_end = end_date      # may be None (meaning: no upper bound)
    elif start_date or end_date:
        resolved_start = start_date
        resolved_end = end_date or today
    else:
        # Default: most recent `limit` days
        resolved_end = (before - timedelta(days=1)) if before else today
        resolved_start = resolved_end - timedelta(days=safe_limit - 1)

    def bio_q():
        q = db.table("biometrics").select("*").eq("athlete_id", athlete_id)
        if resolved_start:
            q = q.gte("date", resolved_start.isoformat())
        if resolved_end:
            q = q.lte("date", resolved_end.isoformat())
        return q

    q = bio_q()

    # If not explicitly asking for "all", cap the response size
    if not all and not (start_date or end_date):
        # Desc + limit, then reverse to preserve oldest->newest order for charts.
        bio_res = await asyncio.to_thread(q.order("date", desc=True).limit(safe_limit + 1).execute)
        bio_rows = bio_res.data or []
        has_more = len(bio_rows) > safe_limit
        bio_rows = bio_rows[:safe_limit]
        bio_rows.reverse()
        next_before = bio_rows[0]["date"] if has_more and bio_rows else None
    else:
        bio_rows = await asyncio.to_thread(fetch_rows_newest_first, bio_q, "date")
        has_more = False
        next_before = None
    
    # Fetch individual sleep periods for the range
    def periods_q():
        q = db.table("sleep_periods").select("*").eq("athlete_id", athlete_id)
        if resolved_start:
            q = q.gte("date", resolved_start.isoformat())
        if resolved_end:
            q = q.lte("date", resolved_end.isoformat())
        return q

    periods_rows = await asyncio.to_thread(fetch_rows_newest_first, periods_q, "started_at")
    periods_by_date = {}
    for p in periods_rows:
        d = p["date"]
        if d not in periods_by_date:
            periods_by_date[d] = []
        periods_by_date[d].append(p)

    # Sleep-stage timeline (hypnogram) segments, keyed by the same night date.
    # Paged, newest first: ~20 segments a night pass PostgREST's 1000-row cap within a 60-day
    # page, and a single oldest-first read dropped the *newest* nights' segments, so their
    # sleep-stage timeline disappeared once enough nights had stages.
    def seg_q():
        q = db.table("sleep_stage_segments").select("date, stage, start_at, end_at").eq("athlete_id", athlete_id)
        if resolved_start:
            q = q.gte("date", resolved_start.isoformat())
        if resolved_end:
            q = q.lte("date", resolved_end.isoformat())
        return q

    seg_rows = await asyncio.to_thread(fetch_rows_newest_first, seg_q, "start_at")
    segments_by_date: dict = {}
    for s in seg_rows:
        segments_by_date.setdefault(s["date"], []).append(
            {"stage": s["stage"], "start_at": _iso_utc(s["start_at"]), "end_at": _iso_utc(s["end_at"])}
        )

    hrv_data = []
    sleep_data = []
    sleep_scores = []
    series = []

    # Attach per-row HRV/RHR z-scores (single pass, running EWMA span=7).
    # Each row's z is computed against the EWMA up to *but excluding* that row,
    # so today's reading can't inflate its own baseline.
    _attach_running_zscores(bio_rows, "hrv_rmssd", "hrv_z", span=7)
    _attach_running_zscores(bio_rows, "resting_hr", "rhr_z", span=7)

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
        row["stage_segments"] = segments_by_date.get(row["date"], [])
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
    background_tasks.add_task(invalidate_athlete_caches, athlete_id)
    return {"status": "success", "message": "Biometrics recorded and recovery analysis queued", "date": payload.date}

@router.get("/heart-rate")
async def get_heart_rate_day(
    day: Optional[date] = Query(None, alias="date"),
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    """
    One local day of all-day heart rate (Garmin: 2-minute averages) with the day's
    workouts (recorded, or detected from this series: ``detected``), sleep, and the
    last 30 days of resting HR. ``date`` defaults to the athlete's local today.
    ``samples`` is empty when the day has no series.
    """
    from app.core.body_cache import HR_PAST_DAY_TTL, HR_TODAY_TTL, get_cached, set_cached
    from app.services.heart_rate_series import build_heart_rate_day
    from app.services.time_utils import athlete_local_date

    today = await asyncio.to_thread(athlete_local_date, db, athlete_id)
    day = day or today
    name = f"hrday:{day.isoformat()}"
    cached = await get_cached(athlete_id, name)
    if cached is not None:
        return cached
    payload = await asyncio.to_thread(build_heart_rate_day, db, athlete_id, day)
    await set_cached(athlete_id, name, payload, HR_TODAY_TTL if day >= today else HR_PAST_DAY_TTL)
    return payload
