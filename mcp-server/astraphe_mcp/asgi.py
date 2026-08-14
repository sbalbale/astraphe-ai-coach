"""ASGI entrypoint. Run with: uvicorn astraphe_mcp.asgi:app --host 0.0.0.0 --port 8090

Streamable HTTP only (see docs/MCP_SERVER.md for why) — no stdio/SSE transport here.
"""
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings

from astraphe_mcp.config import settings
from astraphe_mcp.server import build_mcp_server


def transport_security_for(resource_url: str) -> TransportSecuritySettings:
    """streamable_http_app()'s DNS-rebinding protection defaults to localhost-only Host
    validation (transport_security=None) — a bare 421 Misdirected Request for every real
    request once this server sits behind a public hostname, since it can't infer what
    hostname it's served behind (caught live: Claude's connection failed with 421
    Misdirected Request / "Invalid Host header: mcp.astrapheai.com" against production).
    Derive the allowed Host from MCP_RESOURCE_URL — the one hostname this server is
    actually meant to be reached as — instead of hardcoding the production domain here.
    """
    netloc = urlsplit(resource_url).netloc  # e.g. "mcp.astrapheai.com" or "127.0.0.1:8090"
    host = netloc.split(":", 1)[0]
    return TransportSecuritySettings(
        allowed_hosts=[netloc, f"{host}:*"],
        allowed_origins=[resource_url.rstrip("/"), "https://claude.ai", "https://claude.com"],
    )


mcp = build_mcp_server()
app = mcp.streamable_http_app(transport_security=transport_security_for(str(settings.MCP_RESOURCE_URL)))
