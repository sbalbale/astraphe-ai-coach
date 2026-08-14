"""Shared fixtures for the MCP server test suite.

Reuses backend/tests/conftest.py's hermetic fake Supabase client and MOCK_ATHLETE_ID
constant directly (see docs/MCP_SERVER.md's reuse strategy) so both test suites agree on
what "a fake athlete" looks like. Loaded by explicit file path (not `from tests.conftest
import ...`) because backend/tests/ and mcp-server/tests/ are both literally named `tests`
— a plain package import would collide between the two. What doesn't transfer from
backend's conftest is its FastAPI dependency-override half — MCP has no Depends graph, so
`fake_authenticated_call` below is this suite's own equivalent: it monkeypatches the two
seams `astraphe_mcp.tools._call.call_handler` actually reads from (get_access_token and
get_scoped_db) rather than overriding a FastAPI dependency.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND_CONFTEST_PATH = Path(__file__).resolve().parent.parent.parent / "backend" / "tests" / "conftest.py"
_spec = importlib.util.spec_from_file_location("backend_tests_conftest", _BACKEND_CONFTEST_PATH)
_backend_conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backend_conftest)

_FakeSupabaseClient = _backend_conftest._FakeSupabaseClient
MOCK_ATHLETE_ID = _backend_conftest.MOCK_ATHLETE_ID

FAKE_USER_ID = "fake-user-id-0000-0000-000000000000"
FAKE_ACCESS_TOKEN = "fake-access-token"


@pytest.fixture(autouse=True)
def reset_athlete_id_cache():
    """astraphe_mcp.db._athlete_id_cache is a process-global dict keyed on access token —
    same kind of test-pollution risk backend/tests/conftest.py resets for its own
    globals (_ip_rate_limiter, gemini_quota). Different tests reusing the same literal
    token string would otherwise see a stale cached athlete_id from an earlier test."""
    from astraphe_mcp.db import _athlete_id_cache

    _athlete_id_cache.clear()
    yield
    _athlete_id_cache.clear()


@pytest.fixture
def mock_athlete_id() -> str:
    return MOCK_ATHLETE_ID


@pytest.fixture
def fake_db() -> _FakeSupabaseClient:
    db = _FakeSupabaseClient()
    db.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id=FAKE_USER_ID))
    # _FakeSupabaseClient seeds a few tables already (see backend/tests/conftest.py);
    # add the athletes row resolve_athlete_id() looks up.
    db._table_seeds["athletes"] = [{"id": MOCK_ATHLETE_ID, "user_id": FAKE_USER_ID}]
    return db


@pytest.fixture
def fake_authenticated_call(monkeypatch, fake_db):
    """Makes astraphe_mcp.tools._call.call_handler() act as if FAKE_ACCESS_TOKEN belongs
    to MOCK_ATHLETE_ID, backed by fake_db, without needing a real MCP request/transport."""
    from mcp.server.auth.provider import AccessToken

    fixed_token = AccessToken(
        token=FAKE_ACCESS_TOKEN,
        client_id="test-client",
        scopes=["astraphe:read"],
        subject=FAKE_USER_ID,
    )
    monkeypatch.setattr("astraphe_mcp.tools._call.get_access_token", lambda: fixed_token)
    monkeypatch.setattr("astraphe_mcp.tools._call.get_scoped_db", lambda _token: fake_db)
    return fake_db
