"""astraphe_mcp.asgi is the actual uvicorn entrypoint (see Dockerfile's CMD) — this just
confirms importing it builds a real, mountable ASGI app, the same thing docs/MCP_SERVER.md's
manual uvicorn/Docker verification exercised live."""
from __future__ import annotations


def test_asgi_app_builds():
    from astraphe_mcp.asgi import app, mcp

    assert mcp.name == "astraphe"
    assert callable(app)  # a Starlette instance is itself an ASGI callable
