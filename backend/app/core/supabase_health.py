"""
Lightweight Supabase / PostgREST reachability check for /health.
Uses the service-role client so the probe does not depend on user JWTs.
"""

import asyncio
import logging

from app.config import settings
from app.dependencies import get_admin_db

logger = logging.getLogger(__name__)

# Keep in sync with auth dependency timeouts (dependencies.py).
PROBE_TIMEOUT_SECONDS = 10.0


def _probe_postgrest_sync() -> None:
    """Raises on PGRST002, timeouts, or connection errors."""
    db = get_admin_db()
    db.table("athletes").select("id").limit(1).execute()


async def ping_supabase() -> bool:
    """Returns True when PostgREST can serve a trivial query."""
    if not settings.SUPABASE_URL or not (
        settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    ):
        return False
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_probe_postgrest_sync),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        return True
    except Exception as exc:
        logger.debug("Supabase health probe failed: %s", exc)
        return False
