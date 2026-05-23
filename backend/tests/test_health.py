"""Health endpoint includes Supabase probe."""

from unittest.mock import AsyncMock, patch

from app.main import app
from fastapi.testclient import TestClient


def test_health_reports_supabase_and_redis():
    client = TestClient(app)
    with (
        patch("app.main.ping_redis", new_callable=AsyncMock, return_value=True),
        patch("app.main.ping_supabase", new_callable=AsyncMock, return_value=True),
    ):
        res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["redis"] == "connected"
    assert body["supabase"] == "connected"


def test_health_degraded_when_supabase_unavailable():
    client = TestClient(app)
    with (
        patch("app.main.ping_redis", new_callable=AsyncMock, return_value=True),
        patch("app.main.ping_supabase", new_callable=AsyncMock, return_value=False),
    ):
        res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    assert body["supabase"] == "unavailable"
