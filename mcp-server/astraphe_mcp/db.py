"""RLS-scoped Supabase access for the MCP server.

Mirrors backend/app/dependencies.py's get_user_db()/get_current_athlete() pattern:
apply the caller's own JWT to a per-call Supabase client (so RLS enforces per-user
scoping, not application code), then resolve athlete_id from it. Never share a
JWT-authenticated client across callers.
"""
from __future__ import annotations

import time

from supabase import Client, create_client

from astraphe_mcp.config import settings

# Short-lived athlete_id cache keyed on access token, to avoid a redundant `athletes`
# lookup on every tool call within one MCP session. Tokens are short-lived themselves
# (Supabase default jwt_expiry), so this cache self-invalidates on token rotation.
_ATHLETE_ID_CACHE_TTL_SECONDS = 300
_athlete_id_cache: dict[str, tuple[str, float]] = {}


class AthleteProfileNotFound(RuntimeError):
    """Raised when the authenticated Supabase user has no matching athletes row."""


def get_scoped_db(access_token: str) -> Client:
    """A fresh, per-call Supabase client authenticated as the calling user.

    Never reuse or cache this client across callers — same rule as
    backend/app/dependencies.py:get_user_db().
    """
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    try:
        db.postgrest.auth(access_token)
    except Exception:
        db.postgrest.session.headers.update({"Authorization": f"Bearer {access_token}"})
    return db


async def resolve_athlete_id(db: Client, access_token: str) -> str:
    """Resolve the calling user's athletes.id from their verified access token.

    Never derived from client-supplied input — always looked up server-side from the
    user_id embedded in the (already-verified) token, same invariant as
    backend/app/dependencies.py:get_current_athlete().
    """
    cached = _athlete_id_cache.get(access_token)
    if cached is not None:
        athlete_id, cached_at = cached
        if time.monotonic() - cached_at < _ATHLETE_ID_CACHE_TTL_SECONDS:
            return athlete_id

    from app.dependencies import run_supabase_call  # backend/app on PYTHONPATH, see docs/MCP_SERVER.md

    user_res = await run_supabase_call(lambda: db.auth.get_user(access_token))
    user_id = user_res.user.id

    athlete_res = await run_supabase_call(
        lambda: db.table("athletes").select("id").eq("user_id", user_id).execute()
    )
    if not athlete_res.data:
        raise AthleteProfileNotFound("No Astraphe athlete profile found for this account")

    athlete_id = athlete_res.data[0]["id"]
    _athlete_id_cache[access_token] = (athlete_id, time.monotonic())
    return athlete_id
