"""
Proactive OAuth token refresh background task.

Runs every 30 minutes and refreshes any WHOOP tokens that will expire within
the next 10 minutes. This prevents the reactive-refresh race condition where
simultaneous webhook requests both try to rotate an expired token.

astraphe-api runs multiple replicas (2, as of the 2026-07-03 k3s migration),
and this loop runs independently in-process in each one with no shared
scheduler. Two replicas can therefore wake up and see the same "expiring
soon" row at once. Each refresh first takes an atomic DB-level claim
(a conditional UPDATE on oauth_tokens.refresh_lock_expires_at) before calling
the provider, so only one replica ever calls WHOOP's refresh endpoint for a
given token at a time — calling it twice concurrently for the same
refresh_token risks tripping the provider's reuse-detection and having it
permanently revoke the grant (this is what happened 2026-07-04).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.dependencies import get_admin_db
from app.services import whoop

_REFRESH_INTERVAL_SEC = 30 * 60   # check every 30 minutes
_EXPIRY_BUFFER_SEC    = 10 * 60   # refresh when < 10 minutes remain
_LOCK_DURATION_SEC    = 5 * 60    # claim duration; generous vs. a single HTTP round trip


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

    print(f"[token_refresh] found {len(rows)} expiring WHOOP token(s)")
    for row in rows:
        try:
            token_data = await claim_and_refresh_whoop_token(
                db, row["athlete_id"], row["refresh_token"]
            )
            if token_data is None:
                print(f"[token_refresh] skipping athlete_id={row['athlete_id']} — another replica holds the lock")
            else:
                print(f"[token_refresh] refreshed token for athlete_id={row['athlete_id']}")
        except Exception as e:
            print(f"[token_refresh] failed to refresh token for athlete_id={row.get('athlete_id')}: {e}")


async def claim_and_refresh_whoop_token(db, athlete_id: str, refresh_token: str) -> dict | None:
    """
    Atomically claim the refresh lock for this athlete's WHOOP token, then
    refresh and persist it. Shared by the proactive sweep loop above and any
    reactive refresh path (e.g. whoop_backfill._ensure_valid_whoop_access_token)
    so that no two replicas ever call WHOOP's refresh endpoint for the same
    refresh_token concurrently (see module docstring — this is what caused
    the permanent WHOOP grant revocation on 2026-07-04).

    Returns the new token_data dict from WHOOP, or None if another replica
    currently holds the lock (it is refreshing this token right now — callers
    that need a token immediately should poll the DB briefly rather than
    calling this again straight away).
    """
    now = datetime.now(timezone.utc)
    lock_until = (now + timedelta(seconds=_LOCK_DURATION_SEC)).isoformat()

    # Atomic claim: the WHERE clause is evaluated by Postgres against the
    # row's current state at UPDATE time, so this is race-free even though
    # we never issued a SELECT ... FOR UPDATE.
    claim = (
        db.table("oauth_tokens")
        .update({"refresh_lock_expires_at": lock_until})
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .lt("refresh_lock_expires_at", now.isoformat())
        .execute()
    )
    if not claim.data:
        return None

    try:
        token_data = await whoop.refresh_oauth_token(refresh_token)
    except Exception:
        # Release the lock early so a retry (this or another replica) doesn't
        # have to wait out the full claim duration.
        db.table("oauth_tokens").update(
            {"refresh_lock_expires_at": now.isoformat()}
        ).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()
        raise

    new_access = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token") or refresh_token
    new_expires = token_expires_at(token_data)
    update: dict = {
        "refresh_lock_expires_at": now.isoformat(),  # release immediately, no need to hold it
    }
    if new_access:
        update["access_token"] = new_access
    update["refresh_token"] = new_refresh
    if new_expires:
        update["expires_at"] = new_expires
    db.table("oauth_tokens").update(update).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()
    return token_data


async def token_refresh_loop() -> None:
    """Long-running asyncio task started at FastAPI startup."""
    while True:
        try:
            await _refresh_expiring_whoop_tokens()
        except Exception as e:
            print(f"[token_refresh] unexpected error in refresh loop: {e}")
        await asyncio.sleep(_REFRESH_INTERVAL_SEC)
