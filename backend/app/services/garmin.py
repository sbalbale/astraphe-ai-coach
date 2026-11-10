"""Garmin Connect integration via the community ``garminconnect`` library.

Garmin has no self-serve OAuth for individual/small-business developers — the
official Connect Developer Program is partner-approval-only and, as of 2026,
is reportedly not accepting new signups. This service authenticates with the
athlete's own Garmin username/password via ``garminconnect`` (which wraps
Garmin's mobile-app SSO login, including MFA), then persists only the
resulting session tokens — never the password — for reuse on every
subsequent sync.

Known risk: Garmin's SSO endpoint aggressively rate-limits repeated logins
(accounts can be 429-blocked for 48+ hours). Always prefer restoring a
persisted session (``get_client_for_athlete``) over a fresh username/password
login, and keep polling windows small (see ``sync_activities_for_athlete``).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

import fitdecode
from garminconnect import Garmin
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from app.services.background import spawn as spawn_background
from app.config import settings
from app.dependencies import get_admin_db
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.algorithms import compute_hrss_from_zones, compute_strain_score
from app.services.ai_coach import invalidate_context_cache
from app.services import stream_storage
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services.processing import (
    process_and_save_biometrics,
    process_and_save_workout,
    recalculate_tss_history,
    recompute_workout_tss_for_athlete,
)

logger = logging.getLogger(__name__)

PROVIDER = "garmin"

# Small per-request pause so a full backfill doesn't hammer Garmin's API and
# risk a 429 lockout (see module docstring).
GARMIN_REQUEST_GAP_S = 1.0

# garminconnect never retries 429s itself (by design — see its
# _is_retryable(): "Never retries 401, 429 or 4xx — those are deterministic
# and caller-actionable"), and it raises GarminConnectTooManyRequestsError
# for a 429 on *any* API call, not just login. Once we see one, back off
# instead of continuing to poll at the same 1s pace — the cooldown below is
# how long the poll loop skips this athlete afterward (see
# _poll_one_athlete). Kept well under Garmin's documented worst-case SSO
# login lockout (48h+) since this only guards general API calls, which are a
# lighter-weight limit than the login endpoint.
GARMIN_RATE_LIMIT_COOLDOWN_SEC = 30 * 60


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class GarminMfaRequired(Exception):
    """Raised by ``login()`` when the account requires an MFA code."""

    def __init__(self, state_token: str):
        super().__init__("Garmin login requires an MFA code")
        self.state_token = state_token


class GarminAuthError(Exception):
    """Bad credentials, locked account, or a rejected/expired session."""


class GarminRateLimitedError(Exception):
    """Garmin's SSO endpoint returned 429. Caller should back off, not retry."""


# --------------------------------------------------------------------------
# MFA session holding
# --------------------------------------------------------------------------
#
# astraphe-api runs two replicas, and the two requests of one MFA login
# (`POST /garmin/connect`, then `POST /garmin/connect/mfa` with the code) can
# land on different ones. garminconnect (0.3.x) returns the pending login as
# JSON-serializable ``client_state`` from ``login()`` (SSO session cookies +
# login params) and ``resume_login(client_state, code)`` rebuilds it on any
# ``Garmin`` instance. So the pending login is kept:
#   - in this process (the client object; same-replica fast path, local dev), and
#   - in Redis as ``garmin_mfa:{state_token}``, Fernet-encrypted like the stored
#     OAuth tokens (it holds session cookies), for the 5-minute TTL, taken with
#     GETDEL so it's used once whichever replica gets the code.
# (An older library kept the state only on the live client, whose curl_cffi
# session can't be pickled, so the earlier pickle-to-Redis attempt failed.)
_MFA_TTL_SECONDS = 5 * 60
_pending_mfa: dict[str, tuple[Garmin, float]] = {}


def _prune_expired_mfa() -> None:
    now = time.monotonic()
    for token in [t for t, (_, expires) in _pending_mfa.items() if expires < now]:
        _pending_mfa.pop(token, None)


def _mfa_redis_key(state_token: str) -> str:
    return f"garmin_mfa:{state_token}"


def _store_pending_mfa(state_token: str, client: Garmin, client_state: Any = None) -> None:
    """
    Keep the pending login in this process and, so the other replica can finish it,
    its ``client_state`` (session cookies + login params; the library rebuilds a
    login from it) in Redis, encrypted like the stored OAuth tokens, for the TTL.
    """
    _prune_expired_mfa()
    _pending_mfa[state_token] = (client, time.monotonic() + _MFA_TTL_SECONDS)
    if not client_state:
        return
    from app.core.redis import get_sync_redis
    from app.services.token_crypto import encrypt_token

    r = get_sync_redis()
    if r is None:
        return
    try:
        r.setex(_mfa_redis_key(state_token), _MFA_TTL_SECONDS, encrypt_token(json.dumps(client_state)))
    except Exception as exc:
        logger.warning("garmin MFA state not shared via Redis (same-replica resume only): %s", exc)


def _pop_pending_mfa(state_token: str) -> tuple[Garmin, dict[str, Any]] | None:
    """
    The pending login as (client, client_state): this process's client (state {}:
    it resumes from its own session), else a fresh client plus the state from Redis.
    """
    _prune_expired_mfa()
    pending = _pending_mfa.pop(state_token, None)
    from app.core.redis import get_sync_redis

    r = get_sync_redis()
    raw = None
    if r is not None:
        try:
            raw = r.getdel(_mfa_redis_key(state_token))  # one use, whichever replica
        except Exception as exc:
            logger.warning("garmin MFA state lookup failed: %s", exc)
    if pending is not None:
        return pending[0], {}
    if not raw:
        return None
    from app.services.token_crypto import decrypt_token

    try:
        state = json.loads(decrypt_token(raw))
    except Exception as exc:
        logger.warning("garmin MFA state unreadable: %s", exc)
        return None
    return Garmin(return_on_mfa=True), state


# --------------------------------------------------------------------------
# Auth / session lifecycle
# --------------------------------------------------------------------------

def login(username: str, password: str) -> Garmin:
    """
    Log in with a Garmin username/password.

    Returns a ready-to-use ``Garmin`` client on success. Raises
    ``GarminMfaRequired`` (carrying a ``state_token`` for ``resume_mfa``),
    ``GarminAuthError``, or ``GarminRateLimitedError``.
    """
    client = Garmin(username, password, return_on_mfa=True)
    try:
        mfa_status, client_state = client.login()
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except GarminConnectAuthenticationError as exc:
        raise GarminAuthError(str(exc)) from exc

    if mfa_status == "needs_mfa":
        state_token = secrets.token_urlsafe(24)
        _store_pending_mfa(state_token, client, client_state)
        raise GarminMfaRequired(state_token)

    return client


def resume_mfa(state_token: str, mfa_code: str) -> Garmin:
    """Complete a login that previously raised ``GarminMfaRequired``."""
    pending = _pop_pending_mfa(state_token)
    if pending is None:
        raise GarminAuthError(
            "MFA session expired or unknown; reconnect Garmin from scratch"
        )
    client, client_state = pending
    try:
        # The client that started the login resumes from its own pending session
        # (state {}); one rebuilt on the other replica carries the stored state.
        client.resume_login(client_state, mfa_code)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except GarminConnectAuthenticationError as exc:
        raise GarminAuthError(str(exc)) from exc
    return client


def serialize_session(client: Garmin) -> str:
    """Serialize the client's session tokens (never the password) for storage."""
    from app.services.token_crypto import encrypt_token

    return encrypt_token(client.client.dumps())


def restore_session(blob: str) -> Garmin:
    """Rebuild a ``Garmin`` client from a previously serialized session."""
    from app.services.token_crypto import decrypt_token

    plaintext = decrypt_token(blob)
    client = Garmin(return_on_mfa=True)
    client.client.loads(plaintext)
    # Populates display_name (needed by several endpoints) and validates the
    # restored tokens; also transparently refreshes them if close to expiry
    # (handled inside the library's request layer).
    client._load_profile_and_settings()
    return client


def get_client_for_athlete(athlete_id: str, db: Any) -> Garmin | None:
    """Load and restore the persisted Garmin session for an athlete, or None."""
    res = (
        db.table("oauth_tokens")
        .select("access_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", PROVIDER)
        .maybe_single()
        .execute()
    )
    row = getattr(res, "data", None) if res else None
    blob = row.get("access_token") if row else None
    if not blob:
        return None
    try:
        return restore_session(blob)
    except Exception as exc:
        logger.warning("garmin.restore_session failed athlete_id=%s: %s", athlete_id, exc)
        return None


# astraphe-api runs multiple replicas (2, as of the 2026-07-03 k3s migration —
# see app/services/token_refresh.py). The hourly poll loop below runs
# independently in each replica with no shared scheduler, so two replicas can
# wake up and try to sync the same athlete's Garmin data at once, doubling
# API traffic against Garmin's rate limiter. Reuse the same atomic-claim
# pattern WHOOP's proactive refresh uses (oauth_tokens.refresh_lock_expires_at)
# so only one replica syncs a given athlete per tick.
_SYNC_LOCK_DURATION_SEC = 20 * 60  # generous vs. one athlete's activity+biometrics sync


def _claim_sync_lock(db: Any, athlete_id: str) -> bool:
    now = datetime.now(timezone.utc)
    lock_until = (now + timedelta(seconds=_SYNC_LOCK_DURATION_SEC)).isoformat()
    claim = (
        db.table("oauth_tokens")
        .update({"refresh_lock_expires_at": lock_until})
        .eq("athlete_id", athlete_id)
        .eq("provider", PROVIDER)
        .lt("refresh_lock_expires_at", now.isoformat())
        .execute()
    )
    return bool(claim.data)


def _release_sync_lock(db: Any, athlete_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.table("oauth_tokens").update({"refresh_lock_expires_at": now}).eq(
        "athlete_id", athlete_id
    ).eq("provider", PROVIDER).execute()


def _cooldown_sync_lock(db: Any, athlete_id: str, seconds: int) -> None:
    """
    Hold the sync lock past its normal duration after a 429, so the poll
    loop's next tick (an hour later by default) skips this athlete instead
    of immediately retrying and risking another rate-limit hit.
    """
    until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    db.table("oauth_tokens").update({"refresh_lock_expires_at": until}).eq(
        "athlete_id", athlete_id
    ).eq("provider", PROVIDER).execute()


def persist_session(
    db: Any, athlete_id: str, client: Garmin, external_user_id: str | None = None
) -> None:
    """Re-save the (possibly rotated) session tokens after use."""
    payload: dict[str, Any] = {
        "athlete_id": athlete_id,
        "provider": PROVIDER,
        "access_token": serialize_session(client),
        "refresh_token": None,
    }
    if external_user_id:
        payload["external_user_id"] = external_user_id
    db.table("oauth_tokens").upsert(payload, on_conflict="athlete_id,provider").execute()


# --------------------------------------------------------------------------
# Sport mapping
# --------------------------------------------------------------------------
#
# Garmin Connect's `activityType.typeKey` taxonomy (lowercase snake_case),
# distinct from the official Health API's uppercase enum that the dormant
# `map_garmin_sport()` in `routers/sync.py` was written for.
_SPORT_MAP: dict[str, str] = {
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "track_running": "run",
    "street_running": "run",
    "ultra_run": "run",
    "virtual_run": "run",
    "cycling": "bike",
    "road_biking": "bike",
    "mountain_biking": "bike",
    "gravel_cycling": "bike",
    "cyclocross": "bike",
    "track_cycling": "bike",
    "indoor_cycling": "bike",
    "virtual_ride": "bike",
    "e_bike_ride": "bike",
    "e_bike_mountain": "bike",
    "handcycling": "bike",
    "swimming": "swim",
    "lap_swimming": "swim",
    "open_water_swimming": "swim",
    "strength_training": "strength",
    "indoor_cardio": "strength",
    "elliptical": "strength",
    "stair_climbing": "strength",
    "hiit": "strength",
    "rowing": "row",
    "indoor_rowing": "row",
    "yoga": "mobility",
    "pilates": "mobility",
    "breathwork": "mobility",
    "meditation": "mobility",
    "stretching": "mobility",
    "mobility": "mobility",
    "walking": "other",
    "casual_walking": "other",
    "speed_walking": "other",
    "hiking": "other",
    "multi_sport": "other",
    "fitness_equipment": "other",
}


_TRANSITION_TYPES = {"transition", "transition_v2"}
_logged_unknown_types: set[str] = set()


def map_garmin_connect_sport(type_key: str | None) -> str:
    """Map a Garmin Connect ``activityType.typeKey`` to an ASTRAPHE canonical sport."""
    key = (type_key or "").strip().lower()
    if key in _SPORT_MAP:
        return _SPORT_MAP[key]
    # Garmin versions some keys (on-water rowing came through as something other than
    # "rowing", so 27 sessions were stored as "other" and never matched Strava's "row").
    if "rowing" in key:
        return "row"
    if key and key not in _logged_unknown_types:
        _logged_unknown_types.add(key)
        logger.info("garmin: unmapped activity typeKey=%r stored as other", key)
    return "other"


def is_multisport_parent(activity: dict[str, Any]) -> bool:
    """A Garmin multisport activity (triathlon, erg + run, ...): a parent of separate legs."""
    key = ((activity.get("activityType") or {}).get("typeKey") or "").lower()
    return bool(activity.get("parent") or activity.get("isParent")) or key == "multi_sport"


def leg_as_list_activity(detail: dict[str, Any]) -> dict[str, Any]:
    """A multisport leg from ``get_activity`` (summaryDTO shape) in the shape of a
    ``get_activities_by_date`` entry, so build_workout_payload can map it."""
    s = detail.get("summaryDTO") or {}
    return {
        "activityId": detail.get("activityId"),
        "activityName": detail.get("activityName"),
        "activityType": {"typeKey": (detail.get("activityTypeDTO") or {}).get("typeKey")},
        "startTimeGMT": s.get("startTimeGMT"),
        "duration": s.get("duration"),
        "distance": s.get("distance"),
        "elevationGain": s.get("elevationGain"),
        "calories": s.get("calories"),
        "avgPower": s.get("averagePower"),
        "normPower": s.get("normalizedPower"),
        "averageHR": s.get("averageHR"),
        "maxHR": s.get("maxHR"),
        "averageSpeed": s.get("averageSpeed"),
    }


def multisport_leg_ids(client: Garmin, parent_id: Any) -> list[int]:
    """The parent's legs, in order, without transitions."""
    detail = client.get_activity(parent_id) or {}
    meta = detail.get("metadataDTO") or {}
    ids = meta.get("childIds") or []
    types = meta.get("childActivityTypes") or [None] * len(ids)
    return [int(i) for i, t in zip(ids, types) if (t or "").lower() not in _TRANSITION_TYPES]


def _stored_garmin_ids(db: Any, athlete_id: str, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    res = (
        db.table("workouts")
        .select("garmin_activity_id")
        .eq("athlete_id", athlete_id)
        .in_("garmin_activity_id", ids)
        .execute()
    )
    return {int(r["garmin_activity_id"]) for r in (res.data or []) if r.get("garmin_activity_id")}


def _delete_garmin_parent(db: Any, athlete_id: str, parent_id: Any) -> int:
    """Drop a stored multisport parent: its legs are stored instead (streams and laps cascade;
    a plan linked to it is unlinked by the FK)."""
    res = (
        db.table("workouts")
        .delete()
        .eq("athlete_id", athlete_id)
        .eq("garmin_activity_id", int(parent_id))
        .execute()
    )
    return len(res.data or [])


# --------------------------------------------------------------------------
# Workout payload mapping
# --------------------------------------------------------------------------

def _round_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _parse_garmin_datetime(value: str | None) -> datetime | None:
    """Garmin's ``startTimeGMT`` is ``'YYYY-MM-DD HH:MM:SS'`` (no offset, already UTC)."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


MAX_PACE_SEC_KM = 3600


def _avg_pace_sec_km_from_speed(average_speed_mps: Any) -> int | None:
    try:
        speed = float(average_speed_mps)
    except (TypeError, ValueError):
        return None
    if speed <= 0:
        return None
    pace = int(round(1000.0 / speed))
    # A near-zero average speed (a stopwatch / pickleball / stationary session with a few metres
    # of GPS drift) gives a "pace" like 250,000 s/km, which isn't a pace and overflowed the
    # smallint column, failing the whole sync. Slower than an hour per km: no pace.
    return pace if pace <= MAX_PACE_SEC_KM else None


def build_workout_payload(activity: dict[str, Any]) -> WorkoutPayload | None:
    """Map one entry from ``get_activities_by_date`` into a ``WorkoutPayload``."""
    activity_id = activity.get("activityId")
    if activity_id is None:
        return None

    start_time = _parse_garmin_datetime(activity.get("startTimeGMT"))
    if start_time is None:
        return None

    duration_seconds = _round_int(activity.get("duration"))
    ended_at = (
        start_time + timedelta(seconds=duration_seconds) if duration_seconds else None
    )

    activity_type = activity.get("activityType") or {}
    sport = map_garmin_connect_sport(activity_type.get("typeKey"))

    elevation = activity.get("elevationGain")
    if elevation is None:
        elevation = activity.get("elevationCorrectedElevationGain")

    calories = activity.get("calories")
    if calories is None:
        calories = activity.get("activeCalories")

    try:
        garmin_id = int(activity_id)
    except (TypeError, ValueError):
        garmin_id = None

    return WorkoutPayload(
        source=PROVIDER,
        external_id=str(activity_id),
        garmin_activity_id=garmin_id,
        sport=sport,
        started_at=start_time,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        distance_m=activity.get("distance"),
        elevation_gain_m=float(elevation) if elevation is not None else None,
        calories=float(calories) if calories is not None else None,
        avg_power_w=_round_int(activity.get("avgPower")),
        norm_power_w=_round_int(activity.get("normPower")),
        avg_hr=_round_int(activity.get("averageHR")),
        max_hr=_round_int(activity.get("maxHR")),
        avg_pace_sec_km=_avg_pace_sec_km_from_speed(activity.get("averageSpeed")),
        title=activity.get("activityName") or None,
    )


# --------------------------------------------------------------------------
# FIT download + parsing → Strava-shaped streams/laps
# --------------------------------------------------------------------------

_SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)


def _extract_fit_bytes(original_zip_bytes: bytes) -> bytes | None:
    """The ``ORIGINAL`` download format is a zip; pull out the first .fit entry."""
    try:
        with zipfile.ZipFile(io.BytesIO(original_zip_bytes)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                return None
            return zf.read(fit_names[0])
    except zipfile.BadZipFile:
        # Some activities (e.g. manually-entered, no device file) return a
        # bare .fit or nothing usable; treat unrecognized bytes as "no FIT
        # data". FIT's file header puts the ".FIT" data-type signature at
        # byte offset 8 (header_size(1) + protocol_version(1) +
        # profile_version(2) + data_size(4) precede it), not offset 0.
        return (
            original_zip_bytes
            if len(original_zip_bytes) >= 12 and original_zip_bytes[8:12] == b".FIT"
            else None
        )


def _persist_activity_laps(db: Any, workout_id: str, athlete_id: str, laps: list[dict]) -> None:
    if not laps:
        return
    db.table("activity_laps").delete().eq("workout_id", workout_id).execute()
    lap_rows = [
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
            "average_speed": lap.get("average_speed") or 0,
            "total_elevation_gain": lap.get("total_elevation_gain"),
            "raw_lap": lap,
        }
        for lap in laps
    ]
    db.table("activity_laps").insert(lap_rows).execute()


def download_and_parse_fit(
    client: Garmin, activity_id: str
) -> tuple[dict[str, list], list[dict[str, Any]]]:
    """
    Download an activity's original FIT file and shape it into ASTRAPHE's
    stream/lap format — the same keys Strava's streams API returns
    (``time``, ``heartrate``, ``watts``, ``cadence``, ``velocity_smooth``,
    ``altitude``, ``distance``, ``latlng``) — so no downstream chart/zone
    code needs to know the data came from Garmin.

    Returns ``({}, [])`` if the activity has no downloadable FIT data (e.g.
    a manually-entered activity). Raises ``GarminRateLimitedError`` on a 429
    rather than swallowing it — callers must stop, not keep requesting the
    next activity at the same pace (see GARMIN_RATE_LIMIT_COOLDOWN_SEC).
    """
    try:
        raw = client.download_activity(
            str(activity_id), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
        )
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except Exception as exc:
        logger.info("garmin.download_activity unavailable activity_id=%s: %s", activity_id, exc)
        return {}, []

    fit_bytes = _extract_fit_bytes(raw)
    if not fit_bytes:
        return {}, []

    time_s: list[int] = []
    heartrate: list[Any] = []
    watts: list[Any] = []
    cadence: list[Any] = []
    velocity: list[Any] = []
    altitude: list[Any] = []
    distance: list[Any] = []
    latlng: list[Any] = []

    laps: list[dict[str, Any]] = []
    first_ts: datetime | None = None
    last_lap_end_index = -1

    try:
        with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fit:
            for frame in fit:
                if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue

                if frame.name == "record":
                    ts = frame.get_value("timestamp", fallback=None)
                    if ts is None:
                        continue
                    if first_ts is None:
                        first_ts = ts
                    time_s.append(int((ts - first_ts).total_seconds()))
                    heartrate.append(frame.get_value("heart_rate", fallback=None))
                    watts.append(frame.get_value("power", fallback=None))
                    cadence.append(frame.get_value("cadence", fallback=None))
                    speed = frame.get_value("enhanced_speed", fallback=None)
                    if speed is None:
                        speed = frame.get_value("speed", fallback=None)
                    velocity.append(speed)
                    alt = frame.get_value("enhanced_altitude", fallback=None)
                    if alt is None:
                        alt = frame.get_value("altitude", fallback=None)
                    altitude.append(alt)
                    distance.append(frame.get_value("distance", fallback=None))
                    lat = frame.get_value("position_lat", fallback=None)
                    lng = frame.get_value("position_long", fallback=None)
                    if lat is not None and lng is not None:
                        # Unlike the other streams, latlng is NOT padded with
                        # None to stay 1:1 with `time` — it holds only valid
                        # points, matching Strava's stream contract (which
                        # every consumer, e.g. GpsTrace.svelte, assumes: it
                        # destructures every entry as [lat, lng] with no null
                        # check). A None here before GPS lock would crash
                        # that destructuring on the frontend.
                        latlng.append(
                            [lat * _SEMICIRCLE_TO_DEG, lng * _SEMICIRCLE_TO_DEG]
                        )

                elif frame.name == "lap":
                    start_index = last_lap_end_index + 1
                    end_index = len(time_s) - 1
                    last_lap_end_index = end_index
                    laps.append(
                        {
                            "lap_index": len(laps),
                            "start_index": start_index if end_index >= start_index else None,
                            "end_index": end_index if end_index >= start_index else None,
                            "elapsed_time": _round_int(
                                frame.get_value("total_elapsed_time", fallback=None)
                            ),
                            "moving_time": _round_int(
                                frame.get_value("total_timer_time", fallback=None)
                            ),
                            "distance": frame.get_value("total_distance", fallback=None),
                            "average_heartrate": frame.get_value(
                                "avg_heart_rate", fallback=None
                            ),
                            "max_heartrate": frame.get_value(
                                "max_heart_rate", fallback=None
                            ),
                            "average_watts": frame.get_value("avg_power", fallback=None),
                            "average_cadence": frame.get_value(
                                "avg_cadence", fallback=None
                            ),
                            "average_speed": frame.get_value("avg_speed", fallback=None),
                            "total_elevation_gain": frame.get_value(
                                "total_ascent", fallback=None
                            ),
                        }
                    )
    except Exception as exc:
        logger.warning("garmin FIT parse failed activity_id=%s: %s", activity_id, exc)
        return {}, []

    def _series(values: list[Any]) -> list[Any] | None:
        return values if any(v is not None for v in values) else None

    streams: dict[str, list] = {}
    if time_s:
        streams["time"] = time_s
    for key, values in (
        ("heartrate", heartrate),
        ("watts", watts),
        ("cadence", cadence),
        ("velocity_smooth", velocity),
        ("altitude", altitude),
        ("distance", distance),
        ("latlng", latlng),
    ):
        series = _series(values)
        if series is not None:
            streams[key] = series

    return streams, laps


def _streams_already_stored(db: Any, workout_id: str) -> bool:
    """True when this workout already has a stored stream blob."""
    try:
        res = (
            db.table("activity_streams")
            .select("workout_id")
            .eq("workout_id", workout_id)
            .not_.is_("storage_path", "null")
            .limit(1)
            .execute()
        )
    except Exception:
        return False
    data = getattr(res, "data", None)
    return isinstance(data, list) and len(data) > 0


def _upsert_activity_streams(
    db: Any, workout_id: str, athlete_id: str, time_series: dict[str, Any]
) -> bool:
    if not time_series:
        return False
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
    if getattr(existing, "data", None):
        db.table("activity_streams").update(payload).eq("workout_id", workout_id).execute()
    else:
        db.table("activity_streams").insert(payload).execute()
    return True


def _hr_samples_from_streams(streams: dict[str, Any]) -> list[int]:
    hr_stream = streams.get("heartrate")
    if not isinstance(hr_stream, list):
        return []
    samples: list[int] = []
    for value in hr_stream:
        if value is None or isinstance(value, bool):
            continue
        try:
            bpm = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        if 20 <= bpm <= 260:
            samples.append(bpm)
    return samples


def _update_workout_hr_zones_from_streams(
    db: Any,
    workout_id: str,
    athlete_id: str,
    streams: dict[str, Any],
    duration_seconds: int | None = None,
    sport: str | None = None,
) -> None:
    hr_samples = _hr_samples_from_streams(streams)
    if not hr_samples:
        return
    athlete_res = (
        db.table("athletes")
        .select("lthr,threshold_hr,max_hr,resting_hr,threshold_hr_source,hr_zone_method,gender")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    athlete = getattr(athlete_res, "data", None) or {}
    zone_dist = compute_zone_distribution(hr_samples, get_athlete_zones(athlete))
    update: dict[str, Any] = {}
    zone_minutes: dict[int, float] = {}
    # Prefer the workout's true elapsed duration over the recorded-stream sample
    # count. Garmin sometimes stops recording mid-activity (device hiccup, the
    # athlete pausing without cleanly resuming) so the FIT stream can cover far
    # less time than the activity actually took; using len(hr_samples) here
    # would silently treat the un-recorded gap as "no effort happened",
    # understating strain/TSS for exactly the kind of workout most likely to
    # have one (a longer, harder effort that outlasted a device issue).
    duration_min = (
        duration_seconds / 60.0 if duration_seconds else len(hr_samples) / 60.0
    )
    for idx in range(1, 6):
        pct = zone_dist.get(f"Z{idx}")
        if pct is None:
            continue
        pct_i = int(round(float(pct)))
        update[f"hr_zone_{idx}_pct"] = max(0, min(100, pct_i))
        zone_minutes[idx] = (float(pct) / 100.0) * duration_min
    if zone_minutes:
        update["strain_score"] = compute_strain_score(zone_minutes, sport=sport or "other")
        # build_workout_payload() never populates hr_zone_*_pct — Garmin's
        # activity-list summary doesn't include a zone breakdown, only the
        # downloaded FIT stream does — so process_and_save_workout()'s
        # has_hr_zones branch can't fire on first sync and tss is left at its
        # 0.0 default for any Garmin activity without power or pace data (e.g.
        # indoor rowing, strength). Fill it in now that zones are known, but
        # only if a stronger method (power/pace) hasn't already set a real
        # value — this only ever runs right after process_and_save_workout()
        # for the same workout, so a fresh read is needed to see what it wrote.
        existing = (
            db.table("workouts").select("tss").eq("id", workout_id).maybe_single().execute()
        )
        existing_tss = (getattr(existing, "data", None) or {}).get("tss")
        if not existing_tss:
            update["tss"] = compute_hrss_from_zones(
                zone_minutes=zone_minutes,
                max_hr=int(athlete.get("max_hr") or 0),
                resting_hr=int(athlete.get("resting_hr") or 0),
                threshold_hr=int(athlete.get("threshold_hr") or 0),
                sport=sport or "other",
                gender=str(athlete.get("gender") or "male"),
                threshold_hr_source=athlete.get("threshold_hr_source"),
                hr_zone_method=athlete.get("hr_zone_method"),
            )
    if update:
        db.table("workouts").update(update).eq("id", workout_id).execute()


# --------------------------------------------------------------------------
# Sync orchestration
# --------------------------------------------------------------------------

async def _save_one_activity(
    client: Garmin, activity: dict[str, Any], athlete_id: str, db: Any
) -> tuple[bool, bool]:
    payload = build_workout_payload(activity)
    if payload is None:
        return False, False

    workout_id = await process_and_save_workout(
        payload, athlete_id, db, skip_tss_recalc=True, skip_daily_strain_refresh=True
    )

    activity_id = activity.get("activityId")
    streams: dict[str, Any] = {}
    laps: list[dict[str, Any]] = []
    # The hourly poll sees the same recent activities every time; re-downloading each
    # FIT file burned Garmin quota (and risks its multi-day lockouts) for no new data.
    if activity_id is not None and await asyncio.to_thread(_streams_already_stored, db, workout_id):
        return True, False
    if activity_id is not None:
        # `garminconnect` is a synchronous (requests/curl_cffi) client — run its
        # blocking network calls off the event loop.
        streams, laps = await asyncio.to_thread(
            download_and_parse_fit, client, str(activity_id)
        )

    # Blocking supabase-py writes: off the event loop (this poll runs inside the API
    # process, so on-loop DB work stalled every HTTP request on the replica).
    streams_saved = await asyncio.to_thread(_upsert_activity_streams, db, workout_id, athlete_id, streams)
    if streams_saved:
        await asyncio.to_thread(
            lambda: _update_workout_hr_zones_from_streams(
                db, workout_id, athlete_id, streams,
                duration_seconds=payload.duration_seconds,
                sport=payload.workout_type,
            )
        )
    if laps:
        await asyncio.to_thread(_persist_activity_laps, db, workout_id, athlete_id, laps)

    # Post-workout debrief (coach thread + push, and a text while texts are still on). It
    # fires here rather than inside process_and_save_workout (which Garmin calls with
    # skip_tss_recalc=True, before HR zones/TSS/laps exist) so the coach sees the fully
    # enriched workout. It checks recency and claims each workout once, so history
    # backfills and re-syncs never notify.
    from app.services.coach_notifications import post_workout_debrief

    spawn_background(post_workout_debrief(db, athlete_id, str(workout_id)))

    return True, streams_saved


async def split_multisport(client: Garmin, db: Any, athlete_id: str, parent_id: Any) -> list[dict[str, Any]]:
    """The legs of a multisport parent still to be stored (list-entry shape); also deletes a
    stored copy of the parent. Legs already stored aren't fetched again (the poll sees the
    same parent every 15 minutes)."""
    if parent_id is None:
        return []
    leg_ids = await asyncio.to_thread(multisport_leg_ids, client, parent_id)
    await asyncio.to_thread(_delete_garmin_parent, db, athlete_id, parent_id)
    have = await asyncio.to_thread(_stored_garmin_ids, db, athlete_id, leg_ids)
    legs: list[dict[str, Any]] = []
    for leg_id in leg_ids:
        if leg_id in have:
            continue
        detail = await asyncio.to_thread(client.get_activity, leg_id)
        legs.append(leg_as_list_activity(detail or {}))
        await asyncio.sleep(GARMIN_REQUEST_GAP_S)
    return legs


async def sync_activities_for_athlete(
    athlete_id: str, db: Any, start_date: date, end_date: date
) -> dict[str, int]:
    """Fetch and store Garmin activities in ``[start_date, end_date]`` (inclusive)."""
    client = await asyncio.to_thread(get_client_for_athlete, athlete_id, db)
    if client is None:
        return {"workouts": 0, "streams": 0, "connected": 0}

    try:
        activities = await asyncio.to_thread(
            client.get_activities_by_date, start_date.isoformat(), end_date.isoformat()
        )
    except GarminConnectTooManyRequestsError as exc:
        await asyncio.to_thread(persist_session, db, athlete_id, client)
        raise GarminRateLimitedError(str(exc)) from exc

    workout_count = 0
    stream_count = 0
    rate_limited = False
    expanded: list[dict[str, Any]] = []
    for activity in activities:
        if not is_multisport_parent(activity):
            expanded.append(activity)
            continue
        # Garmin is the source of truth for multisport: store its legs (each scored as its own
        # sport), not the parent, which double-counted the whole session next to the legs.
        try:
            legs = await split_multisport(client, db, athlete_id, activity.get("activityId"))
        except GarminConnectTooManyRequestsError as exc:
            await asyncio.to_thread(persist_session, db, athlete_id, client)
            raise GarminRateLimitedError(str(exc)) from exc
        expanded.extend(legs)

    for activity in expanded:
        try:
            saved_workout, saved_streams = await _save_one_activity(
                client, activity, athlete_id, db
            )
        except GarminRateLimitedError:
            # Stop immediately rather than keep requesting the next activity
            # at the same pace — that's what actually risks compounding a
            # light API throttle into a much longer lockout. Whatever we
            # already saved this pass stays; the poll loop's cooldown
            # (GARMIN_RATE_LIMIT_COOLDOWN_SEC) picks this athlete back up
            # later instead of retrying on the very next tick.
            logger.warning(
                "garmin activity sync rate-limited athlete=%s after %s/%s activities; stopping this pass",
                athlete_id, workout_count, len(expanded),
            )
            rate_limited = True
            break
        except Exception as exc:
            # One activity that can't be stored mustn't abort the rest of the sync (and, in a
            # backfill, the biometrics after it): log it and carry on.
            logger.warning(
                "garmin activity %s skipped athlete=%s: %r",
                activity.get("activityId"), athlete_id, exc,
            )
            continue
        if saved_workout:
            workout_count += 1
        if saved_streams:
            stream_count += 1
        # Pace requests so a large backfill doesn't trip Garmin's rate limiter
        # (see module docstring — repeated hits risk a 48h+ account lockout).
        await asyncio.sleep(GARMIN_REQUEST_GAP_S)

    await asyncio.to_thread(persist_session, db, athlete_id, client)

    # Recompute for whatever we did save, whether or not we finished the pass.
    if workout_count:
        await recompute_workout_tss_for_athlete(athlete_id, db)
        await asyncio.to_thread(recalculate_tss_history, athlete_id, db)
        invalidate_context_cache(athlete_id)

    if rate_limited:
        # Re-raise after persisting/recomputing whatever progress we made, so
        # the caller (backfill_historical_data / _poll_one_athlete) backs off
        # instead of moving straight on to biometrics against the same
        # rate-limited account.
        raise GarminRateLimitedError(
            f"rate-limited after {workout_count}/{len(activities)} activities"
        )

    logger.info(
        "Garmin activity sync complete athlete=%s workouts=%s streams=%s window=%s..%s",
        athlete_id,
        workout_count,
        stream_count,
        start_date,
        end_date,
    )
    return {"workouts": workout_count, "streams": stream_count, "connected": 1}


# --------------------------------------------------------------------------
# Biometrics (sleep / HRV / resting HR / SpO2)
# --------------------------------------------------------------------------

def _daily_biometrics_from_garmin(
    day: date, sleep: dict[str, Any] | None, hrv: dict[str, Any] | None, heart_rates: dict[str, Any] | None
) -> DailyBiometrics | None:
    sleep_dto = (sleep or {}).get("dailySleepDTO") or {}
    hrv_summary = (hrv or {}).get("hrvSummary") or {}

    sleep_duration_min = _round_int((sleep_dto.get("sleepTimeSeconds") or 0) / 60.0) or None
    deep_s = sleep_dto.get("deepSleepSeconds")
    light_s = sleep_dto.get("lightSleepSeconds")
    rem_s = sleep_dto.get("remSleepSeconds")
    awake_s = sleep_dto.get("awakeSleepSeconds")
    total_s = sleep_dto.get("sleepTimeSeconds")

    def _pct(part: Any, whole: Any) -> float | None:
        try:
            p, w = float(part), float(whole)
        except (TypeError, ValueError):
            return None
        return round((p / w) * 100.0, 1) if w > 0 else None

    sleep_start = _parse_epoch_ms(sleep_dto.get("sleepStartTimestampGMT"))
    sleep_end = _parse_epoch_ms(sleep_dto.get("sleepEndTimestampGMT"))

    resting_hr = _round_int((heart_rates or {}).get("restingHeartRate"))
    # 0% is not a physiological SpO2 reading, so a 0 (or negative / non-numeric / absent)
    # SpO2 is treated as missing rather than stored -- otherwise it would be saved as
    # real data and could win source-priority over a valid value from another source.
    # The live get_sleep_data() payload names it averageSpO2Value; avgSpO2 is the key the
    # garminconnect typed model uses, so keep it as a fallback.
    spo2_source = sleep_dto.get("averageSpO2Value")
    if spo2_source is None:
        spo2_source = sleep_dto.get("avgSpO2")
    try:
        spo2_raw = float(spo2_source)
    except (TypeError, ValueError):
        spo2_raw = None
    spo2_pct = spo2_raw if spo2_raw and spo2_raw > 0 else None

    # avgSkinTempDeviationC lives at the top level of the sleep response (a
    # sibling of dailySleepDTO/hrvStatus/restingHeartRate), not inside
    # dailySleepDTO like avgSpO2 is. It's a *deviation* from the athlete's own
    # baseline (Garmin Connect's "Avg Skin Temp Change"), not an absolute
    # temperature like WHOOP's skin_temp_celsius -- stored separately as
    # skin_temp_deviation_c, never merged into skin_temp. Garmin needs ~2-3
    # weeks to establish that baseline (skinTempCalibrationDays); before then,
    # or on devices without the sensor, skinTempDataExists is False and the
    # deviation value (often a stale 0.0) should not be trusted.
    skin_temp_deviation_c = (
        (sleep or {}).get("avgSkinTempDeviationC") if (sleep or {}).get("skinTempDataExists") else None
    )

    has_any = any(
        v is not None
        for v in (sleep_duration_min, hrv_summary.get("lastNightAvg"), resting_hr, spo2_pct, skin_temp_deviation_c)
    )
    if not has_any:
        return None

    return DailyBiometrics(
        date=day,
        source=PROVIDER,
        external_id=f"{PROVIDER}:{day.isoformat()}",
        hrv_rmssd=hrv_summary.get("lastNightAvg"),
        resting_hr=resting_hr,
        spo2_pct=spo2_pct,
        skin_temp_deviation_c=skin_temp_deviation_c,
        sleep_duration_min=sleep_duration_min,
        sleep_deep_pct=_pct(deep_s, total_s),
        sleep_rem_pct=_pct(rem_s, total_s),
        sleep_light_pct=_pct(light_s, total_s),
        sleep_awake_pct=_pct(awake_s, total_s),
        sleep_bedtime=sleep_start,
        sleep_wakeup=sleep_end,
    )


def _parse_epoch_ms(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


# Garmin sleepLevels `activityLevel` codes (confirmed against dailySleepDTO totals).
_SLEEP_STAGE_BY_LEVEL = {0: "deep", 1: "light", 2: "rem", 3: "awake"}


def _parse_garmin_naive_utc(value: Any) -> datetime | None:
    """sleepLevels timestamps look like '2026-11-01T03:09:18.0' -- UTC with no offset."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_sleep_stage_segments(sleep: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Turn get_sleep_data()['sleepLevels'] into [{stage, start_at, end_at}] (UTC, sorted).
    Missing/empty input gives []; segments with an unknown stage code or unparseable
    / non-positive timestamps are skipped (logged), never raised.
    """
    levels = (sleep or {}).get("sleepLevels")
    if not isinstance(levels, list):
        return []
    segments: list[dict[str, Any]] = []
    for seg in levels:
        if not isinstance(seg, dict):
            continue
        try:
            stage = _SLEEP_STAGE_BY_LEVEL.get(int(float(seg.get("activityLevel"))))
        except (TypeError, ValueError):
            stage = None
        if stage is None:
            logger.info("garmin sleepLevels: skipping unknown activityLevel=%r", seg.get("activityLevel"))
            continue
        start = _parse_garmin_naive_utc(seg.get("startGMT"))
        end = _parse_garmin_naive_utc(seg.get("endGMT"))
        if start is None or end is None or end <= start:
            logger.info("garmin sleepLevels: skipping segment with bad timestamps %r", seg)
            continue
        segments.append({"stage": stage, "start_at": start, "end_at": end})
    segments.sort(key=lambda s: s["start_at"])
    return segments


def _parse_garmin_ts(value: Any) -> datetime | None:
    """Garmin timestamps arrive as epoch ms or as naive-UTC ISO strings."""
    if isinstance(value, (int, float)):
        return _parse_epoch_ms(value)
    return _parse_garmin_naive_utc(value)


def parse_garmin_naps(payload: Any) -> list[dict[str, Any]]:
    """
    Naps from a Garmin sleep payload: get_sleep_data()['dailyNapDTOS'] or the list
    returned by get_naps(). Returns [{start, end, duration_min, calendar_date}],
    skipping entries without a usable time window.
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("dailyNapDTOS") or payload.get("dailyNapDTOs") or payload.get("naps") or []
    else:
        items = []
    naps: list[dict[str, Any]] = []
    for n in items if isinstance(items, list) else []:
        if not isinstance(n, dict):
            continue
        start = _parse_garmin_ts(n.get("napStartTimestampGMT") or n.get("startTimestampGMT") or n.get("startGMT"))
        end = _parse_garmin_ts(n.get("napEndTimestampGMT") or n.get("endTimestampGMT") or n.get("endGMT"))
        if start is None or end is None or end <= start:
            logger.info("garmin naps: skipping nap with bad timestamps %r", n)
            continue
        window_s = (end - start).total_seconds()
        try:
            dur_s = float(n.get("napTimeSec") or n.get("napTimeSeconds") or n.get("durationInSeconds") or window_s)
        except (TypeError, ValueError):
            dur_s = window_s
        dur_s = min(max(dur_s, 0.0), window_s)
        if dur_s < 60:
            continue
        naps.append(
            {
                "start": start,
                "end": end,
                "duration_min": int(round(dur_s / 60.0)),
                "calendar_date": n.get("calendarDate"),
            }
        )
    naps.sort(key=lambda x: x["start"])
    return naps


def _sync_end_date(db: Any, athlete_id: str) -> date:
    """
    Last day to sync: the later of UTC today and the athlete's local today. Garmin keys
    days by the athlete's local calendar, so a UTC-only end date missed this morning's
    sleep for athletes east of UTC until UTC midnight.
    """
    utc_today = datetime.now(timezone.utc).date()
    local_today = (datetime.now(timezone.utc) + timedelta(minutes=_athlete_offset_min(db, athlete_id))).date()
    return max(utc_today, local_today)


def _athlete_offset_min(db: Any, athlete_id: str) -> int:
    try:
        res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).maybe_single().execute()
        row = getattr(res, "data", None) if res else None
        return int((row or {}).get("timezone_offset_min") or 0)
    except Exception:
        return 0


def save_garmin_naps(
    athlete_id: str, db: Any, naps: list[dict[str, Any]], timezone_offset_min: int = 0
) -> list[str]:
    """
    Store naps as `sleep_periods` rows (is_nap=True), dated by the local wake day like
    WHOOP naps. Idempotent: the external id is derived from the athlete and nap start.
    Returns the dates touched.
    """
    if not naps:
        return []
    rows = []
    for nap in naps:
        start, end = nap["start"], nap["end"]
        cal = nap.get("calendar_date")
        try:
            day = date.fromisoformat(str(cal)[:10]) if cal else None
        except ValueError:
            day = None
        if day is None:
            day = (end + timedelta(minutes=timezone_offset_min or 0)).date()
        in_bed = int(round((end - start).total_seconds() / 60.0))
        rows.append(
            {
                "athlete_id": athlete_id,
                "date": day.isoformat(),
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "duration_min": nap["duration_min"],
                "in_bed_min": in_bed,
                "awake_pct": round(max(0, in_bed - nap["duration_min"]) / in_bed * 100.0, 1) if in_bed else None,
                "is_nap": True,
                "source": PROVIDER,
                # Athlete id in the key: sleep_periods is unique on (source, external_id) only.
                "external_id": f"{PROVIDER}:nap:{athlete_id}:{int(start.timestamp())}",
            }
        )
    db.table("sleep_periods").upsert(rows, on_conflict="athlete_id,source,external_id").execute()
    return sorted({r["date"] for r in rows})


def save_sleep_stage_segments(
    athlete_id: str, db: Any, day: date, segments: list[dict[str, Any]]
) -> int:
    """
    Replace this athlete+date+'garmin' rows with `segments` (idempotent re-sync).
    No segments => leave existing rows untouched (a transient empty response must
    not wipe stored data).
    """
    if not segments:
        return 0
    db.table("sleep_stage_segments").delete().eq("athlete_id", athlete_id).eq(
        "date", day.isoformat()
    ).eq("source", PROVIDER).execute()
    rows = [
        {
            "athlete_id": athlete_id,
            "date": day.isoformat(),
            "source": PROVIDER,
            "stage": s["stage"],
            "start_at": s["start_at"].isoformat(),
            "end_at": s["end_at"].isoformat(),
        }
        for s in segments
    ]
    db.table("sleep_stage_segments").upsert(rows, on_conflict="athlete_id,source,start_at").execute()
    return len(rows)


async def sync_weigh_ins(athlete_id: str, db: Any, client: Garmin, start_date: date, end_date: date) -> int:
    """Garmin weigh-ins (Index scale or entered in Garmin Connect) for the window: one call."""
    from app.services.weight import parse_garmin_weigh_ins, save_garmin_weigh_ins

    try:
        payload = await asyncio.to_thread(client.get_weigh_ins, start_date.isoformat(), end_date.isoformat())
        return await asyncio.to_thread(save_garmin_weigh_ins, db, athlete_id, parse_garmin_weigh_ins(payload))
    except Exception as exc:  # a 429 here waits for the next pass like any other
        logger.info("garmin weigh-ins sync failed athlete=%s: %s", athlete_id, exc)
        return 0


async def store_heart_rate_series_and_detect(
    athlete_id: str, db: Any, day: date, heart_rates: dict[str, Any] | None
) -> int:
    """Save the day's all-day heart rate and re-detect workouts; returns detections changed."""
    from app.services.heart_rate_series import parse_garmin_heart_rate_values, save_series
    from app.services.hr_activity_detection import detect_and_save_for_day

    samples = parse_garmin_heart_rate_values(heart_rates)
    if not samples:
        return 0
    try:
        await asyncio.to_thread(
            save_series, db, athlete_id, day, PROVIDER, samples,
            _round_int((heart_rates or {}).get("restingHeartRate")),
        )
    except Exception as exc:
        logger.warning("garmin heart rate series save failed athlete=%s date=%s: %s", athlete_id, day, exc)
        return 0
    try:
        res = await detect_and_save_for_day(db, athlete_id, day)
        return res["saved"] + res["removed"]
    except Exception as exc:
        logger.warning("hr activity detection failed athlete=%s date=%s: %s", athlete_id, day, exc)
        return 0


async def fetch_and_store_biometrics_for_day(
    athlete_id: str, db: Any, client: Garmin, day: date,
    detection_counter: dict[str, int] | None = None,
) -> bool:
    """
    Fetch sleep/HRV/resting-HR for one day and store via the canonical
    pipeline. Raises ``GarminRateLimitedError`` on a 429 from any of the
    three calls, without trying the remaining ones for this day — see
    GARMIN_RATE_LIMIT_COOLDOWN_SEC.
    """
    cdate = day.isoformat()
    sleep = hrv = heart_rates = None
    try:
        sleep = await asyncio.to_thread(client.get_sleep_data, cdate)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except Exception as exc:
        logger.info("garmin.get_sleep_data failed athlete=%s date=%s: %s", athlete_id, cdate, exc)
    try:
        hrv = await asyncio.to_thread(client.get_hrv_data, cdate)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except Exception as exc:
        logger.info("garmin.get_hrv_data failed athlete=%s date=%s: %s", athlete_id, cdate, exc)
    try:
        heart_rates = await asyncio.to_thread(client.get_heart_rates, cdate)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimitedError(str(exc)) from exc
    except Exception as exc:
        logger.info("garmin.get_heart_rates failed athlete=%s date=%s: %s", athlete_id, cdate, exc)

    # Stage timeline rides on the sleep response we already fetched (no extra Garmin
    # call). Stored independently of the summary so it survives WHOOP winning the night.
    try:
        await asyncio.to_thread(
            save_sleep_stage_segments, athlete_id, db, day, parse_sleep_stage_segments(sleep)
        )
    except Exception as exc:
        logger.warning("garmin sleep stage segments save failed athlete=%s date=%s: %s", athlete_id, cdate, exc)

    # Naps. Saved before the day's summary so the summary's sleep aggregation includes
    # them (as it does for WHOOP naps). Usually they ride on the sleep response; only
    # when Garmin reports nap time without the nap list do we spend a call on get_naps.
    naps = parse_garmin_naps(sleep)
    nap_seconds = ((sleep or {}).get("dailySleepDTO") or {}).get("napTimeSeconds") or 0
    if not naps and nap_seconds:
        try:
            naps = parse_garmin_naps(await asyncio.to_thread(client.get_naps, cdate))
        except GarminConnectTooManyRequestsError as exc:
            raise GarminRateLimitedError(str(exc)) from exc
        except Exception as exc:
            logger.info("garmin.get_naps failed athlete=%s date=%s: %s", athlete_id, cdate, exc)
    if naps:
        try:
            await asyncio.to_thread(
                save_garmin_naps, athlete_id, db, naps, _athlete_offset_min(db, athlete_id)
            )
        except Exception as exc:
            logger.warning("garmin naps save failed athlete=%s date=%s: %s", athlete_id, cdate, exc)

    # All-day heart rate (2-minute averages) rides on the get_heart_rates response we
    # already fetched; workouts are then detected from it. Activities sync before
    # biometrics, so the day's recorded workouts are already there to defer to.
    detected = await store_heart_rate_series_and_detect(athlete_id, db, day, heart_rates)
    if detection_counter is not None:
        detection_counter["changed"] = detection_counter.get("changed", 0) + detected

    payload = _daily_biometrics_from_garmin(day, sleep, hrv, heart_rates)
    if payload is None:
        return False
    # ~10 blocking queries plus a thread pool: keep them off the event loop.
    await asyncio.to_thread(lambda: process_and_save_biometrics(payload, athlete_id, db, skip_pmc_recalc=True))
    return True


async def sync_biometrics_for_athlete(
    athlete_id: str, db: Any, start_date: date, end_date: date
) -> int:
    client = await asyncio.to_thread(get_client_for_athlete, athlete_id, db)
    if client is None:
        return 0
    count = 0
    rate_limited = False
    detections: dict[str, int] = {}
    day = start_date
    while day <= end_date:
        try:
            if await fetch_and_store_biometrics_for_day(athlete_id, db, client, day, detections):
                count += 1
        except GarminRateLimitedError:
            logger.warning(
                "garmin biometrics sync rate-limited athlete=%s at day=%s; stopping this pass",
                athlete_id, day,
            )
            rate_limited = True
            break
        day += timedelta(days=1)
        await asyncio.sleep(GARMIN_REQUEST_GAP_S)
    if not rate_limited:
        await sync_weigh_ins(athlete_id, db, client, start_date, end_date)
    # New series / detections / weigh-ins: retire the cached Body screens.
    from app.core.body_cache import bump_body_cache

    await bump_body_cache(athlete_id)
    await asyncio.to_thread(persist_session, db, athlete_id, client)
    if detections.get("changed"):
        # Detected workouts carry TSS; fold them into CTL/ATL once for the whole pass.
        await asyncio.to_thread(recalculate_tss_history, athlete_id, db)
    if rate_limited:
        raise GarminRateLimitedError(f"rate-limited after {count} day(s) of biometrics")
    return count


# --------------------------------------------------------------------------
# Backfill
# --------------------------------------------------------------------------

async def backfill_historical_data(athlete_id: str, db: Any, days: int = 90) -> dict[str, int]:
    """
    Callers (the connect flow's scheduled backfill, the manual "sync now"
    route) always invoke this fire-and-forget — a GarminRateLimitedError
    left to propagate would just surface as an opaque "Task exception was
    never retrieved" warning from asyncio, so it's caught and logged clearly
    here instead. Whatever partial progress was made (and persisted) before
    the rate limit stands; the athlete's next manual "sync now" or the
    poll loop (once its cooldown elapses) picks up the rest.
    """
    days = max(1, min(int(days), 365))
    end_date = await asyncio.to_thread(_sync_end_date, db, athlete_id)
    start_date = end_date - timedelta(days=days - 1)

    workouts = {"workouts": 0, "streams": 0}
    biometrics_count = 0
    try:
        workouts = await sync_activities_for_athlete(athlete_id, db, start_date, end_date)
        biometrics_count = await sync_biometrics_for_athlete(athlete_id, db, start_date, end_date)
    except GarminRateLimitedError as exc:
        logger.warning(
            "Garmin backfill rate-limited athlete=%s days=%s: %s — partial progress kept",
            athlete_id, days, exc,
        )
        return {
            "workouts": workouts.get("workouts", 0),
            "streams": workouts.get("streams", 0),
            "biometrics": biometrics_count,
            "days": days,
            "rate_limited": True,
        }

    logger.info(
        "Garmin backfill complete athlete=%s workouts=%s streams=%s biometrics=%s days=%s",
        athlete_id,
        workouts.get("workouts", 0),
        workouts.get("streams", 0),
        biometrics_count,
        days,
    )
    return {
        "workouts": workouts.get("workouts", 0),
        "streams": workouts.get("streams", 0),
        "biometrics": biometrics_count,
        "days": days,
    }


# --------------------------------------------------------------------------
# Periodic poll (no webhook exists for this integration — see docs)
# --------------------------------------------------------------------------

# Small recent window per tick, not a full re-backfill: an hourly cadence
# only needs to catch up on what's new since the last tick, and fetching the
# smallest useful window keeps a lost tick's Garmin-quota spend cheap.
POLL_WINDOW_DAYS = 2


async def _poll_one_athlete(athlete_id: str, db: Any) -> None:
    if not await asyncio.to_thread(_claim_sync_lock, db, athlete_id):
        logger.debug("garmin poll: athlete_id=%s locked by another replica; skipping", athlete_id)
        return
    rate_limited = False
    try:
        end_date = await asyncio.to_thread(_sync_end_date, db, athlete_id)
        start_date = end_date - timedelta(days=POLL_WINDOW_DAYS - 1)
        await sync_activities_for_athlete(athlete_id, db, start_date, end_date)
        await sync_biometrics_for_athlete(athlete_id, db, start_date, end_date)
    except GarminRateLimitedError:
        rate_limited = True
        logger.warning(
            "garmin poll: rate-limited athlete_id=%s; skipping for %ds",
            athlete_id, GARMIN_RATE_LIMIT_COOLDOWN_SEC,
        )
    except Exception as exc:
        logger.warning("garmin poll: sync failed athlete_id=%s: %s", athlete_id, exc)
    finally:
        if rate_limited:
            # Held past the normal lock duration so the *next* poll tick
            # (an hour later, by default) still sees this athlete as
            # "locked" and skips it, rather than immediately retrying into
            # the same rate limit.
            await asyncio.to_thread(_cooldown_sync_lock, db, athlete_id, GARMIN_RATE_LIMIT_COOLDOWN_SEC)
        else:
            await asyncio.to_thread(_release_sync_lock, db, athlete_id)


async def poll_tick(db: Any) -> int:
    """One pass over every connected Garmin athlete. Returns the count processed."""
    res = await asyncio.to_thread(
        db.table("oauth_tokens")
        .select("athlete_id")
        .eq("provider", PROVIDER)
        .execute
    )
    athlete_ids = [row["athlete_id"] for row in (getattr(res, "data", None) or [])]
    for athlete_id in athlete_ids:
        await _poll_one_athlete(athlete_id, db)
    return len(athlete_ids)


def _poll_interval_sec() -> int:
    minutes = getattr(settings, "GARMIN_SYNC_POLL_MINUTES", None)
    if minutes:
        return max(60, int(minutes) * 60)
    return max(1, int(settings.GARMIN_SYNC_POLL_HOURS)) * 3600


async def poll_loop() -> None:
    """Long-running asyncio task started at FastAPI startup (see main.py)."""
    while True:
        interval_sec = _poll_interval_sec()
        try:
            db = get_admin_db()
            processed = await poll_tick(db)
            if processed:
                logger.info("garmin poll tick complete athletes=%s", processed)
        except Exception as exc:
            logger.warning("garmin poll tick failed: %s", exc)
        await asyncio.sleep(interval_sec)
