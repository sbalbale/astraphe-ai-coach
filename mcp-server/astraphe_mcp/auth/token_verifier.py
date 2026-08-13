"""Validates bearer tokens issued by Supabase Auth's OAuth Server (GoTrue).

Same validation primitive backend/app/dependencies.py uses for every request
(db.auth.get_user(token) — delegates verification to Supabase Auth itself; nothing here
manually decodes or checks a JWT signature). See docs/MCP_SERVER.md for why Supabase's
OAuth Server mode was chosen over a bespoke OAuth authorization server.
"""
from __future__ import annotations

import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier
from supabase import create_client

from astraphe_mcp.config import settings

logger = logging.getLogger(__name__)


class AstrapheTokenVerifier(TokenVerifier):
    """Verifies a Supabase-OAuth-Server-issued access token for the MCP resource server."""

    async def verify_token(self, token: str) -> AccessToken | None:
        # Unauthenticated client is fine here — auth.get_user(token) validates the token
        # itself; the returned client isn't used for any data access, only verification.
        db = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        try:
            user_res = await self._get_user(db, token)
        except Exception:
            logger.info("MCP token verification failed", exc_info=True)
            return None

        user = getattr(user_res, "user", None)
        if user is None:
            return None

        app_metadata = getattr(user, "app_metadata", None) or {}
        client_id = app_metadata.get("client_id") if isinstance(app_metadata, dict) else None

        return AccessToken(
            token=token,
            client_id=client_id or "",
            # Read-only for the whole of Phase 1 (see docs/MCP_SERVER.md) — no per-token
            # scope distinction to make yet; write tools in Phase 3 will gate on a real
            # "astraphe:write" scope read from the token/consent grant instead of this
            # hardcoded value.
            scopes=["astraphe:read"],
            resource=str(settings.MCP_RESOURCE_URL),
            subject=user.id,
        )

    @staticmethod
    async def _get_user(db, token: str):
        from app.dependencies import run_supabase_call  # backend/app on PYTHONPATH, see docs/MCP_SERVER.md

        return await run_supabase_call(lambda: db.auth.get_user(token))
