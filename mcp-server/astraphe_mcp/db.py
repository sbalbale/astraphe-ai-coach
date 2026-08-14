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


def _prune_expired_athlete_id_cache_entries(now: float) -> None:
    expired = [
        token for token, (_, cached_at) in _athlete_id_cache.items()
        if now - cached_at >= _ATHLETE_ID_CACHE_TTL_SECONDS
    ]
    for token in expired:
        del _athlete_id_cache[token]


async def resolve_athlete_id(db: Client, access_token: str, user_id: str) -> str:
    """Resolve the calling user's athletes.id from their verified access token.

    `user_id` must come from the same token's AccessToken.subject (set by
    AstrapheTokenVerifier from the auth.get_user() call already made during token
    verification) — never re-derive it here with a second auth.get_user() round trip, and
    never accept it as client-supplied input. `athlete_id` itself is always looked up
    server-side, same invariant as backend/app/dependencies.py:get_current_athlete().
    """
    now = time.monotonic()
    cached = _athlete_id_cache.get(access_token)
    if cached is not None:
        athlete_id, cached_at = cached
        if now - cached_at < _ATHLETE_ID_CACHE_TTL_SECONDS:
            return athlete_id

    from app.dependencies import run_supabase_call  # backend/app on PYTHONPATH, see docs/MCP_SERVER.md

    athlete_res = await run_supabase_call(
        lambda: db.table("athletes").select("id").eq("user_id", user_id).execute()
    )
    if not athlete_res.data:
        raise AthleteProfileNotFound("No Astraphe athlete profile found for this account")

    athlete_id = athlete_res.data[0]["id"]
    # Sweep expired entries on every cache miss instead of a background task — bounds
    # growth in a long-running process without needing a scheduler. O(n) on miss only,
    # not on every lookup.
    _prune_expired_athlete_id_cache_entries(now)
    _athlete_id_cache[access_token] = (athlete_id, now)
    return athlete_id
