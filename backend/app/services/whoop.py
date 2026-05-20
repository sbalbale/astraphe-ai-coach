import base64
import hmac
import hashlib
import httpx
from fastapi import HTTPException
from app.config import settings
from typing import Any, List, Optional

def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    Verifies the HMAC-SHA256 signature sent by WHOOP.
    WHOOP signs webhook payloads with the app's Client Secret as the HMAC key.
    WHOOP_WEBHOOK_SECRET must equal the Client Secret from the WHOOP Developer Portal.
    """
    if not settings.WHOOP_WEBHOOK_SECRET:
        print("[whoop.sig] WHOOP_WEBHOOK_SECRET is not set — rejecting")
        return False
    # WHOOP sends a base64-encoded HMAC-SHA256.
    # The client secret is a hex string; WHOOP uses the raw decoded bytes as the HMAC key.
    secret = settings.WHOOP_WEBHOOK_SECRET
    try:
        key = bytes.fromhex(secret)
    except ValueError:
        key = secret.encode('utf-8')
    expected_signature = base64.b64encode(
        hmac.new(
            key=key,
            msg=payload_body,
            digestmod=hashlib.sha256
        ).digest()
    ).decode('utf-8')
    match = hmac.compare_digest(expected_signature, signature_header)
    if not match:
        print(
            f"[whoop.sig] MISMATCH — received={signature_header[:16]}... "
            f"expected={expected_signature[:16]}... "
            f"body_len={len(payload_body)}"
        )
    return match

async def exchange_oauth_code(code: str, redirect_url: str) -> dict:
    """Exchanges the code for tokens. Must match the URL sent in the first step."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.WHOOP_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.WHOOP_CLIENT_ID,
                "client_secret": settings.WHOOP_CLIENT_SECRET,
                "redirect_uri": redirect_url, # Key in payload MUST be redirect_uri
            }
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.WHOOP_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.WHOOP_CLIENT_ID,
                "client_secret": settings.WHOOP_CLIENT_SECRET,
            },
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

async def fetch_recovery_data(access_token: str, cycle_id: int) -> dict:
    """Fetches recovery metrics for a specific cycle."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # v2 docs: GET /v2/cycle/{cycleId}/recovery
        response = await client.get(f"{_v2_base()}/cycle/{cycle_id}/recovery", headers=headers)
        return _json_or_error(response, "fetch_recovery_data(v2)")

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