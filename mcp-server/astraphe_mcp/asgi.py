"""ASGI entrypoint. Run with: uvicorn astraphe_mcp.asgi:app --host 0.0.0.0 --port 8090

Streamable HTTP only (see docs/MCP_SERVER.md for why) — no stdio/SSE transport here.
"""
from astraphe_mcp.server import build_mcp_server

mcp = build_mcp_server()
app = mcp.streamable_http_app()
