import hmac
import hashlib
import httpx
from fastapi import HTTPException
from app.config import settings
from typing import Any, List, Optional

def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verifies the HMAC-SHA256 signature using the Client Secret."""
    if not settings.WHOOP_WEBHOOK_SECRET:
        return False
    expected_signature = hmac.new(
        key=settings.WHOOP_WEBHOOK_SECRET.encode('utf-8'),
        msg=payload_body,
        digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)

async def exchange_oauth_code(code: str, redirect_url: str) -> dict:
    """Exchanges the code for tokens. Must match the URL sent in the first step."""
    async with httpx.AsyncClient() as client:
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

async def fetch_recovery_data(access_token: str, cycle_id: int) -> dict:
    """Fetches recovery metrics for a specific cycle."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.WHOOP_API_BASE}/cycle/{cycle_id}/recovery", headers=headers)
        return response.json()

async def fetch_sleep_data(access_token: str, sleep_id: int) -> dict:
    """Fetches sleep performance data."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.WHOOP_API_BASE}/activity/sleep/{sleep_id}", headers=headers)
        return response.json()

async def fetch_workout_data(access_token: str, workout_id: int) -> dict:
    """Fetches detailed workout metrics."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.WHOOP_API_BASE}/activity/workout/{workout_id}", headers=headers)
        return response.json()

async def fetch_profile(access_token: str) -> dict:
    """Fetches basic user profile info."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.WHOOP_API_BASE}/user/profile/basic", headers=headers)
        return response.json()

async def fetch_body_measurement(access_token: str) -> dict:
    """Fetches user body measurements like weight and max HR."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.WHOOP_API_BASE}/user/measurement/body", headers=headers)
        return response.json()


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