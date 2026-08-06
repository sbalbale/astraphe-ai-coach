from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.models.workout import WorkoutPayload
from app.services.ai_coach import invalidate_context_cache
from app.services.token_crypto import decrypt_oauth_row, encrypt_oauth_fields
from app.services.processing import (
    _sport_for_db,
    find_or_create_canonical_workout,
    normalize_sport,
    process_and_save_workout,
    recalculate_tss_history,
    recompute_workout_tss_for_athlete,
)

STRAVA_OAUTH_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

STREAM_KEYS = (
    "time,heartrate,watts,cadence,velocity_smooth,distance,altitude,"
    "latlng,grade_smooth,temp,moving"
)

# Strava read limits are tight (~100/15min per app); backfill spaces out detail fetches.
STRAVA_BACKFILL_REQUEST_GAP_S = 1.5
STRAVA_RATE_LIMIT_COOLDOWN_S = 900  # 15 min rolling window when no Retry-After

_background_tasks: set[asyncio.Task] = set()


def schedule_hydrate_streams_background(db: Any, athlete_id: str, workout_id: str) -> None:
    """
    Schedule a background hydration task and keep a strong reference.

    Asyncio tasks without a strong ref may be garbage collected/cancelled.
    """
    try:
        task = asyncio.create_task(_hydrate_streams_background(db, athlete_id, workout_id))
    except RuntimeError:
        # No running loop (e.g., called from a sync context); skip silently.
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class StravaRateLimitError(Exception):
    """Raised on HTTP 429 from Strava read APIs so callers can back off (backfill/webhook)."""

    def __init__(self, message: str = "Strava rate limit exceeded", *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after_seconds(response: httpx.Response, default: int = STRAVA_RATE_LIMIT_COOLDOWN_S) -> int:
    raw = response.headers.get("Retry-After")
    if not raw:
        return default
    try:
        v = int(raw)
        if 1 <= v <= 7200:
            return v
    except ValueError:
        pass
    return default


async def _sleep_if_delay(delay: bool) -> None:
    if delay:
        await asyncio.sleep(STRAVA_BACKFILL_REQUEST_GAP_S)


def _parse_strava_start_date(value: Any) -> datetime | None:
    """Parse Strava ``start_date`` (ISO 8601) from list or detail payloads."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_smallint(value: Any, *, max_val: int = 32767) -> int | None:
    """Coerce Strava floats to SMALLINT for PostgREST; None if missing or invalid."""
    if value is None:
        return None
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if n < 0:
        n = 0
    if n > max_val:
        n = max_val
    return n


def _avg_pace_sec_km_from_strava(activity: dict[str, Any]) -> int | None:
    """Convert Strava average_speed (m/s) to pace seconds per km."""
    speed = activity.get("average_speed")
    if not speed or float(speed) <= 0:
        return None
    return int(round(1000.0 / float(speed)))


def _workout_payload_from_strava(
    activity: dict[str, Any],
    activity_id: int,
    sport_type: str,
    start_time: datetime,
    ended_at: datetime,
    elapsed_time: int,
    zone_dist: dict[str, Any],
) -> WorkoutPayload:
    zone_cols = _hr_stream_zone_dist_to_workout_columns(zone_dist)
    return WorkoutPayload(
        source="strava",
        external_id=str(activity_id),
        strava_activity_id=activity_id,
        sport=sport_type,
        started_at=start_time,
        ended_at=ended_at,
        duration_seconds=int(max(0, elapsed_time)),
        distance_m=activity.get("distance"),
        norm_power_w=_optional_smallint(activity.get("weighted_average_watts")),
        avg_hr=_optional_smallint(activity.get("average_heartrate")),
        max_hr=_optional_smallint(activity.get("max_heartrate")),
        avg_pace_sec_km=_avg_pace_sec_km_from_strava(activity),
        title=activity.get("name"),
        hr_zone_0_pct=zone_cols.get("hr_zone_0_pct"),
        hr_zone_1_pct=zone_cols.get("hr_zone_1_pct"),
        hr_zone_2_pct=zone_cols.get("hr_zone_2_pct"),
        hr_zone_3_pct=zone_cols.get("hr_zone_3_pct"),
        hr_zone_4_pct=zone_cols.get("hr_zone_4_pct"),
        hr_zone_5_pct=zone_cols.get("hr_zone_5_pct"),
    )


async def _finalize_strava_sync(athlete_id: str, db) -> None:
    """Recompute missing workout TSS and rebuild PMC after Strava ingest/backfill."""
    await recompute_workout_tss_for_athlete(athlete_id, db)
    recalculate_tss_history(athlete_id, db)
    invalidate_context_cache(athlete_id)


def _hr_stream_zone_dist_to_workout_columns(zone_dist: dict[str, Any]) -> dict[str, Any]:
    """Map compute_zone_distribution Z1..Z5 into workouts.hr_zone_*_pct columns."""
    if not zone_dist:
        return {}
    col_by_key = {
        "Z0": "hr_zone_0_pct",
        "Z1": "hr_zone_1_pct",
        "Z2": "hr_zone_2_pct",
        "Z3": "hr_zone_3_pct",
        "Z4": "hr_zone_4_pct",
        "Z5": "hr_zone_5_pct",
    }
    out: dict[str, Any] = {}
    for zk, col in col_by_key.items():
        if zk not in zone_dist:
            continue
        v = _optional_smallint(zone_dist[zk], max_val=100)
        if v is not None:
            out[col] = v
    return out


def _expires_ts_from_db(value: Any) -> float | None:
    """Normalize oauth_tokens.expires_at to Unix seconds, or None if unusable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _expires_at_iso_from_strava(token_payload: dict[str, Any]) -> str | None:
    """Strava token responses include expires_at as Unix epoch seconds."""
    raw = token_payload.get("expires_at")
    if raw is None:
        return None
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def strava_oauth_expires_at_iso(token_payload: dict[str, Any]) -> str | None:
    """
    Persist oauth_tokens.expires_at the same way as get_valid_token after refresh:
    ISO 8601 UTC string, compatible with _expires_ts_from_db / TIMESTAMPTZ.
    """
    return _expires_at_iso_from_strava(token_payload)


async def exchange_oauth_code(code: str, redirect_uri: str, delay: bool = False) -> dict[str, Any]:
    """POST authorization_code grant; returns full Strava token payload."""
    await _sleep_if_delay(delay)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            STRAVA_OAUTH_TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange Strava code: {response.status_code} {response.text}",
        )
    return response.json()


async def refresh_oauth_token(refresh_token: str, delay: bool = False) -> dict[str, Any]:
    """POST refresh_token grant; callers should persist returned tokens."""
    await _sleep_if_delay(delay)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            STRAVA_OAUTH_TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Strava refresh failed: {response.status_code} {response.text}",
        )
    try:
        return response.json()
    except Exception:
        body = response.text
        snippet = body[:300] if body else "<empty body>"
        raise HTTPException(status_code=502, detail=f"Strava refresh returned non-JSON: {snippet}")


async def get_valid_token(athlete_id: str, db: Any, delay: bool = False) -> str | None:
    """Return a usable access_token for Strava, refreshing and persisting when needed."""
    await _sleep_if_delay(delay)
    res = (
        db.table("oauth_tokens")
        .select("access_token,refresh_token,expires_at")
        .eq("provider", "strava")
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    row = decrypt_oauth_row(res.data)
    if not row:
        return None

    access_token = row.get("access_token")
    refresh_token = row.get("refresh_token")
    expires_at = row.get("expires_at")

    exp_ts = _expires_ts_from_db(expires_at)
    needs_refresh = exp_ts is None or exp_ts < time.time() + 300

    if not needs_refresh:
        return access_token if isinstance(access_token, str) else None

    if not refresh_token:
        print(f"[strava.token] No refresh_token for athlete_id={athlete_id}")
        return None

    try:
        token_data = await refresh_oauth_token(refresh_token, delay=False)
    except HTTPException as e:
        print(f"[strava.token] Refresh failed for athlete_id={athlete_id}: {e.detail}")
        return None
    new_access = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token") or refresh_token
    expires_iso = _expires_at_iso_from_strava(token_data)

    update_payload: dict[str, Any] = {
        "access_token": new_access,
        "refresh_token": new_refresh,
    }
    if expires_iso is not None:
        update_payload["expires_at"] = expires_iso

    if new_access:
        db.table("oauth_tokens").update(encrypt_oauth_fields(update_payload)).eq(
            "athlete_id", athlete_id
        ).eq("provider", "strava").execute()

    return new_access if isinstance(new_access, str) else None


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get_activity(activity_id: int, access_token: str, delay: bool = False) -> dict[str, Any]:
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_auth_headers(access_token))
    if response.status_code == 429:
        raise StravaRateLimitError(retry_after=_retry_after_seconds(response))
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Strava get_activity failed: {response.status_code} {response.text}",
        )
    try:
        return response.json()
    except Exception:
        body = response.text
        snippet = body[:300] if body else "<empty body>"
        raise HTTPException(status_code=502, detail=f"Strava get_activity non-JSON: {snippet}")


async def get_activity_streams(
    activity_id: int, access_token: str, delay: bool = False
) -> dict[str, Any]:
    """
    Strava returns a JSON array of stream objects; normalize to dict keyed by type.

    Strava returns: [{"type": "heartrate", "data": [...], ...}, ...]
    Normalize to: {"heartrate": {"data": [...], ...}, ...}
    """
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/activities/{activity_id}/streams"
    params = {"keys": STREAM_KEYS, "key_by_type": "true"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, headers=_auth_headers(access_token), params=params)
    if response.status_code == 404:
        return {}
    if response.status_code == 429:
        raise StravaRateLimitError(retry_after=_retry_after_seconds(response))
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Strava get_activity_streams failed: {response.status_code} {response.text}",
        )
    try:
        streams = response.json()
    except Exception:
        return {}
    if isinstance(streams, dict):
        return {k: v for k, v in streams.items() if isinstance(v, dict)}
    if isinstance(streams, list):
        return {s["type"]: s for s in streams if isinstance(s, dict) and "type" in s}
    return {}


def compute_500m_splits_from_streams(streams: dict) -> list[dict]:
    """
    Derives 500m intervals from raw stream arrays when device laps are unreliable.
    Returns a list of dicts, each representing one 500m piece.
    streams: the key_by_type=true response from Strava streams API.
    """
    dist = (streams.get("distance") or {}).get("data", [])
    time_s = (streams.get("time") or {}).get("data", [])
    hr = (streams.get("heartrate") or {}).get("data", [])
    watts = (streams.get("watts") or {}).get("data", [])
    cadence = (streams.get("cadence") or {}).get("data", [])
    velocity = (streams.get("velocity_smooth") or {}).get("data", [])

    if not dist or not time_s:
        return []

    total_distance = dist[-1] if dist else 0
    splits = []
    piece_start_idx = 0
    piece_num = 1
    target = 500.0

    while target <= total_distance + 50:  # +50m tolerance for final piece
        # Find index where cumulative distance first crosses target
        end_idx = next(
            (i for i, d in enumerate(dist) if d >= target),
            len(dist) - 1,
        )

        slice_hr = [hr[i] for i in range(piece_start_idx, end_idx + 1) if i < len(hr)]
        slice_watts = [watts[i] for i in range(piece_start_idx, end_idx + 1) if i < len(watts)]
        slice_cad = [cadence[i] for i in range(piece_start_idx, end_idx + 1) if i < len(cadence)]
        slice_vel = [velocity[i] for i in range(piece_start_idx, end_idx + 1) if i < len(velocity)]

        start_time = time_s[piece_start_idx] if piece_start_idx < len(time_s) else 0
        end_time = time_s[end_idx] if end_idx < len(time_s) else 0
        elapsed = end_time - start_time
        piece_dist = dist[end_idx] - dist[piece_start_idx] if piece_start_idx < len(dist) else 500

        # pace in seconds per 500m
        pace_per_500m = int(elapsed / (piece_dist / 500)) if piece_dist > 0 else 0

        splits.append(
            {
                "split_number": piece_num,
                "distance": round(piece_dist, 1),
                "elapsed_time": elapsed,
                "pace_per_500m": pace_per_500m,
                "average_heartrate": round(sum(slice_hr) / len(slice_hr), 1) if slice_hr else None,
                "average_watts": round(sum(slice_watts) / len(slice_watts), 1) if slice_watts else None,
                "average_cadence": round(sum(slice_cad) / len(slice_cad), 1) if slice_cad else None,
                "average_velocity": round(sum(slice_vel) / len(slice_vel), 3) if slice_vel else None,
                "start_index": piece_start_idx,
                "end_index": end_idx,
                "source": "stream_derived",
            }
        )

        piece_start_idx = end_idx + 1
        target += 500.0
        piece_num += 1

        if piece_start_idx >= len(dist):
            break

    return splits


def _time_series_to_streams_dict(time_series: Any) -> dict[str, Any]:
    """Rebuild Strava-style stream objects from stored time_series JSON."""
    from app.services import stream_storage

    return stream_storage.time_series_to_streams_dict(time_series)


def _load_stored_streams_dict(db: Any, workout_id: str) -> dict[str, Any]:
    """Return Strava-style streams from Storage or legacy JSONB, or {} if no row."""
    from app.services import stream_storage

    ts_row = (
        db.table("activity_streams")
        .select("time_series, storage_path, content_encoding")
        .eq("workout_id", workout_id)
        .maybe_single()
        .execute()
    )
    ts_holder = _supabase_single_row(ts_row)
    if not ts_holder:
        return {}
    ts = stream_storage.resolve_time_series(ts_holder)
    return stream_storage.time_series_to_streams_dict(ts)


def _upsert_activity_streams(
    db: Any, workout_id: str, athlete_id: str, streams: dict[str, Any]
) -> None:
    if not streams:
        return
    from app.services import stream_storage

    time_series = stream_storage.streams_dict_to_time_series(streams)
    storage_path, byte_size = stream_storage.upload_time_series_gzip(
        athlete_id, workout_id, time_series
    )
    payload = {
        "workout_id": workout_id,
        "athlete_id": athlete_id,
        "time_series": None,
        "storage_path": storage_path,
        "byte_size": byte_size,
        "content_encoding": stream_storage.CONTENT_ENCODING,
        "resolution_seconds": 1,
    }
    existing = (
        db.table("activity_streams")
        .select("id")
        .eq("workout_id", workout_id)
        .maybe_single()
        .execute()
    )
    if _supabase_single_row(existing):
        db.table("activity_streams").update(payload).eq("workout_id", workout_id).execute()
    else:
        db.table("activity_streams").insert(payload).execute()


def _parse_raw_strava_payload(value: Any) -> dict | None:
    """``raw_strava_payload`` may be JSONB object or a double-encoded JSON string from some writers."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            out = json.loads(s)
        except json.JSONDecodeError:
            return None
        return out if isinstance(out, dict) else None
    return None


def _supabase_resp_data(resp: Any) -> Any:
    """Safe ``.data`` read — some clients or error paths leave ``execute()`` as None."""
    return getattr(resp, "data", None) if resp is not None else None


def _supabase_single_row(resp: Any) -> dict | None:
    """Normalize ``maybe_single().execute()`` to one dict or None."""
    data = _supabase_resp_data(resp)
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    return None


def _pick_best_laps(api_laps: list[Any] | None, embedded_laps: list[Any] | None) -> list[Any]:
    """
    Prefer rich device autolaps from GET /activities/{id} over the /laps endpoint.

    Strava often returns a single synthetic lap (distance 0, full elapsed time) from /laps
    while the activity detail payload includes the real 500m splits.
    """
    api = [lap for lap in (api_laps or []) if isinstance(lap, dict)]
    emb = [lap for lap in (embedded_laps or []) if isinstance(lap, dict)]
    if not api:
        return emb
    if not emb:
        return api
    if len(emb) > len(api):
        return emb
    if len(api) == 1 and len(emb) > 1:
        only = api[0]
        dist = only.get("distance") or 0
        try:
            dist_f = float(dist)
        except (TypeError, ValueError):
            dist_f = 0.0
        if dist_f < 100:
            return emb
    return api


def _stream_data_len(streams: dict[str, Any] | None, key: str) -> int:
    if not isinstance(streams, dict):
        return 0
    holder = streams.get(key)
    if not isinstance(holder, dict):
        return 0
    data = holder.get("data")
    return len(data) if isinstance(data, list) else 0


def _has_quality_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return True


def _lap_quality_score(laps: list[Any] | None) -> int:
    score = 0
    for lap in laps or []:
        if not isinstance(lap, dict):
            continue
        score += 5_000
        for key in (
            "distance",
            "elapsed_time",
            "moving_time",
            "average_heartrate",
            "max_heartrate",
            "average_watts",
            "average_cadence",
            "average_speed",
            "total_elevation_gain",
            "start_index",
            "end_index",
        ):
            if _has_quality_value(lap.get(key)):
                score += 250
    return score


def _strava_detail_quality_score(
    activity: dict[str, Any] | None,
    streams: dict[str, Any] | None,
    laps: list[Any] | None,
) -> int:
    """
    Higher means the activity has richer analyzable detail.

    Stream presence dominates summary fields because streams/laps drive charts,
    rowing intervals, zones, and downstream TSS/strain calculations.
    """
    score = 0
    stream_weights = {
        "heartrate": 100_000,
        "watts": 90_000,
        "latlng": 80_000,
        "cadence": 35_000,
        "distance": 30_000,
        "velocity_smooth": 30_000,
        "altitude": 15_000,
        "time": 10_000,
        "moving": 5_000,
        "grade_smooth": 5_000,
        "temp": 2_500,
    }
    for key, weight in stream_weights.items():
        n = _stream_data_len(streams, key)
        if n > 0:
            score += weight + min(n, 30_000)

    score += _lap_quality_score(laps)

    if isinstance(activity, dict):
        for key in (
            "average_heartrate",
            "max_heartrate",
            "has_heartrate",
            "average_watts",
            "weighted_average_watts",
            "device_watts",
            "distance",
            "total_elevation_gain",
            "average_speed",
            "max_speed",
            "start_latlng",
            "end_latlng",
            "map",
            "splits_metric",
            "splits_standard",
        ):
            if _has_quality_value(activity.get(key)):
                score += 500
    return score


def _persist_activity_laps(
    db: Any, workout_id: str, athlete_id: str, laps: list[Any]
) -> None:
    if not laps:
        return
    db.table("activity_laps").delete().eq("workout_id", workout_id).execute()
    lap_rows = []
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        spd = lap.get("average_speed") or 0
        lap_rows.append(
            {
                "workout_id": workout_id,
                "athlete_id": athlete_id,
                "lap_index": lap.get("lap_index"),
                "start_index": lap.get("start_index"),
                "end_index": lap.get("end_index"),
                "elapsed_time": lap.get("elapsed_time"),
                "moving_time": lap.get("moving_time"),
                "distance": lap.get("distance"),
                "average_heartrate": lap.get("average_heartrate"),
                "max_heartrate": lap.get("max_heartrate"),
                "average_watts": lap.get("average_watts"),
                "average_cadence": lap.get("average_cadence"),
                "average_speed": spd,
                "total_elevation_gain": lap.get("total_elevation_gain"),
                "raw_lap": lap,
            }
        )
    if lap_rows:
        db.table("activity_laps").insert(lap_rows).execute()


def _load_cached_laps_for_workout(db: Any, workout_id: str) -> list[dict] | None:
    """Return laps from ``activity_laps.raw_lap`` ordered by ``lap_index``, or None if unusable."""
    res = (
        db.table("activity_laps")
        .select("lap_index, raw_lap")
        .eq("workout_id", workout_id)
        .execute()
    )
    data = _supabase_resp_data(res)
    rows = data if isinstance(data, list) else []
    if not rows:
        return None
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("lap_index") is None,
            row.get("lap_index") if row.get("lap_index") is not None else 0,
        ),
    )
    laps_out: list[dict] = []
    for r in ordered:
        rl = r.get("raw_lap")
        if not isinstance(rl, dict):
            return None
        laps_out.append(rl)
    return laps_out


def get_rowing_intervals(activity: dict, streams: dict) -> tuple[list[dict], str]:
    """
    Returns all device autolaps exactly as recorded — no filtering, no work/rest
    discrimination. Every lap Garmin recorded is returned including rest and
    active recovery pieces. Stream derivation only fires if there are no laps at all.
    """
    laps = activity.get("laps") or []

    if not laps:
        stream_splits = compute_500m_splits_from_streams(streams)
        return stream_splits, "stream_derived"

    intervals = []
    for i, lap in enumerate(laps):
        spd = lap.get("average_speed") or 0
        pace = int(500 / spd) if spd > 0 else None
        intervals.append({
            "split_number": i + 1,
            "distance": lap.get("distance"),
            "elapsed_time": lap.get("elapsed_time"),
            "moving_time": lap.get("moving_time"),
            "pace_per_500m": pace,
            "average_heartrate": lap.get("average_heartrate"),
            "max_heartrate": lap.get("max_heartrate"),
            "average_watts": lap.get("average_watts"),
            "average_cadence": lap.get("average_cadence"),
            "total_elevation_gain": lap.get("total_elevation_gain"),
            "start_index": lap.get("start_index"),
            "end_index": lap.get("end_index"),
            "source": "laps",
        })

    return intervals, "laps"


async def get_activity_laps(activity_id: int, access_token: str, delay: bool = False) -> list[Any]:
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/activities/{activity_id}/laps"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_auth_headers(access_token))
        if response.status_code == 429:
            raise StravaRateLimitError(retry_after=_retry_after_seconds(response))
        if response.status_code < 200 or response.status_code >= 300:
            return []
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def get_athlete_strava_id(access_token: str, delay: bool = False) -> int | None:
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/athlete"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_auth_headers(access_token))
        if response.status_code < 200 or response.status_code >= 300:
            return None
        payload = response.json()
        aid = payload.get("id") if isinstance(payload, dict) else None
        if aid is None:
            return None
        return int(aid)
    except Exception:
        return None


async def resolve_canonical_workout_for_strava_activity(
    db: Any,
    athlete_id: str,
    activity_type: str | None,
    started_at_utc: datetime,
    elapsed_seconds: int,
    activity_id: int,
    external_id: str | None = None,
) -> tuple[dict, bool]:
    """
    Resolve or create the canonical ``workouts`` row for a Strava activity.
    Dedupe logic lives in ``app.services.processing`` — do not duplicate constants here.
    """
    return await find_or_create_canonical_workout(
        db,
        athlete_id,
        "strava",
        normalize_sport(activity_type or ""),
        started_at_utc,
        int(max(0, elapsed_seconds)),
        external_id or str(activity_id),
        activity_id,
    )


def _strava_id_string(value: Any) -> str | None:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return None


def _strava_activity_is_primary(workout: dict, activity_id: int) -> bool:
    """True when this Strava activity is the canonical Strava id on the workout."""
    primary = _strava_id_string(workout.get("strava_activity_id"))
    return primary is not None and primary == _strava_id_string(activity_id)


def _strava_activity_is_linked(workout: dict, activity_id: int) -> bool:
    """True when the activity is either primary or tracked as a Strava alias."""
    if _strava_activity_is_primary(workout, activity_id):
        return True
    raw = (workout.get("source_ids") or {}).get("strava")
    sid = _strava_id_string(activity_id)
    if sid is None:
        return False
    if isinstance(raw, list):
        linked = {_strava_id_string(x) for x in raw}
        return sid in {x for x in linked if x is not None}
    if isinstance(raw, str):
        return _strava_id_string(raw) == sid
    if raw is not None:
        return _strava_id_string(raw) == sid
    return False


async def ingest_strava_activity(
    owner_strava_id: int,
    activity_id: int,
    db,
    delay: bool = False,
    access_token: str | None = None,
    force_refresh: bool = False,
    athlete_id: str | None = None,
    skip_pmc_recalc: bool = False,
) -> dict | None:
    """
    Full pipeline: fetch -> deduplicate -> store streams/laps -> compute zones -> return workout.
    Called by both the webhook handler and the backfill task.
    If access_token is set, skips get_valid_token (avoids redundant DB reads during backfill).
    ``athlete_id`` may be passed from the webhook (oauth_tokens) when ``athletes.strava_athlete_id`` is unset.
    """
    athlete = None
    if athlete_id:
        athlete_res = (
            db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute()
        )
        athlete = athlete_res.data if athlete_res else None
    if not athlete:
        athlete_res = (
            db.table("athletes")
            .select("*")
            .eq("strava_athlete_id", owner_strava_id)
            .maybe_single()
            .execute()
        )
        athlete = athlete_res.data if athlete_res else None
    if not athlete:
        print(f"[strava.ingest] No athlete for strava_id={owner_strava_id} athlete_id={athlete_id}")
        return None

    athlete_id = athlete["id"]

    if not access_token:
        access_token = await get_valid_token(athlete_id, db)
    if not access_token:
        print(
            f"[strava.ingest] No valid Strava token for athlete_id={athlete_id} "
            f"(re-connect Strava if refresh failed)"
        )
        return None

    activity = await get_activity(activity_id, access_token, delay=delay)
    if not activity or "id" not in activity:
        return None

    sport_type = normalize_sport(activity.get("sport_type") or activity.get("type") or "")
    start_time = datetime.fromisoformat(activity["start_date"].replace("Z", "+00:00"))
    elapsed_time = activity.get("elapsed_time") or 0
    is_rowing = sport_type == "row"

    workout, was_created = await find_or_create_canonical_workout(
        db=db,
        athlete_id=athlete_id,
        source="strava",
        sport_type=sport_type,
        started_at=start_time,
        elapsed_time_seconds=elapsed_time,
        external_id=str(activity_id),
        strava_activity_id=activity_id,
        strava_activity_payload=activity,
    )
    workout_id = workout["id"]

    primary_aid = workout.get("strava_activity_id")
    try:
        primary_int = int(primary_aid) if primary_aid is not None else None
    except (TypeError, ValueError):
        primary_int = None
    is_primary_strava = _strava_activity_is_primary(workout, activity_id)
    is_linked_strava = _strava_activity_is_linked(workout, activity_id)
    is_duplicate_strava = is_linked_strava and not is_primary_strava
    needs_enrichment = force_refresh or not workout.get("strava_streams_fetched")

    if not is_linked_strava:
        print(
            f"[strava.ingest] activity_id={activity_id} not linked to workout {workout_id}; "
            f"primary strava_activity_id={primary_int}"
        )
        return workout

    if is_primary_strava and not needs_enrichment and not was_created:
        if workout.get("tss") is not None:
            print(
                f"[strava.ingest] activity_id={activity_id} already enriched on workout {workout_id}; skip"
            )
            return workout
        print(
            f"[strava.ingest] activity_id={activity_id} enriched but missing TSS on {workout_id}; recomputing"
        )

    # Fetch from Strava when no activity_streams row exists (flag alone is not reliable:
    # reprocess/merge paths may set strava_streams_fetched without persisting streams).
    stored_streams = _load_stored_streams_dict(db, workout_id)
    if is_primary_strava and not force_refresh and stored_streams:
        streams = stored_streams
    else:
        streams = await get_activity_streams(activity_id, access_token, delay=delay)

    cached_laps = _load_cached_laps_for_workout(db, workout_id)
    if is_duplicate_strava or force_refresh:
        laps = await get_activity_laps(activity_id, access_token, delay=delay)
    elif not workout.get("strava_streams_fetched"):
        if cached_laps is not None:
            laps: list[Any] = cached_laps
        else:
            laps = await get_activity_laps(activity_id, access_token, delay=delay)
    else:
        laps = await get_activity_laps(activity_id, access_token, delay=delay)

    hr_stream = (streams.get("heartrate") or {}).get("data", [])
    zones = get_athlete_zones(athlete)
    zone_dist = compute_zone_distribution(hr_stream, zones) if hr_stream else {}

    embedded_list = activity.get("laps") if isinstance(activity.get("laps"), list) else []
    if is_rowing:
        merged_laps = _pick_best_laps(laps, embedded_list)
    else:
        merged_laps = laps if laps else embedded_list

    if is_duplicate_strava:
        existing_activity = _parse_raw_strava_payload(workout.get("raw_strava_payload"))
        existing_embedded = (
            existing_activity.get("laps")
            if isinstance(existing_activity, dict) and isinstance(existing_activity.get("laps"), list)
            else []
        )
        existing_laps = _pick_best_laps(cached_laps, existing_embedded)
        existing_score = _strava_detail_quality_score(
            existing_activity,
            stored_streams,
            existing_laps,
        )
        candidate_score = _strava_detail_quality_score(activity, streams, merged_laps)
        if candidate_score <= existing_score:
            print(
                f"[strava.dedup] Keeping primary activity {primary_int} on workout {workout_id}; "
                f"duplicate {activity_id} score {candidate_score} <= {existing_score}"
            )
            return workout
        print(
            f"[strava.dedup] Promoting duplicate activity {activity_id} over {primary_int} "
            f"on workout {workout_id}; score {candidate_score} > {existing_score}"
        )

    intervals = None
    intervals_source = None
    if is_rowing:
        activity_for_intervals = {**activity, "laps": merged_laps}
        intervals, intervals_source = get_rowing_intervals(activity_for_intervals, streams)

    # workouts table columns must match Supabase schema (see migrations); extras live in raw_strava_payload.
    ended_at = start_time + timedelta(seconds=int(max(0, elapsed_time)))
    update: dict[str, Any] = {
        "strava_activity_id": activity_id,
        # True = streams API was attempted for this activity; empty stream dict is valid (e.g. Zwift, no HR).
        "strava_streams_fetched": True,
        "primary_source": "strava",
        "raw_strava_payload": activity,
        "sport": _sport_for_db(sport_type),
        "title": activity.get("name"),
        "started_at": activity["start_date"],
        "ended_at": ended_at.isoformat(),
        "duration_seconds": int(max(0, elapsed_time)),
        "distance_m": activity.get("distance"),
        "avg_hr": _optional_smallint(activity.get("average_heartrate")),
        "max_hr": _optional_smallint(activity.get("max_heartrate")),
        "avg_power_w": _optional_smallint(activity.get("average_watts")),
        "norm_power_w": _optional_smallint(activity.get("weighted_average_watts")),
        "elevation_gain_m": activity.get("total_elevation_gain"),
        "strain_score": _optional_smallint(activity.get("suffer_score"), max_val=1000),
        "splits_metric": activity.get("splits_metric"),
        "splits_standard": activity.get("splits_standard"),
    }
    update.update(_hr_stream_zone_dist_to_workout_columns(zone_dist))

    if intervals is not None:
        update["intervals"] = intervals
        update["intervals_source"] = intervals_source

    update = {k: v for k, v in update.items() if v is not None}

    db.table("workouts").update(update).eq("id", workout_id).execute()
    workout = {**workout, **update}

    _upsert_activity_streams(db, workout_id, athlete_id, streams)

    _persist_activity_laps(db, workout_id, athlete_id, merged_laps)

    tss_payload = _workout_payload_from_strava(
        activity, activity_id, sport_type, start_time, ended_at, elapsed_time, zone_dist
    )
    await process_and_save_workout(tss_payload, athlete_id, db, skip_tss_recalc=skip_pmc_recalc)

    print(
        f"[strava.ingest] activity_id={activity_id} athlete={athlete_id} "
        f"sport={sport_type} created={was_created}"
    )
    if not streams:
        schedule_hydrate_streams_background(db, athlete_id, workout_id)
    return workout


async def _hydrate_streams_background(db: Any, athlete_id: str, workout_id: str) -> None:
    """Fetch Strava streams after ingest so opening a workout does not block on hydrate."""
    try:
        await hydrate_workout_streams(db, athlete_id, workout_id, delay=True)
    except Exception as exc:
        print(f"[strava.hydrate_bg] workout={workout_id} athlete={athlete_id} error={exc}")


async def backfill_historical_data(
    athlete_id: str,
    owner_strava_id: int,
    access_token: str,
    db,
    days: int = 90,
    *,
    hours: int | None = None,
) -> int:
    """
    Fetches last N days of Strava activities and ingests each one, **newest first**.

    Strava sorts **oldest first** when the ``after`` query param is used; we paginate with
    ``page``/``per_page`` only (default **newest first**) and stop once ``start_date`` is
    before the cutoff so recent activities land in the DB first.

    When ``hours`` is set it takes precedence over ``days`` (startup self-heal window).

    Spaces detail fetches (get activity + streams + laps) using ``STRAVA_BACKFILL_REQUEST_GAP_S``;
    on HTTP 429 sleeps ``Retry-After`` or 15 minutes and retries the same activity.

    Returns the number of activities ingested.
    """
    if hours is not None:
        cutoff_start = datetime.now(timezone.utc) - timedelta(hours=hours)
        window_label = f"{hours}h"
    else:
        cutoff_start = datetime.now(timezone.utc) - timedelta(days=days)
        window_label = f"{days}d"
    page = 1
    per_page = 50
    total_ingested = 0
    max_rate_limit_retries = 6

    print(f"[strava.backfill] Starting {window_label} backfill for athlete={athlete_id}")

    while True:
        await asyncio.sleep(STRAVA_BACKFILL_REQUEST_GAP_S)

        url = f"{STRAVA_API_BASE}/athlete/activities"
        # Do not pass ``after`` — Strava then returns oldest-first; ``page`` alone is newest-first.
        params = {"page": page, "per_page": per_page}
        headers = _auth_headers(access_token)

        activities: list[Any] = []
        list_retries = 0
        while list_retries < max_rate_limit_retries:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429:
                wait = _retry_after_seconds(resp)
                print(f"[strava.backfill] List activities 429 — sleeping {wait}s")
                await asyncio.sleep(wait)
                list_retries += 1
                continue
            if resp.status_code != 200:
                print(f"[strava.backfill] Error fetching page {page}: {resp.status_code}")
                activities = []
                break
            raw = resp.json()
            activities = raw if isinstance(raw, list) else []
            break
        else:
            print(f"[strava.backfill] Gave up fetching activity list page {page} after repeated 429s")
            activities = []

        if not activities:
            break  # no more pages (or fetch failed)

        reached_cutoff = False
        for activity in activities:
            start_dt = _parse_strava_start_date(activity.get("start_date"))
            if start_dt is not None and start_dt < cutoff_start:
                reached_cutoff = True
                break

            aid = activity.get("id")
            if aid is None:
                continue

            skip_primary = (
                db.table("workouts")
                .select("id")
                .eq("athlete_id", athlete_id)
                .eq("strava_activity_id", aid)
                .eq("strava_streams_fetched", True)
                .maybe_single()
                .execute()
            )
            if skip_primary is not None and skip_primary.data is not None:
                continue

            rl_attempts = 0
            while rl_attempts < max_rate_limit_retries:
                try:
                    await ingest_strava_activity(
                        owner_strava_id=owner_strava_id,
                        activity_id=int(aid),
                        db=db,
                        delay=True,
                        access_token=access_token,
                        skip_pmc_recalc=True,
                    )
                    total_ingested += 1
                    break
                except StravaRateLimitError as e:
                    wait = (
                        e.retry_after
                        if e.retry_after and e.retry_after > 0
                        else STRAVA_RATE_LIMIT_COOLDOWN_S
                    )
                    print(
                        f"[strava.backfill] Rate limited on activity {aid} — "
                        f"sleeping {wait}s (attempt {rl_attempts + 1}/{max_rate_limit_retries})"
                    )
                    await asyncio.sleep(wait)
                    rl_attempts += 1
                except Exception as e:
                    print(f"[strava.backfill] Failed activity {aid}: {e}")
                    break
            else:
                print(
                    f"[strava.backfill] Gave up activity {aid} after {max_rate_limit_retries} "
                    "rate-limit waits"
                )

        if reached_cutoff:
            break

        if len(activities) < per_page:
            break  # last page
        page += 1

    await _finalize_strava_sync(athlete_id, db)
    print(
        f"[strava.backfill] Complete. Ingested {total_ingested} activities "
        f"for athlete={athlete_id}"
    )
    return total_ingested


async def backfill_recent(hours: int = 24) -> None:
    """Self-heal missed Strava webhooks after deploy/restart for all connected athletes."""
    from app.dependencies import get_admin_db

    db = get_admin_db()
    try:
        res = (
            db.table("oauth_tokens")
            .select("athlete_id, external_user_id")
            .eq("provider", "strava")
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        print(f"[strava.startup_backfill] failed to list Strava tokens: {e}")
        return

    print(f"[strava.startup_backfill] starting hours={hours} athletes={len(rows)}")
    total_ingested = 0
    for row in rows:
        athlete_id = row.get("athlete_id")
        external_user_id = row.get("external_user_id")
        if not athlete_id or not external_user_id:
            print(
                f"[strava.startup_backfill] skip athlete_id={athlete_id!r} "
                "(missing external_user_id)"
            )
            continue
        try:
            owner_strava_id = int(external_user_id)
        except (TypeError, ValueError):
            print(
                f"[strava.startup_backfill] skip athlete_id={athlete_id} "
                f"invalid external_user_id={external_user_id!r}"
            )
            continue

        access_token = await get_valid_token(athlete_id, db)
        if not access_token:
            print(f"[strava.startup_backfill] skip athlete_id={athlete_id} (no valid token)")
            continue

        try:
            n = await backfill_historical_data(
                athlete_id,
                owner_strava_id,
                access_token,
                db,
                hours=hours,
            )
            total_ingested += n
        except Exception as e:
            print(f"[strava.startup_backfill] failed athlete_id={athlete_id}: {e!r}")

    print(
        f"[strava.startup_backfill] complete hours={hours} "
        f"athletes={len(rows)} ingested={total_ingested}"
    )


def reprocess_rowing_intervals_from_stored_data(db: Any, workout_id: str) -> tuple[str, str]:
    """
    Recompute rowing ``intervals`` / ``intervals_source`` and HR-zone columns from DB only:
    ``workouts.raw_strava_payload``, ``activity_streams.time_series``, and ``activity_laps``
    (falling back to laps embedded in the payload when no lap rows exist). No Strava HTTP.
    """
    try:
        wres = (
            db.table("workouts")
            .select("id, athlete_id, sport, raw_strava_payload")
            .eq("id", workout_id)
            .maybe_single()
            .execute()
        )
        row = _supabase_single_row(wres)
        if not row:
            return "skip", "workout not found"
        if row.get("sport") != "row":
            return "skip", f"sport is {row.get('sport')!r}, not row"
        activity = _parse_raw_strava_payload(row.get("raw_strava_payload"))
        if not activity:
            return "skip", "raw_strava_payload missing or not a JSON object"

        ares = (
            db.table("athletes")
            .select("*")
            .eq("id", row["athlete_id"])
            .maybe_single()
            .execute()
        )
        athlete = _supabase_single_row(ares) or {}

        ts_row = (
            db.table("activity_streams")
            .select("time_series, storage_path, content_encoding")
            .eq("workout_id", workout_id)
            .maybe_single()
            .execute()
        )
        ts_holder = _supabase_single_row(ts_row)
        from app.services import stream_storage

        ts = stream_storage.resolve_time_series(ts_holder) if ts_holder else None
        streams = stream_storage.time_series_to_streams_dict(ts)

        laps_db = _load_cached_laps_for_workout(db, workout_id)
        emb = activity.get("laps")
        embedded = emb if isinstance(emb, list) else []
        laps = _pick_best_laps(laps_db, embedded)

        activity_for = {**activity, "laps": laps}
        intervals, intervals_source = get_rowing_intervals(activity_for, streams)

        hr_stream = (streams.get("heartrate") or {}).get("data", [])
        zones = get_athlete_zones(athlete)
        zone_dist = compute_zone_distribution(hr_stream, zones) if hr_stream else {}

        update: dict[str, Any] = {
            "intervals": intervals,
            "intervals_source": intervals_source,
        }
        update.update(_hr_stream_zone_dist_to_workout_columns(zone_dist))
        update = {k: v for k, v in update.items() if v is not None}

        db.table("workouts").update(update).eq("id", workout_id).execute()
        _persist_activity_laps(db, workout_id, row["athlete_id"], laps)
        return (
            "ok",
            f"source={intervals_source} pieces={len(intervals)} stream_types={len(streams)} laps_used={len(laps)}",
        )
    except Exception as e:
        return "error", str(e)


_WORKOUT_REFETCH_COLUMNS = (
    "id, title, sport, started_at, ended_at, duration_seconds, distance_m, avg_hr, max_hr, "
    "strava_activity_id, strava_streams_fetched, raw_strava_payload, intervals, intervals_source, "
    "splits_metric, hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct, tss"
)


async def refetch_workout_from_strava(
    db: Any,
    athlete_id: str,
    workout_id: str,
    *,
    delay: bool = False,
) -> dict[str, Any]:
    """Re-download activity detail, streams, and laps from Strava for one stored workout."""
    wres = (
        db.table("workouts")
        .select("id, athlete_id, strava_activity_id")
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    workout = _supabase_single_row(wres)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    strava_id_raw = workout.get("strava_activity_id")
    if strava_id_raw is None:
        raise HTTPException(status_code=400, detail="Workout has no Strava activity id")

    ares = (
        db.table("athletes")
        .select("strava_athlete_id")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    athlete_row = _supabase_single_row(ares)
    owner_raw = athlete_row.get("strava_athlete_id") if athlete_row else None
    if owner_raw is None:
        raise HTTPException(status_code=400, detail="Strava not linked for this athlete")

    try:
        owner = int(owner_raw)
        activity_id = int(strava_id_raw)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid Strava ids on workout/athlete") from e

    access_token = await get_valid_token(athlete_id, db, delay=delay)
    if not access_token:
        raise HTTPException(status_code=503, detail="Strava not connected")

    try:
        result = await ingest_strava_activity(
            owner_strava_id=owner,
            activity_id=activity_id,
            db=db,
            delay=delay,
            access_token=access_token,
            force_refresh=True,
        )
    except StravaRateLimitError as e:
        wait = e.retry_after if e.retry_after and e.retry_after > 0 else STRAVA_RATE_LIMIT_COOLDOWN_S
        raise HTTPException(
            status_code=429,
            detail=f"Strava rate limit — try again in about {int(wait)}s",
        ) from e

    if not result:
        raise HTTPException(status_code=502, detail="Strava did not return activity data")

    streams = _load_stored_streams_dict(db, workout_id)
    latlng = (streams.get("latlng") or {}).get("data", [])
    latlng_len = len(latlng) if isinstance(latlng, list) else 0

    fresh = (
        db.table("workouts")
        .select(_WORKOUT_REFETCH_COLUMNS)
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    workout_row = _supabase_single_row(fresh) or result

    return {
        "status": "ok",
        "workout_id": workout_id,
        "strava_activity_id": activity_id,
        "stream_types": sorted(streams.keys()) if streams else [],
        "has_latlng_stream": latlng_len >= 2,
        "workout": workout_row,
    }


async def hydrate_workout_streams(
    db: Any,
    athlete_id: str,
    workout_id: str,
    *,
    delay: bool = False,
) -> dict[str, Any]:
    """
    Fetch Strava streams when ``activity_streams`` is missing for a linked workout.
    Idempotent when a stream row already exists.
    """
    wres = (
        db.table("workouts")
        .select("id, athlete_id, strava_activity_id")
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    workout = _supabase_single_row(wres)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    strava_id = workout.get("strava_activity_id")
    if strava_id is None:
        raise HTTPException(status_code=400, detail="Workout has no Strava activity id")

    if _load_stored_streams_dict(db, workout_id):
        return {"status": "already_stored"}

    access_token = await get_valid_token(athlete_id, db, delay=delay)
    if not access_token:
        raise HTTPException(status_code=503, detail="Strava not connected")

    streams = await get_activity_streams(int(strava_id), access_token, delay=delay)

    db.table("workouts").update({"strava_streams_fetched": True}).eq("id", workout_id).execute()
    _upsert_activity_streams(db, workout_id, athlete_id, streams)

    hr_stream = (streams.get("heartrate") or {}).get("data", [])
    if hr_stream:
        ares = (
            db.table("athletes")
            .select("*")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        athlete = _supabase_single_row(ares) or {}
        zones = get_athlete_zones(athlete)
        zone_dist = compute_zone_distribution(hr_stream, zones)
        zone_cols = _hr_stream_zone_dist_to_workout_columns(zone_dist)
        if zone_cols:
            db.table("workouts").update(zone_cols).eq("id", workout_id).execute()

    return {
        "status": "hydrated" if streams else "empty",
        "stream_types": sorted(streams.keys()) if streams else [],
    }


async def reset_rowing_intervals(db) -> int:
    """
    Clear rowing interval columns so ingest/reprocess can rebuild them.

    Targets ``sport=row`` with a Strava activity id and ``intervals_source`` in
    ``laps`` or ``stream_derived`` (stream_derived was previously excluded, so
    those rows never matched the old reset).
    """

    def _sync() -> int:
        sel = (
            db.table("workouts")
            .select("id")
            .eq("sport", "row")
            .not_.is_("strava_activity_id", "null")
            .in_("intervals_source", ["laps", "stream_derived"])
            .execute()
        )
        data = _supabase_resp_data(sel)
        rows = data if isinstance(data, list) else []
        n = len(rows)
        if n == 0:
            return 0
        db.table("workouts").update(
            {
                "intervals": None,
                "intervals_source": None,
                "strava_streams_fetched": False,
            }
        ).eq("sport", "row").not_.is_("strava_activity_id", "null").in_(
            "intervals_source",
            ["laps", "stream_derived"],
        ).execute()
        return n

    return await asyncio.to_thread(_sync)
