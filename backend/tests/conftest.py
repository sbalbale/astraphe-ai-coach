from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import (
    get_current_athlete,
    get_current_gemini_model,
    get_current_user_tier,
    get_user_config,
    get_user_db,
    require_ai_rate_limit,
    UserConfig,
)

# The UUID we want to return whenever the API asks for the current authenticated user
MOCK_ATHLETE_ID = "550e8400-e29b-41d4-a716-446655440000"

def override_get_current_athlete():
    """Mock authentication dependency that returns a fixed athlete ID."""
    return MOCK_ATHLETE_ID


def override_get_current_user_tier():
    """Coach and plan routes require premium in tests."""
    return "premium"


def override_get_user_config():
    """Mock combined auth/config dependency used by coach routes."""
    return UserConfig(
        user_id="fake-user-id",
        tier="premium",
        gemini_model="gemini-flash-lite-test",
        gemini_analysis_model="gemini-flash-lite-test",
        rate_limit_rpm=1000,
        rate_limit_rph=1000,
        is_admin=False,
    )


async def override_require_ai_rate_limit():
    return None


@pytest.fixture
def client():
    """Provides a test client with bypassed authentication."""
    # Tell FastAPI to use our mock function instead of checking for a Supabase JWT
    app.dependency_overrides[get_current_athlete] = override_get_current_athlete
    app.dependency_overrides[get_current_user_tier] = override_get_current_user_tier
    app.dependency_overrides[get_user_config] = override_get_user_config
    app.dependency_overrides[require_ai_rate_limit] = override_require_ai_rate_limit

    # Yield the client so tests can use it
    with TestClient(app) as test_client:
        yield test_client

    # Clean up the overrides after the tests finish
    app.dependency_overrides = {}

@pytest.fixture
def test_athlete_id():
    """A standard UUID for consistent testing across modules."""
    return MOCK_ATHLETE_ID


# ---------------------------------------------------------------------------
# Fake Supabase client for hermetic router tests
# ---------------------------------------------------------------------------


class _FakeSupabaseQuery:
    """Minimal chainable fake matching the supabase-py table/rpc surface used in routes."""

    def __init__(self, rows: list[dict] | None = None, fake_id: str = "fake-row-id"):
        self._rows: list[dict] = list(rows) if rows is not None else []
        self._single_mode = False
        self._fake_id = fake_id

    # Mutating ops --------------------------------------------------------
    def insert(self, payload, *_a, **_k):
        # Echo back what was inserted, ensuring an id is present so route code
        # that reads `res.data[0]["id"]` keeps working.
        if isinstance(payload, dict):
            row = {**payload}
            row.setdefault("id", self._fake_id)
            self._rows = [row]
        elif isinstance(payload, list):
            self._rows = [
                {**r, "id": r.get("id") or self._fake_id} for r in payload
            ]
        return self

    def update(self, *_a, **_k):
        return self

    def delete(self, *_a, **_k):
        return self

    # Read-side filters (all no-ops on the fake) --------------------------
    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def neq(self, *_a, **_k):
        return self

    def gt(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def single(self):
        self._single_mode = True
        return self

    def maybe_single(self):
        self._single_mode = True
        return self

    def execute(self):
        if self._single_mode:
            data = self._rows[0] if self._rows else None
        else:
            data = self._rows
        return SimpleNamespace(data=data)


class _FakeSupabaseClient:
    """Minimal in-memory stand-in for the supabase-py Client."""

    # Per-table fake row id used when an insert payload doesn't supply one.
    _FAKE_IDS: dict[str, str] = {
        "coach_conversations": "fake-conversation-id",
        "coach_messages": "fake-message-id",
    }

    def __init__(self):
        # Pre-seeded rows per table so reads return realistic shapes.
        # Routes mainly need: a coach_conversations row that looks "untitled"
        # so title-setting logic exercises both branches.
        self._table_seeds: dict[str, list[dict]] = {
            "coach_conversations": [
                {"id": "fake-conversation-id", "athlete_id": MOCK_ATHLETE_ID, "title": None}
            ],
            "coach_messages": [],
        }
        # Some code paths reach for these directly; provide harmless mocks.
        self.auth = MagicMock()
        self.postgrest = MagicMock()
        self.storage = MagicMock()

    def table(self, name: str) -> _FakeSupabaseQuery:
        return _FakeSupabaseQuery(
            rows=self._table_seeds.get(name, []),
            fake_id=self._FAKE_IDS.get(name, "fake-row-id"),
        )

    def rpc(self, *_a, **_k) -> _FakeSupabaseQuery:
        return _FakeSupabaseQuery([])


@pytest.fixture
def fake_db() -> _FakeSupabaseClient:
    return _FakeSupabaseClient()


@pytest.fixture
def coach_client(fake_db):
    """
    Test client with auth, DB, and Gemini-model dependencies all stubbed.
    Use this for any router test that hits an endpoint depending on
    get_user_db or get_current_gemini_model.
    """
    app.dependency_overrides[get_current_athlete] = override_get_current_athlete
    app.dependency_overrides[get_current_user_tier] = override_get_current_user_tier
    app.dependency_overrides[get_user_config] = override_get_user_config
    app.dependency_overrides[get_user_db] = lambda: fake_db
    app.dependency_overrides[get_current_gemini_model] = lambda: "gemini-flash-lite-test"
    app.dependency_overrides[require_ai_rate_limit] = override_require_ai_rate_limit

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides = {}