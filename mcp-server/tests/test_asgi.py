"""astraphe_mcp.asgi is the actual uvicorn entrypoint (see Dockerfile's CMD) — this just
confirms importing it builds a real, mountable ASGI app, the same thing docs/MCP_SERVER.md's
manual uvicorn/Docker verification exercised live."""
from __future__ import annotations


def test_asgi_app_builds():
    from astraphe_mcp.asgi import app, mcp

    assert mcp.name == "astraphe"
    assert callable(app)  # a Starlette instance is itself an ASGI callable


def test_transport_security_allows_the_deployed_resource_host():
    """Regression test: streamable_http_app()'s DNS-rebinding protection defaults to
    localhost-only Host validation when transport_security isn't passed explicitly —
    which 421s every real request once this server sits behind a public hostname (caught
    live: Claude's connection failed with 421 Misdirected Request / "Invalid Host header:
    mcp.astrapheai.com" against production). transport_security_for() must derive
    allowed_hosts from whatever MCP_RESOURCE_URL actually is, not just from what happens
    to match the local-dev default (127.0.0.1) — hence testing it directly against a
    production-shaped URL rather than via the ambient test-environment settings.
    """
    from astraphe_mcp.asgi import transport_security_for

    security = transport_security_for("https://mcp.astrapheai.com")

    assert security.allowed_hosts == ["mcp.astrapheai.com", "mcp.astrapheai.com:*"]
    assert "https://mcp.astrapheai.com" in security.allowed_origins


def test_transport_security_for_local_dev_resource_url():
    from astraphe_mcp.asgi import transport_security_for

    security = transport_security_for("http://127.0.0.1:8090")

    assert security.allowed_hosts == ["127.0.0.1:8090", "127.0.0.1:*"]


def test_asgi_app_wires_transport_security_from_settings():
    from astraphe_mcp.asgi import mcp
    from astraphe_mcp.config import settings

    security = mcp.session_manager.security_settings
    assert security is not None

    resource_netloc = str(settings.MCP_RESOURCE_URL).split("://", 1)[1].rstrip("/")
    assert resource_netloc in security.allowed_hosts
