"""
Profile and settings changes, shared by the settings screen (PATCH /v1/athlete/profile)
and the coach's update_profile tool, so both validate and save a change the same way.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from app.models.athlete import AthleteProfileUpdate
from app.services.hr_zones import get_athlete_zones, optional_canonical_hr_zone_method
from app.services.time_utils import coerce_timezone_offset_min, local_datetime_from_timezone_offset

logger = logging.getLogger(__name__)


class ProfileValueError(ValueError):
    """A value the profile can't take (shown to the athlete / the coach as is)."""


def normalize_profile_update(update_data: dict[str, Any]) -> dict[str, Any]:
    """
    The validated fields of an AthleteProfileUpdate, ready to write to `athletes`:
    sources for athlete-entered heart rates, dates as ISO strings, and units / time format /
    gender / zone method in their stored form. Raises ProfileValueError for a bad value.
    """
    data = dict(update_data)

    if "max_hr" in data:
        # Entered by the athlete: never replaced by the app's estimate (cleared -> estimated again).
        data["max_hr_source"] = "manual" if data.get("max_hr") else None

    # Resting HR follows the wearable ('measured') until the athlete enters one; asking
    # for 'measured' again drops any value sent with it (the caller then recomputes it,
    # see hr_anchors.refresh_measured_resting_hr).
    if data.get("resting_hr_source") == "measured":
        data.pop("resting_hr", None)
    elif "resting_hr" in data:
        data.pop("resting_hr_source", None)
        if data.get("resting_hr"):
            data["resting_hr_source"] = "manual"
        else:
            data.pop("resting_hr")  # clearing it: keep the measured value
    if "threshold_hr" in data and data.get("threshold_hr") is not None:
        try:
            if int(data["threshold_hr"]) > 0:
                data["threshold_hr_source"] = "manual"
        except (TypeError, ValueError):
            pass

    # Supabase client JSON-encodes request bodies; normalize non-JSON types.
    for k, v in list(data.items()):
        if isinstance(v, (date, datetime)):
            data[k] = v.isoformat()

    units = data.get("measurement_units")
    if units is not None:
        units_norm = str(units).strip().lower()
        if units_norm not in ("metric", "imperial"):
            raise ProfileValueError("measurement_units must be 'metric' or 'imperial'")
        data["measurement_units"] = units_norm

    tf = data.get("time_format")
    if tf is not None:
        tf_norm = str(tf).strip().lower()
        # Accept a few common variants from clients (e.g. "12-hour", "12 hour").
        if tf_norm in ("12h", "12-hour", "12 hour", "12hour", "12"):
            data["time_format"] = "12h"
        elif tf_norm in ("24h", "24-hour", "24 hour", "24hour", "24"):
            data["time_format"] = "24h"
        else:
            raise ProfileValueError("time_format must be '12h' or '24h'")

    # Used by Banister TRIMP constants; keep supported values narrow.
    gender = data.get("gender")
    if gender is not None:
        gender_norm = str(gender).strip().lower()
        if gender_norm not in ("male", "female"):
            raise ProfileValueError("gender must be 'male' or 'female'")
        data["gender"] = gender_norm

    # Must match the CHECK constraint on athletes (alias max_hr_percent -> max_hr).
    if data.get("hr_zone_method") is not None:
        try:
            data["hr_zone_method"] = optional_canonical_hr_zone_method(data["hr_zone_method"])
        except ValueError:
            raise ProfileValueError("hr_zone_method must be lthr, hrr, or max_hr")

    return data


def fetch_latest_weight_kg_sync(db: Any, athlete_id: str) -> float | None:
    res = (
        db.table("biometrics")
        .select("weight_kg")
        .eq("athlete_id", athlete_id)
        .not_.is_("weight_kg", "null")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    raw = res.data[0].get("weight_kg")
    if raw is None:
        return None
    return float(raw)


def record_manual_weight_sync(db: Any, athlete_id: str, weight_kg: float) -> bool:
    """
    Record a weight the athlete typed in as today's biometrics reading (source "manual").

    The app shows the newest biometrics weight, so without this a stale scale sync would
    keep overriding what the athlete just entered. Nothing is written when the value
    matches the newest reading, so re-saving the profile doesn't create readings.
    Returns True when a reading was written.
    """
    latest = fetch_latest_weight_kg_sync(db, athlete_id)
    if latest is not None and abs(latest - weight_kg) < 0.05:
        return False

    offset = None
    try:
        res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).maybe_single().execute()
        row = getattr(res, "data", None) if res else None
        if isinstance(row, dict):
            offset = row.get("timezone_offset_min")
    except Exception:
        pass
    today = local_datetime_from_timezone_offset(coerce_timezone_offset_min(offset)).date().isoformat()

    metric_sources: dict = {}
    try:
        res = (
            db.table("biometrics")
            .select("metric_sources")
            .eq("athlete_id", athlete_id)
            .eq("date", today)
            .limit(1)
            .execute()
        )
        if res.data and isinstance(res.data[0].get("metric_sources"), dict):
            metric_sources = dict(res.data[0]["metric_sources"])
    except Exception:
        pass
    metric_sources["weight_kg"] = "manual"

    db.table("biometrics").upsert(
        {
            "athlete_id": athlete_id,
            "date": today,
            "weight_kg": round(float(weight_kg), 2),
            "metric_sources": metric_sources,
        },
        on_conflict="athlete_id,date",
    ).execute()
    return True


# ---------------------------------------------------------------------------
# Coach tool: update_profile
# ---------------------------------------------------------------------------

# What the coach may change. Name, birthday, gender, privacy and marketing stay in the app.
COACH_PROFILE_FIELDS = (
    "ftp_watts",
    "threshold_pace",
    "threshold_hr",
    "max_hr",
    "resting_hr",
    "hr_zone_method",
    "weight_kg",
    "height_cm",
    "measurement_units",
    "time_format",
)
NOTIFICATION_TYPES = ("debrief", "reply", "ready", "weekly", "sync")
_HR_FIELDS = ("threshold_hr", "max_hr", "resting_hr", "hr_zone_method")


def _merge_notification_changes(current: Any, changes: Any, quiet: Any) -> dict[str, Any]:
    """Current notification settings with the requested changes on top (only what was asked)."""
    from app.services.notification_prefs import effective

    merged = effective(current)
    if isinstance(changes, dict):
        for tid, val in changes.items():
            if tid not in merged["types"] or not isinstance(val, dict):
                continue
            for k in ("on", "push", "opt"):
                if val.get(k) is not None:
                    merged["types"][tid][k] = val[k]
    if isinstance(quiet, dict):
        for k in ("on", "from", "to"):
            if quiet.get(k) is not None:
                merged["quiet"][k] = quiet[k]
    return merged


def _invalidate_profile_caches_sync(athlete_id: str) -> None:
    """The settings screen's cache clearing, from a worker thread (the coach loop has no event
    loop of its own, and the shared Redis client belongs to the app's loop). Never raises: a
    cache that can't be cleared just expires on its TTL (5 minutes)."""
    try:
        from app.services.ai_coach import invalidate_context_cache

        invalidate_context_cache(athlete_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.config import settings

        if not settings.REDIS_URL:
            return
        from redis import Redis

        r = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            r.delete(f"profile:{athlete_id}", f"zones:{athlete_id}", f"state:{athlete_id}")
            r.incr(f"zones_version:{athlete_id}")
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("profile cache invalidation failed for athlete_id=%s: %s", athlete_id, e)


def _rescore_from(athlete_id: str, since: date) -> None:
    from app.dependencies import get_admin_db
    from app.services.anchor_history import rescore_and_rebuild

    try:
        rescore_and_rebuild(get_admin_db(), athlete_id, since)
    except Exception as e:  # noqa: BLE001
        logger.error("rescore after coach profile change failed for athlete_id=%s: %s", athlete_id, e)


def update_profile_from_coach(db: Any, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    The coach's update_profile tool: change training anchors, body measurements, units or
    notification settings the same way the settings screen does (bounds, anchor history,
    re-scoring from today, a manual weight reading, cache clearing). Returns what changed,
    old -> new, and the recalculated zones when a heart-rate anchor changed.
    """
    fields = {k: args[k] for k in COACH_PROFILE_FIELDS if args.get(k) is not None}
    notif_changes, quiet = args.get("notifications"), args.get("quiet_hours")
    if not fields and not notif_changes and not quiet:
        return {"error": "nothing_to_change: pass at least one value to update"}

    try:
        current_res = db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute()
        current = (getattr(current_res, "data", None) if current_res else None) or {}
    except Exception as e:
        return {"error": f"profile_query_failed: {e}"}
    if not current:
        return {"error": "athlete_not_found"}

    if notif_changes or quiet:
        fields["notification_settings"] = _merge_notification_changes(
            current.get("notification_settings"), notif_changes, quiet
        )

    try:
        validated = AthleteProfileUpdate(**fields).model_dump(exclude_unset=True)
        update = normalize_profile_update(validated)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg')}" for err in e.errors()
        )
        return {"error": f"invalid_value: {problems}"}
    except ProfileValueError as e:
        return {"error": f"invalid_value: {e}"}

    try:
        db.table("athletes").update(update).eq("id", athlete_id).execute()
        fresh_res = db.table("athletes").select("*").eq("id", athlete_id).single().execute()
        fresh = getattr(fresh_res, "data", None) or {}
    except Exception as e:
        return {"error": f"profile_update_failed: {e}"}

    weight = update.get("weight_kg")
    if isinstance(weight, (int, float)) and weight > 0:
        try:
            record_manual_weight_sync(db, athlete_id, float(weight))
        except Exception as e:  # noqa: BLE001
            logger.warning("manual weight reading failed for athlete_id=%s: %s", athlete_id, e)

    from app.services.anchor_history import ANCHOR_FIELDS, record_change

    rescoring = False
    if any(k in update for k in ANCHOR_FIELDS) and any(current.get(k) != fresh.get(k) for k in ANCHOR_FIELDS):
        try:
            from app.dependencies import get_admin_db
            from app.services.time_utils import athlete_local_date

            admin = get_admin_db()
            today = athlete_local_date(admin, athlete_id)
            record_change(admin, athlete_id, fresh, today)
            # Re-scoring can take a while; the reply shouldn't wait for it.
            threading.Thread(target=_rescore_from, args=(athlete_id, today), daemon=True).start()
            rescoring = True
        except Exception as e:  # noqa: BLE001
            logger.error("anchor history update failed for athlete_id=%s: %s", athlete_id, e)

    _invalidate_profile_caches_sync(athlete_id)

    changed = {
        k: {"from": current.get(k), "to": fresh.get(k)}
        for k in update
        if k not in ("max_hr_source", "threshold_hr_source", "resting_hr_source") and current.get(k) != fresh.get(k)
    }
    out: dict[str, Any] = {"status": "updated" if changed else "unchanged", "changed": changed}
    if rescoring:
        out["note"] = "Workouts from today on are being re-scored with the new anchors; earlier ones keep their values."
    if any(k in update for k in _HR_FIELDS):
        out["hr_zones"] = [
            {"zone": z.zone, "name": z.name, "min_bpm": z.min_bpm, "max_bpm": z.max_bpm}
            for z in get_athlete_zones(fresh)
        ]
    return out
