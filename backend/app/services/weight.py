"""
Weigh-ins (table ``weigh_ins``) and the one-per-day ``biometrics.weight_kg`` derived
from them. See supabase/migrations/20261109100000_weigh_ins.sql for how daily weights
written elsewhere become weigh-ins.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "weigh_ins"
# Which weigh-in sets the day's weight when a day has several (same order as
# processing._BIOMETRIC_FIELD_SOURCES["weight_kg"]); the latest wins within a source.
DAILY_SOURCE_PRIORITY = ("manual", "garmin", "whoop", "healthkit", "intervals_icu")
WEIGHT_RANGE_KG = (20.0, 350.0)
HISTORY_DAYS = 365


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_weight(kg: Any) -> float | None:
    try:
        v = round(float(kg), 2)
    except (TypeError, ValueError):
        return None
    return v if WEIGHT_RANGE_KG[0] <= v <= WEIGHT_RANGE_KG[1] else None


# ---- daily value ----------------------------------------------------------


def _source_rank(source: str | None) -> int:
    try:
        return DAILY_SOURCE_PRIORITY.index(source or "")
    except ValueError:
        return len(DAILY_SOURCE_PRIORITY)


def pick_daily(weigh_ins: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The weigh-in that stands for its day: best source, then the latest."""
    live = [w for w in weigh_ins if not w.get("deleted_at")]
    if not live:
        return None
    latest_first = sorted(live, key=lambda w: str(w.get("measured_at") or ""), reverse=True)
    return min(latest_first, key=lambda w: _source_rank(w.get("source")))


def refresh_daily_weight(db: Any, athlete_id: str, day: date) -> float | None:
    """Set biometrics.weight_kg for `day` from its weigh-ins (cleared when none are left)."""
    from app.services.processing import _upsert_biometrics_sync

    res = (
        db.table(TABLE).select("weight_kg, source, measured_at, deleted_at")
        .eq("athlete_id", athlete_id).eq("date", day.isoformat()).execute()
    )
    best = pick_daily((res.data if res else None) or [])
    cur = (
        db.table("biometrics").select("weight_kg, metric_sources")
        .eq("athlete_id", athlete_id).eq("date", day.isoformat()).limit(1).execute()
    )
    row = ((cur.data if cur else None) or [None])[0]
    sources = dict((row or {}).get("metric_sources") or {})
    if best is None:
        if row and row.get("weight_kg") is not None:
            sources.pop("weight_kg", None)
            db.table("biometrics").update({"weight_kg": None, "metric_sources": sources}).eq(
                "athlete_id", athlete_id
            ).eq("date", day.isoformat()).execute()
        return None
    kg = round(float(best["weight_kg"]), 2)
    sources["weight_kg"] = best.get("source") or "manual"
    _upsert_biometrics_sync(
        db, {"athlete_id": athlete_id, "date": day.isoformat(), "weight_kg": kg, "metric_sources": sources}
    )
    return kg


# ---- app actions -----------------------------------------------------------


def _offset_min(db: Any, athlete_id: str) -> int:
    from app.services.time_utils import fetch_athlete_timezone_offset_min

    return fetch_athlete_timezone_offset_min(db, athlete_id)


def log_weigh_in(
    db: Any, athlete_id: str, weight_kg: float, day: date | None = None,
    body_fat_pct: float | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """
    A weigh-in the athlete logged in the app. Today's is stamped now; an earlier day's
    has no real time (shown as just the date).
    """
    now = now or datetime.now(timezone.utc)
    offset = _offset_min(db, athlete_id)
    local_today = (now + timedelta(minutes=offset)).date()
    day = day or local_today
    if day == local_today:
        measured_at, time_known = now, True
    else:
        noon_local = datetime(day.year, day.month, day.day, 12, tzinfo=timezone(timedelta(minutes=offset)))
        measured_at, time_known = noon_local.astimezone(timezone.utc), False
    row = {
        "athlete_id": athlete_id,
        "date": day.isoformat(),
        "measured_at": measured_at.isoformat(),
        "weight_kg": weight_kg,
        "body_fat_pct": body_fat_pct,
        "source": "manual",
        "external_id": f"app:{uuid.uuid4()}",
        "time_known": time_known,
    }
    res = db.table(TABLE).insert(row).execute()
    saved = ((res.data if res else None) or [row])[0]
    refresh_daily_weight(db, athlete_id, day)
    return saved


def set_deleted(db: Any, athlete_id: str, weigh_in_id: str, deleted: bool) -> dict[str, Any] | None:
    """Soft-delete (or restore) a weigh-in and recompute its day. None if not found."""
    res = (
        db.table(TABLE).select("id, date").eq("athlete_id", athlete_id).eq("id", weigh_in_id)
        .limit(1).execute()
    )
    row = ((res.data if res else None) or [None])[0]
    if not row:
        return None
    stamp = datetime.now(timezone.utc).isoformat() if deleted else None
    db.table(TABLE).update({"deleted_at": stamp}).eq("athlete_id", athlete_id).eq("id", weigh_in_id).execute()
    refresh_daily_weight(db, athlete_id, date.fromisoformat(str(row["date"])[:10]))
    return row


def set_goal(db: Any, athlete_id: str, goal_kg: float | None) -> None:
    db.table("athletes").update({"goal_weight_kg": goal_kg}).eq("id", athlete_id).execute()


def weight_payload(db: Any, athlete_id: str, today: date) -> dict[str, Any]:
    """GET /v1/weight: the last year of weigh-ins (oldest first) plus goal and FTP."""
    since = (today - timedelta(days=HISTORY_DAYS + 1)).isoformat()
    res = (
        db.table(TABLE)
        .select("id, date, measured_at, weight_kg, body_fat_pct, source, time_known")
        .eq("athlete_id", athlete_id).gte("date", since).is_("deleted_at", "null")
        .order("measured_at").limit(2000).execute()
    )
    rows = (res.data if res else None) or []
    athlete = (
        db.table("athletes").select("goal_weight_kg, ftp_watts, measurement_units")
        .eq("id", athlete_id).maybe_single().execute()
    )
    a = (athlete.data if athlete else None) or {}
    entries = []
    for r in rows:
        ts = _parse_ts(r.get("measured_at"))
        if ts is None:
            continue
        entries.append({
            "id": r["id"],
            "date": str(r["date"])[:10],
            "measured_at": _iso_z(ts),
            "weight_kg": float(r["weight_kg"]),
            "body_fat_pct": float(r["body_fat_pct"]) if r.get("body_fat_pct") is not None else None,
            "source": r.get("source"),
            "time_known": bool(r.get("time_known")),
        })
    goal = a.get("goal_weight_kg")
    return {
        "today": today.isoformat(),
        "entries": entries,
        "goal_weight_kg": float(goal) if goal is not None else None,
        "ftp_watts": a.get("ftp_watts"),
        "measurement_units": a.get("measurement_units"),
    }


# ---- Garmin ----------------------------------------------------------------


def parse_garmin_weigh_ins(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """``get_weigh_ins`` response -> weigh-in rows (no athlete id). Grams -> kg."""
    out: list[dict[str, Any]] = []
    for day in (payload or {}).get("dailyWeightSummaries") or []:
        for m in (day or {}).get("allWeightMetrics") or []:
            if not isinstance(m, dict) or m.get("samplePk") is None:
                continue
            kg = valid_weight((m.get("weight") or 0) / 1000.0)
            ts_ms = m.get("timestampGMT") or m.get("date")
            cal = m.get("calendarDate") or day.get("summaryDate")
            if kg is None or not ts_ms or not cal:
                continue
            try:
                measured = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
                d = date.fromisoformat(str(cal)[:10])
            except (TypeError, ValueError, OverflowError, OSError):
                continue
            fat = m.get("bodyFat")
            try:
                fat = round(float(fat), 1) if fat is not None and 2 <= float(fat) <= 75 else None
            except (TypeError, ValueError):
                fat = None
            out.append({
                "date": d.isoformat(),
                "measured_at": measured.isoformat(),
                "weight_kg": kg,
                "body_fat_pct": fat,
                "source": "garmin",
                "external_id": str(m["samplePk"]),
                "time_known": True,
            })
    return out


def save_garmin_weigh_ins(db: Any, athlete_id: str, rows: list[dict[str, Any]]) -> int:
    """
    Upsert Garmin weigh-ins. deleted_at isn't in the payload, so a re-sync never
    restores one the athlete deleted. A real Garmin weigh-in replaces the time-less
    'daily:' copy the trigger made of the same day's Garmin weight.
    """
    if not rows:
        return 0
    payload = [{**r, "athlete_id": athlete_id} for r in rows]
    db.table(TABLE).upsert(payload, on_conflict="athlete_id,source,external_id").execute()
    days = sorted({r["date"] for r in rows})
    for d in days:
        db.table(TABLE).delete().eq("athlete_id", athlete_id).eq("source", "garmin").eq("date", d).like(
            "external_id", "daily:%"
        ).execute()
        refresh_daily_weight(db, athlete_id, date.fromisoformat(d))
    return len(rows)
