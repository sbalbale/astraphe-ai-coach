"""Gzip JSON activity stream blobs in Supabase Storage (bucket ``activity-streams``)."""
from __future__ import annotations

import gzip
import json
import logging
from typing import Any

from app.dependencies import get_admin_db

logger = logging.getLogger(__name__)

BUCKET_ID = "activity-streams"
CONTENT_ENCODING = "gzip"


def storage_object_path(athlete_id: str, workout_id: str) -> str:
    return f"{athlete_id}/{workout_id}.json.gz"


def streams_dict_to_time_series(streams: dict[str, Any]) -> dict[str, list]:
    """Strava API stream objects → flat arrays for storage."""
    out: dict[str, list] = {}
    for key, value in streams.items():
        if not isinstance(value, dict):
            continue
        data = value.get("data")
        if isinstance(data, list):
            out[str(key)] = data
    return out


def time_series_to_streams_dict(time_series: Any) -> dict[str, Any]:
    """Flat time_series JSON → Strava-style stream objects."""
    if not isinstance(time_series, dict) or not time_series:
        return {}
    out: dict[str, Any] = {}
    for key, value in time_series.items():
        k = str(key)
        if isinstance(value, list):
            out[k] = {"data": value}
        elif isinstance(value, dict) and isinstance(value.get("data"), list):
            out[k] = value
    return out


def upload_time_series_gzip(athlete_id: str, workout_id: str, time_series: dict[str, Any]) -> tuple[str, int]:
    """Upload gzip JSON; returns ``(storage_path, byte_size)``. Uses service role."""
    path = storage_object_path(athlete_id, workout_id)
    body = gzip.compress(json.dumps(time_series, separators=(",", ":")).encode("utf-8"))
    client = get_admin_db()
    client.storage.from_(BUCKET_ID).upload(
        path,
        body,
        file_options={"content-type": "application/json", "upsert": "true"},
    )
    return path, len(body)


def download_time_series_gzip(storage_path: str) -> dict[str, Any] | None:
    """Download and parse gzip JSON from Storage. Returns None if missing."""
    if not storage_path:
        return None
    client = get_admin_db()
    try:
        res = client.storage.from_(BUCKET_ID).download(storage_path)
    except Exception as exc:
        logger.warning("stream_storage download failed path=%s: %s", storage_path, exc)
        return None
    if not res:
        return None
    raw = res if isinstance(res, bytes) else bytes(res)
    try:
        text = gzip.decompress(raw).decode("utf-8")
        parsed = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("stream_storage parse failed path=%s: %s", storage_path, exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def resolve_time_series(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Read time_series from a DB row: Storage path first, else legacy JSONB column.
    """
    if not row:
        return None
    storage_path = row.get("storage_path")
    if storage_path:
        ts = download_time_series_gzip(str(storage_path))
        if ts is not None:
            return ts
    legacy = row.get("time_series")
    if isinstance(legacy, dict) and legacy:
        return legacy
    return None


def fetch_stream_row_columns(db: Any, workout_id: str, athlete_id: str) -> dict[str, Any] | None:
    """Load activity_streams metadata + resolved time_series for internal Strava helpers."""
    res = (
        db.table("activity_streams")
        .select(
            "time_series, storage_path, byte_size, content_encoding, "
            "resolution_seconds, created_at"
        )
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    data = getattr(res, "data", None)
    if not data:
        return None
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]
    if not isinstance(data, dict):
        return None
    ts = resolve_time_series(data)
    # Treat missing/corrupt Storage blobs the same as missing streams.
    # If storage_path exists but the blob is missing/corrupt, resolve_time_series returns None.
    if ts is None:
        return None
    return {
        "time_series": ts or {},
        "resolution_seconds": data.get("resolution_seconds") or 1,
        "created_at": data.get("created_at"),
        "storage_path": data.get("storage_path"),
        "byte_size": data.get("byte_size"),
        "content_encoding": data.get("content_encoding"),
    }
