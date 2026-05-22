"""
Proactive OAuth token refresh background task.

Runs every 30 minutes and refreshes any WHOOP tokens that will expire within
the next 10 minutes. This prevents the reactive-refresh race condition where
simultaneous webhook requests both try to rotate an expired token.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.dependencies import get_admin_db
from app.services import whoop

_REFRESH_INTERVAL_SEC = 30 * 60   # check every 30 minutes
_EXPIRY_BUFFER_SEC    = 10 * 60   # refresh when < 10 minutes remain


def token_expires_at(token_data: dict) -> str | None:
    """Return an ISO-8601 UTC timestamp for when this token expires, or None."""
    expires_in = token_data.get("expires_in")
    try:
        secs = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()


async def _refresh_expiring_whoop_tokens() -> None:
    db = get_admin_db()  # service-role key so RLS doesn't block cross-athlete reads
    cutoff = (datetime.now(timezone.utc) + timedelta(seconds=_EXPIRY_BUFFER_SEC)).isoformat()
    try:
        res = (
            db.table("oauth_tokens")
            .select("id,athlete_id,external_user_id,access_token,refresh_token,expires_at")
            .eq("provider", "whoop")
            .not_.is_("refresh_token", "null")
            .lte("expires_at", cutoff)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        print(f"[token_refresh] failed to query expiring tokens: {e}")
        return

    if not rows:
        return

    print(f"[token_refresh] refreshing {len(rows)} expiring WHOOP token(s)")
    for row in rows:
        try:
            token_data = await whoop.refresh_oauth_token(row["refresh_token"])
            new_access  = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token") or row["refresh_token"]
            new_expires = token_expires_at(token_data)
            if not new_access:
                continue
            update: dict = {"access_token": new_access, "refresh_token": new_refresh}
            if new_expires:
                update["expires_at"] = new_expires
            db.table("oauth_tokens").update(update).eq("id", row["id"]).execute()
            print(f"[token_refresh] refreshed token for athlete_id={row['athlete_id']}")
        except Exception as e:
            print(f"[token_refresh] failed to refresh token for athlete_id={row.get('athlete_id')}: {e}")


async def token_refresh_loop() -> None:
    """Long-running asyncio task started at FastAPI startup."""
    while True:
        try:
            await _refresh_expiring_whoop_tokens()
        except Exception as e:
            print(f"[token_refresh] unexpected error in refresh loop: {e}")
        await asyncio.sleep(_REFRESH_INTERVAL_SEC)
