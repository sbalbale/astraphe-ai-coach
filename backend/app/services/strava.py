from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings
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
