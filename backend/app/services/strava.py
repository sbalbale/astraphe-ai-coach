from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services.processing import find_or_create_canonical_workout, normalize_sport

STRAVA_OAUTH_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

STREAM_KEYS = (
    "time,heartrate,watts,cadence,velocity_smooth,distance,altitude,"
    "latlng,grade_smooth,temp,moving"
)


async def _sleep_if_delay(delay: bool) -> None:
    if delay:
        await asyncio.sleep(0.5)


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
    row = res.data
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
        return None

    token_data = await refresh_oauth_token(refresh_token, delay=False)
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
        db.table("oauth_tokens").update(update_payload).eq("athlete_id", athlete_id).eq(
            "provider", "strava"
        ).execute()

    return new_access if isinstance(new_access, str) else None


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def get_activity(activity_id: int, access_token: str, delay: bool = False) -> dict[str, Any]:
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_auth_headers(access_token))
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
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Strava get_activity_streams failed: {response.status_code} {response.text}",
        )
    try:
        streams = response.json()
    except Exception:
        return {}
    if not isinstance(streams, list):
        return {}
    return {s["type"]: s for s in streams if isinstance(s, dict) and "type" in s}


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


def get_rowing_intervals(activity: dict, streams: dict) -> tuple[list[dict], str]:
    """
    Returns (intervals, source) for a rowing activity.
    Prefers device auto-laps (Garmin/Apple Watch 500m auto-lap),
    falls back to stream-derived 500m splits.

    Returns:
        intervals: list of 500m piece dicts
        source: 'laps' | 'stream_derived'
    """
    laps = activity.get("laps") or []

    # Filter to laps that look like auto-500m pieces
    valid_500m = [l for l in laps if 450 <= (l.get("distance") or 0) <= 550]

    # Also filter out rest laps (avg pace worse than 3:30/500m = 210s)
    # velocity in m/s → 500m pace in seconds = 500 / avg_speed
    def lap_pace(lap):
        spd = lap.get("average_speed") or 0
        return (500 / spd) if spd > 0 else 999

    work_laps = [l for l in valid_500m if lap_pace(l) < 210]

    if len(work_laps) >= len(laps) * 0.6 and len(work_laps) > 0:
        # Device auto-lapped reliably — convert laps to canonical interval shape
        intervals = []
        for i, lap in enumerate(work_laps):
            spd = lap.get("average_speed") or 0
            pace = int(500 / spd) if spd > 0 else None
            intervals.append(
                {
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
                }
            )
        return intervals, "laps"

    # Fallback: derive from streams
    stream_splits = compute_500m_splits_from_streams(streams)
    return stream_splits, "stream_derived"


async def get_activity_laps(activity_id: int, access_token: str, delay: bool = False) -> list[Any]:
    await _sleep_if_delay(delay)
    url = f"{STRAVA_API_BASE}/activities/{activity_id}/laps"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_auth_headers(access_token))
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


async def ingest_strava_activity(
    owner_strava_id: int,
    activity_id: int,
    db,
    delay: bool = False,
    access_token: str | None = None,
) -> dict | None:
    """
    Full pipeline: fetch -> deduplicate -> store streams/laps -> compute zones -> return workout.
    Called by both the webhook handler and the backfill task.
    If access_token is set, skips get_valid_token (avoids redundant DB reads during backfill).
    """
    athlete_res = (
        db.table("athletes")
        .select("*")
        .eq("strava_athlete_id", owner_strava_id)
        .maybe_single()
        .execute()
    )
    if not athlete_res.data:
        print(f"[strava.ingest] No athlete found for strava_id={owner_strava_id}")
        return None

    athlete = athlete_res.data
    athlete_id = athlete["id"]

    if not access_token:
        access_token = await get_valid_token(athlete_id, db)
    if not access_token:
        print(f"[strava.ingest] No valid token for athlete_id={athlete_id}")
        return None

    if delay:
        await asyncio.sleep(0.5)

    activity = await get_activity(activity_id, access_token)
    if not activity or "id" not in activity:
        return None

    sport_type = normalize_sport(activity.get("sport_type") or activity.get("type") or "")
    start_time = datetime.fromisoformat(activity["start_date"].replace("Z", "+00:00"))
    elapsed_time = activity.get("elapsed_time") or 0
    is_rowing = sport_type == "rowing"

    workout, was_created = await find_or_create_canonical_workout(
        db=db,
        athlete_id=athlete_id,
        source="strava",
        sport_type=sport_type,
        started_at=start_time,
        elapsed_time_seconds=elapsed_time,
        strava_activity_id=activity_id,
    )
    workout_id = workout["id"]

    streams: dict[str, Any] = {}
    if not workout.get("strava_streams_fetched"):
        if delay:
            await asyncio.sleep(0.5)
        streams = await get_activity_streams(activity_id, access_token)

    if delay:
        await asyncio.sleep(0.5)
    laps = await get_activity_laps(activity_id, access_token)

    hr_stream = (streams.get("heartrate") or {}).get("data", [])
    zones = get_athlete_zones(athlete)
    zone_dist = compute_zone_distribution(hr_stream, zones) if hr_stream else {}

    intervals = None
    intervals_source = None
    if is_rowing:
        intervals, intervals_source = get_rowing_intervals(activity, streams)

    update: dict[str, Any] = {
        "strava_activity_id": activity_id,
        "strava_streams_fetched": bool(streams),
        "primary_source": "strava",
        "raw_strava_payload": activity,
        "sport": sport_type,
        "started_at": activity["start_date"],
        "elapsed_time": elapsed_time,
        "moving_time": activity.get("moving_time"),
        "distance_m": activity.get("distance"),
        "avg_hr": activity.get("average_heartrate"),
        "max_hr": activity.get("max_heartrate"),
        "avg_watts": activity.get("average_watts"),
        "max_watts": activity.get("max_watts"),
        "weighted_avg_watts": activity.get("weighted_average_watts"),
        "kilojoules": activity.get("kilojoules"),
        "avg_cadence": activity.get("average_cadence"),
        "suffer_score": activity.get("suffer_score"),
        "perceived_exertion": activity.get("perceived_exertion"),
        "total_elevation_gain": activity.get("total_elevation_gain"),
        "splits_metric": activity.get("splits_metric"),
        "splits_standard": activity.get("splits_standard"),
        "hr_zone_distribution": zone_dist if zone_dist else None,
    }

    if intervals is not None:
        update["intervals"] = intervals
        update["intervals_source"] = intervals_source

    update = {k: v for k, v in update.items() if v is not None}

    db.table("workouts").update(update).eq("id", workout_id).execute()

    if streams:
        db.table("activity_streams").upsert(
            {
                "workout_id": workout_id,
                "athlete_id": athlete_id,
                "time_series": {
                    k: v.get("data", [])
                    for k, v in streams.items()
                    if isinstance(v, dict)
                },
                "resolution_seconds": 1,
            },
            on_conflict="workout_id",
        ).execute()

    if laps:
        db.table("activity_laps").delete().eq("workout_id", workout_id).execute()
        lap_rows = []
        for lap in laps:
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
        db.table("activity_laps").insert(lap_rows).execute()

    print(
        f"[strava.ingest] activity_id={activity_id} athlete={athlete_id} "
        f"sport={sport_type} created={was_created}"
    )
    return workout


async def backfill_historical_data(
    athlete_id: str,
    owner_strava_id: int,
    access_token: str,
    db,
    days: int = 90,
) -> None:
    """
    Fetches last N days of Strava activities and ingests each one.
    Rate-limit safe: 0.5s delay between requests.
    Only fetches activity summaries first; streams are fetched per-activity during ingest.
    """
    after_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    page = 1
    per_page = 50
    total_ingested = 0

    print(f"[strava.backfill] Starting {days}d backfill for athlete={athlete_id}")

    while True:
        await asyncio.sleep(0.5)  # rate limit buffer

        url = f"{STRAVA_API_BASE}/athlete/activities"
        params = {"after": after_ts, "page": page, "per_page": per_page}
        headers = _auth_headers(access_token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params, headers=headers)

        if resp.status_code != 200:
            print(f"[strava.backfill] Error fetching page {page}: {resp.status_code}")
            break

        activities = resp.json()
        if not activities:
            break  # no more pages

        for activity in activities:
            try:
                await ingest_strava_activity(
                    owner_strava_id=owner_strava_id,
                    activity_id=activity["id"],
                    db=db,
                    delay=True,
                    access_token=access_token,
                )
                total_ingested += 1
            except Exception as e:
                print(f"[strava.backfill] Failed activity {activity.get('id')}: {e}")
                continue

        if len(activities) < per_page:
            break  # last page
        page += 1

    print(
        f"[strava.backfill] Complete. Ingested {total_ingested} activities "
        f"for athlete={athlete_id}"
    )
