import base64
import hmac
import hashlib
import httpx
from fastapi import HTTPException
from app.config import settings
from typing import Any, List, Optional

def _whoop_client_secret() -> str | None:
    """Client secret from env/Secret Manager, stripped (avoids trailing newlines)."""
    raw = settings.WHOOP_CLIENT_SECRET
    return raw.strip() if raw else None


def _whoop_oauth_credentials() -> tuple[str, str]:
    """client_id + client_secret for token exchange (WHOOP expects client_secret_post)."""
    client_id = (settings.WHOOP_CLIENT_ID or "").strip()
    client_secret = _whoop_client_secret() or ""
    if not client_id or not client_secret:
        print("[whoop.oauth] WHOOP_CLIENT_ID or WHOOP_CLIENT_SECRET is missing/empty")
        raise HTTPException(status_code=500, detail="WHOOP OAuth is not configured on the server")
    return client_id, client_secret


def _whoop_hmac_key() -> bytes | None:
    """WHOOP HMAC key is the client secret string as UTF-8 (not hex-decoded)."""
    secret = (settings.WHOOP_WEBHOOK_SECRET or "").strip() or _whoop_client_secret()
    if not secret:
        return None
    return secret.encode("utf-8")


def verify_webhook_signature(
    payload_body: bytes,
    signature_header: str,
    timestamp_header: str | None = None,
) -> bool:
    """
    Verifies the HMAC-SHA256 signature sent by WHOOP.

    WHOOP signs: base64(HMAC-SHA256(timestamp + raw_body, client_secret)).
    See https://developer.whoop.com/docs/developing/webhooks#webhooks-security
    """
    key = _whoop_hmac_key()
    if key is None:
        print("[whoop.sig] WHOOP_WEBHOOK_SECRET / WHOOP_CLIENT_SECRET not set — rejecting")
        return False
    if not timestamp_header:
        print("[whoop.sig] Missing X-WHOOP-Signature-Timestamp — rejecting")
        return False
    msg = timestamp_header.encode("utf-8") + payload_body
    expected_signature = base64.b64encode(
        hmac.new(key=key, msg=msg, digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    match = hmac.compare_digest(expected_signature, signature_header)
    if not match:
        print(
            f"[whoop.sig] MISMATCH — received={signature_header[:16]}... "
            f"expected={expected_signature[:16]}... "
            f"body_len={len(payload_body)} ts={timestamp_header[:13]}..."
        )
    return match

async def exchange_oauth_code(code: str, redirect_url: str) -> dict:
    """Exchanges the code for tokens. Must match the URL sent in the first step."""
    client_id, client_secret = _whoop_oauth_credentials()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.WHOOP_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_url,  # Key in payload MUST be redirect_uri
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            print(f"WHOOP Exchange Error: {response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange WHOOP code")
        return response.json()

async def refresh_oauth_token(refresh_token: str) -> dict:
    """
    Refresh WHOOP OAuth tokens using the refresh_token grant.
    WHOOP may rotate refresh tokens; callers should persist returned values.
    """
    client_id, client_secret = _whoop_oauth_credentials()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.WHOOP_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"WHOOP refresh failed: {response.status_code} {response.text}",
            )
        try:
            return response.json()
        except Exception:
            body = response.text
            snippet = body[:300] if body else "<empty body>"
            raise HTTPException(status_code=502, detail=f"WHOOP refresh returned non-JSON: {snippet}")

async def fetch_recovery_data(access_token: str, cycle_id: int | str) -> dict:
    """Fetches recovery metrics for a specific cycle."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # v2 docs: GET /v2/cycle/{cycleId}/recovery
        response = await client.get(f"{_v2_base()}/cycle/{cycle_id}/recovery", headers=headers)
        return _json_or_error(response, "fetch_recovery_data(v2)")


def recovery_is_scored(recovery_data: dict | None) -> bool:
    """True when WHOOP has finished scoring this recovery (safe to persist vitals)."""
    if not recovery_data:
        return False
    state = recovery_data.get("score_state")
    if state and state != "SCORED":
        return False
    score = recovery_data.get("score")
    return isinstance(score, dict) and bool(score)


def recovery_score_to_vitals(score: dict) -> dict[str, Any]:
    """Normalize WHOOP recovery score fields into DailyBiometrics-compatible keys."""
    hrv = score.get("hrv_rmssd_milli")
    if hrv is None:
        hrv = score.get("hrv_rmssd_ms")
    return {
        "hrv_rmssd": hrv,
        "resting_hr": score.get("resting_heart_rate"),
        "spo2_pct": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
        "recovery_score": score.get("recovery_score"),
    }


def build_whoop_vitals_from_recovery(recovery_data: dict) -> dict[str, Any]:
    """Extract vitals from a scored recovery document."""
    score = recovery_data.get("score") if isinstance(recovery_data.get("score"), dict) else {}
    return recovery_score_to_vitals(score)


async def fetch_recovery_for_sleep(
    access_token: str,
    sleep_id: Any,
    *,
    sleep_data: dict | None = None,
) -> dict | None:
    """
    Resolve recovery for a sleep record via its cycle_id.
    Returns None if recovery is missing or not yet SCORED.
    """
    sleep = sleep_data if sleep_data is not None else await fetch_sleep_data(access_token, sleep_id)
    cycle_id = sleep.get("cycle_id")
    if cycle_id is None:
        return None
    try:
        recovery = await fetch_recovery_data(access_token, cycle_id)
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise
    if not recovery_is_scored(recovery):
        return None
    return recovery


async def fetch_recovery_for_event_id(access_token: str, event_id: Any) -> dict | None:
    """
    Fetch recovery for a webhook event id.
    v1 webhooks use numeric cycle ids; v2 recovery.updated uses sleep UUIDs.
    """
    eid = str(event_id)
    if eid.isdigit():
        try:
            recovery = await fetch_recovery_data(access_token, int(eid))
        except HTTPException as e:
            if e.status_code == 404:
                return None
            raise
        if not recovery_is_scored(recovery):
            return None
        return recovery
    return await fetch_recovery_for_sleep(access_token, eid)

async def fetch_sleep_data(access_token: str, sleep_id: Any) -> dict:
    """Fetches sleep performance data (v2 uses UUID ids)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # v2 docs: GET /v2/activity/sleep/{sleepId}
        sid = str(sleep_id)
        response = await client.get(f"{_v2_base()}/activity/sleep/{sid}", headers=headers)
        return _json_or_error(response, "fetch_sleep_data(v2)")

def _json_or_error(response: httpx.Response, label: str) -> dict:
    """
    WHOOP sometimes responds with non-JSON bodies on error.
    Make failures obvious so webhook ingestion doesn't silently "200 OK" without saving.
    """
    if response.status_code < 200 or response.status_code >= 300:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"WHOOP {label} failed: {response.status_code} {response.text}",
        )
    try:
        return response.json()
    except Exception:
        body = response.text
        snippet = body[:300] if body else "<empty body>"
        raise HTTPException(
            status_code=502,
            detail=f"WHOOP {label} returned non-JSON: {snippet}",
        )


async def fetch_workout_data(access_token: str, workout_id: Any) -> dict:
    """
    Fetches detailed workout metrics.

    WHOOP webhooks may deliver UUID-like workout IDs (v2). Try v2 first in that case,
    otherwise fall back to v1 base.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    wid = str(workout_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # If it's not a pure integer, it's likely a v2 record id.
        if not wid.isdigit():
            res = await client.get(f"{_v2_base()}/activity/workout/{wid}", headers=headers)
            return _json_or_error(res, "fetch_workout_data(v2)")

        res = await client.get(f"{settings.WHOOP_API_BASE}/activity/workout/{wid}", headers=headers)
        return _json_or_error(res, "fetch_workout_data(v1)")

async def fetch_profile(access_token: str) -> dict:
    """Fetches basic user profile info."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # v2 docs: GET /v2/user/profile/basic
        response = await client.get(f"{_v2_base()}/user/profile/basic", headers=headers)
        return _json_or_error(response, "fetch_profile(v2)")

async def fetch_body_measurement(access_token: str) -> dict:
    """Fetches user body measurements like weight and max HR."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # v2 docs: GET /v2/user/measurement/body
        response = await client.get(f"{_v2_base()}/user/measurement/body", headers=headers)
        return _json_or_error(response, "fetch_body_measurement(v2)")




def _v2_base() -> str:
    base = settings.WHOOP_API_BASE.rstrip("/")
    # Many projects store v1 base; collection endpoints are documented under /developer/v2.
    if base.endswith("/v1"):
        return base[:-3] + "/v2"
    if base.endswith("/developer/v1"):
        return base[:-3] + "v2"
    if base.endswith("/developer/v2"):
        return base
    # Fallback: best guess
    return "https://api.prod.whoop.com/developer/v2"


async def fetch_collection(
    access_token: str,
    path: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 25,
) -> List[dict[str, Any]]:
    """
    Fetch a paginated WHOOP collection (v2) and return all records.
    `path` examples: 'recovery', 'activity/sleep', 'activity/workout', 'cycle'
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{_v2_base()}/{path.lstrip('/')}"

    records: List[dict[str, Any]] = []
    next_token: Optional[str] = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict[str, Any] = {"limit": min(max(1, limit), 25)}
            if start:
                params["start"] = start
            if end:
                params["end"] = end
            if next_token:
                params["nextToken"] = next_token

            res = await client.get(url, headers=headers, params=params)
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=f"WHOOP collection fetch failed: {res.text}")

            payload = res.json() or {}
            page_records = payload.get("records") or []
            if isinstance(page_records, list):
                records.extend(page_records)

            next_token = payload.get("next_token") or payload.get("nextToken")
            if not next_token:
                break

    return records


def hr_zone_pct_from_whoop_zone_millis(
    zone_durations: Optional[dict[str, Any]],
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    """
    Map WHOOP ``zone_durations`` (milliseconds per zone) to five integer percentages Z1-Z5 summing to 100.
    WHOOP Z0 time is folded into Astrape Z1 (active recovery begins at 0 bpm).
    """
    zone = zone_durations or {}
    hr0 = int(zone.get("zone_zero_milli") or 0)
    hr1 = int(zone.get("zone_one_milli") or 0)
    hr2 = int(zone.get("zone_two_milli") or 0)
    hr3 = int(zone.get("zone_three_milli") or 0)
    hr4 = int(zone.get("zone_four_milli") or 0)
    hr5 = int(zone.get("zone_five_milli") or 0)

    raw = [hr0 + hr1, hr2, hr3, hr4, hr5]
    total_ms = sum(raw)
    if total_ms <= 0:
        return (None, None, None, None, None)

    pcts = [round(v / total_ms * 100) for v in raw]
    diff = 100 - sum(pcts)
    if diff != 0:
        pcts[pcts.index(max(pcts))] += diff

    return (pcts[0], pcts[1], pcts[2], pcts[3], pcts[4])