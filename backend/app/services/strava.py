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
