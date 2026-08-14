"""Settings for the Astraphe MCP server.

Mirrors backend/app/config.py's shape deliberately: same field names for the Supabase
settings shared with the backend, same .env-over-shell-env dev convention. This is a
separate Settings instance (not the backend's) so the two services can be configured,
deployed, and rotated independently.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

MCP_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    APP_NAME: str = "ASTRAPHE-MCP"
    APP_ENV: str = "development"
    PORT: int = 8090

    # --- Supabase (same project as the backend; RLS scopes every call by the caller's JWT) ---
    SUPABASE_URL: str = "http://127.0.0.1:54321"
    SUPABASE_KEY: str = "test-anon-key"

    # --- MCP OAuth resource-server config (Supabase Auth / GoTrue acts as the authorization
    # server — see docs/MCP_SERVER.md). issuer_url must match GoTrue's own issuer exactly
    # (its /auth/v1/.well-known/oauth-authorization-server `issuer` field). ---
    MCP_ISSUER_URL: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:54321/auth/v1")
    MCP_RESOURCE_URL: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8090")

    # Dynamic client registration is on in production (see docs/MCP_SERVER.md) — any
    # MCP client can self-register without a manually-issued client ID/secret, which is
    # exactly why MCP_RATE_LIMIT_RPM below is enforced rather than aspirational.
    MCP_ALLOW_DYNAMIC_CLIENT_REGISTRATION: bool = False

    # --- Rate limiting: enforced in astraphe_mcp/tools/_call.py via backend/app/core/
    # rate_limiter.py's RateLimiter, reused unmodified, with a distinct key prefix so
    # MCP tool calls don't share quota with in-app coach calls. Deliberately no REDIS_URL
    # field here — that RateLimiter reads backend's own app.config.settings.REDIS_URL
    # (via app.core.redis.get_redis()) to get a shared Redis instance/state, not a
    # separate one; set REDIS_URL on the backend service to make this multi-instance-safe,
    # otherwise it falls back to this process's own in-memory state (fine for a single
    # replica, resets on restart).
    MCP_RATE_LIMIT_RPM: int = 30

    model_config = SettingsConfigDict(
        env_file=MCP_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # .env takes priority over shell env vars in dev — same convention as
        # backend/app/config.py, so stale shell exports don't shadow local settings.
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


settings = Settings()
