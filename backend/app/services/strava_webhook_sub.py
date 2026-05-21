"""Strava push subscription helpers (dev drift detection + registration)."""
from __future__ import annotations

import httpx

from app.config import settings

STRAVA_PUSH_SUBS_URL = "https://www.strava.com/api/v3/push_subscriptions"


def expected_callback_url() -> str | None:
    if not settings.APP_BASE_URL:
        return None
    prefix = (settings.API_PREFIX or "/v1").rstrip("/")
    return f"{settings.APP_BASE_URL.rstrip('/')}{prefix}/sync/strava/webhook"


def fetch_push_subscriptions() -> list[dict]:
    if not settings.STRAVA_CLIENT_ID or not settings.STRAVA_CLIENT_SECRET:
        return []
    r = httpx.get(
        STRAVA_PUSH_SUBS_URL,
        params={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def subscription_matches_app_base() -> tuple[bool, str]:
    """
    Returns (ok, human-readable detail).
    Strava allows one subscription per callback URL per app; we expect exactly one
    matching APP_BASE_URL when webhooks are configured.
    """
    expected = expected_callback_url()
    if not expected:
        return True, "APP_BASE_URL not set; skip Strava subscription check"

    try:
        subs = fetch_push_subscriptions()
    except Exception as e:
        return True, f"Could not query Strava subscriptions: {e}"

    if not subs:
        return False, f"No Strava push subscription. Register: {expected}"

    matching = [s for s in subs if s.get("callback_url") == expected]
    if matching:
        return True, f"Strava webhook OK (id={matching[0].get('id')})"

    registered = ", ".join(
        f"{s.get('id')}→{s.get('callback_url')}" for s in subs if s.get("callback_url")
    )
    return (
        False,
        f"Strava webhook mismatch. Expected {expected}. Registered: {registered or 'none'}. "
        f"Run: python scripts/register_strava_webhook.py",
    )
