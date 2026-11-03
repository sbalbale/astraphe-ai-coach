"""Revoke third-party grants before an account is deleted."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.token_crypto import decrypt_oauth_row

logger = logging.getLogger(__name__)

STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"


def _whoop_revoke_url() -> str:
    from app.services.whoop import _v2_base

    return f"{_v2_base()}/user/access"


async def revoke_provider_grants(admin_db: Any, athlete_id: str) -> dict[str, bool]:
    """
    Best effort: tell WHOOP and Strava to drop Astraphe's access, so deleting the
    account also stops the providers sending us this person's data. Garmin (stored
    session) and Intervals (API key) have nothing to revoke; their rows go with the
    account. Returns provider -> revoked.
    """
    try:
        res = (
            admin_db.table("oauth_tokens")
            .select("provider,access_token")
            .eq("athlete_id", athlete_id)
            .in_("provider", ["strava", "whoop"])
            .execute()
        )
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        logger.warning("account deletion: couldn't read tokens for athlete_id=%s: %s", athlete_id, e)
        return {}

    out: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for raw in rows:
            row = decrypt_oauth_row(raw) or {}
            provider, token = row.get("provider"), row.get("access_token")
            if not provider or not token:
                continue
            try:
                if provider == "strava":
                    resp = await client.post(STRAVA_DEAUTHORIZE_URL, data={"access_token": token})
                else:
                    resp = await client.delete(_whoop_revoke_url(), headers={"Authorization": f"Bearer {token}"})
                out[provider] = resp.status_code < 300
            except Exception as e:  # noqa: BLE001
                logger.warning("account deletion: %s revoke failed for athlete_id=%s: %s", provider, athlete_id, e)
                out[provider] = False
    return out
