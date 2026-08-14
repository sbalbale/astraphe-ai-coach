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
            # Must be a scope GoTrue's OAuth Server actually supports (openid/profile/
            # email/phone only — see docs/MCP_SERVER.md). This gets published in RFC 9728
            # protected-resource metadata AND enforced against the token's own scopes by
            # the SDK's bearer-auth middleware, so a mismatch here breaks auth twice over:
            # once when a spec-compliant client dutifully requests exactly the advertised
            # scope from GoTrue (which rejects unsupported ones outright), and again if a
            # token ever did carry a scope this list doesn't require. Covered by
            # tests/test_mcp_protocol.py::test_required_scopes_are_a_subset_of_what_the_verifier_grants.
            required_scopes=["openid"],
            client_registration_options=ClientRegistrationOptions(
                enabled=settings.MCP_ALLOW_DYNAMIC_CLIENT_REGISTRATION,
            ),
        ),
    )
    register_all(mcp)
    return mcp
