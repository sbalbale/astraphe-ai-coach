"""Builds the Astraphe MCPServer instance: auth wiring + tool registration."""
from __future__ import annotations

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer

from astraphe_mcp.auth.token_verifier import AstrapheTokenVerifier
from astraphe_mcp.config import settings
from astraphe_mcp.tools.registry import register_all


def build_mcp_server() -> MCPServer:
    mcp = MCPServer(
        name="astraphe",
        title="Astraphe",
        description="Read your Astraphe training data — workouts, biometrics, training load, coach memory.",
        token_verifier=AstrapheTokenVerifier(),
        auth=AuthSettings(
            issuer_url=str(settings.MCP_ISSUER_URL),
            resource_server_url=str(settings.MCP_RESOURCE_URL),
            required_scopes=["astraphe:read"],
            client_registration_options=ClientRegistrationOptions(
                enabled=settings.MCP_ALLOW_DYNAMIC_CLIENT_REGISTRATION,
            ),
        ),
    )
    register_all(mcp)
    return mcp
