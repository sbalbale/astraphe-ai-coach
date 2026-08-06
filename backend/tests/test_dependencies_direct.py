from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import dependencies as deps
from app.config import settings


def _run_async(coro):
    return asyncio.run(coro)


def _creds(token="tok"):
    return SimpleNamespace(credentials=token)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def test_get_db_creates_client_with_anon_key():
    fake_client = MagicMock()
    with patch.object(deps, "create_client", return_value=fake_client) as mock_create:
        result = deps.get_db()

    mock_create.assert_called_once_with(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    assert result is fake_client


def test_get_admin_db_caches_singleton(monkeypatch):
    monkeypatch.setattr(deps, "_admin_db_client", None)
    fake_client = MagicMock()

    with patch.object(deps, "create_client", return_value=fake_client) as mock_create:
        first = deps.get_admin_db()
        second = deps.get_admin_db()

    mock_create.assert_called_once()
    assert first is fake_client
    assert second is fake_client
    monkeypatch.setattr(deps, "_admin_db_client", None)


def test_with_auth_token_prefers_postgrest_auth():
    fake_db = MagicMock()
    result = deps._with_auth_token(fake_db, "jwt-token")

    fake_db.postgrest.auth.assert_called_once_with("jwt-token")
    assert result is fake_db


def test_with_auth_token_falls_back_to_headers_on_failure():
    fake_db = MagicMock()
    fake_db.postgrest.auth.side_effect = RuntimeError("no auth method")

    deps._with_auth_token(fake_db, "jwt-token")

    fake_db.postgrest.session.headers.update.assert_called_once_with(
        {"Authorization": "Bearer jwt-token"}
    )


def test_with_auth_token_swallows_total_failure():
    fake_db = MagicMock()
    fake_db.postgrest.auth.side_effect = RuntimeError("no auth")
    fake_db.postgrest.session.headers.update.side_effect = RuntimeError("no headers either")

    result = deps._with_auth_token(fake_db, "jwt-token")  # should not raise
    assert result is fake_db


def test_get_user_db_applies_bearer_token():
    fake_db = MagicMock()
    with patch.object(deps, "get_db", return_value=fake_db):
        result = _run_async(deps.get_user_db(credentials=_creds("abc")))

    fake_db.postgrest.auth.assert_called_once_with("abc")
    assert result is fake_db


# ---------------------------------------------------------------------------
# Transient error detection + run_supabase_call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "ConnectionTerminated",
        "connection terminated",
        "server disconnected",
        "connection reset",
        "broken pipe",
        "eof occurred",
    ],
)
def test_is_transient_db_error_matches_known_messages(message):
    assert deps._is_transient_db_error(RuntimeError(message)) is True


def test_is_transient_db_error_false_for_unrelated_error():
    assert deps._is_transient_db_error(ValueError("some other failure")) is False


def test_run_supabase_call_returns_result_on_success():
    result = _run_async(deps.run_supabase_call(lambda: 42))
    assert result == 42


def test_run_supabase_call_raises_503_on_timeout():
    def _fn():
        raise TimeoutError("shouldn't be called directly")

    async def _fake_wait_for(coro, timeout):
        coro.close()  # avoid a "coroutine was never awaited" warning
        raise asyncio.TimeoutError()

    with patch("asyncio.wait_for", _fake_wait_for):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps.run_supabase_call(_fn))

    assert exc_info.value.status_code == 503


def test_run_supabase_call_retries_transient_errors_then_succeeds():
    attempts = {"n": 0}

    def _fn():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("connection reset")
        return "ok"

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = _run_async(deps.run_supabase_call(_fn, retries=3))

    assert result == "ok"
    assert attempts["n"] == 2


def test_run_supabase_call_raises_503_after_exhausting_transient_retries():
    def _fn():
        raise RuntimeError("connection reset")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps.run_supabase_call(_fn, retries=2))

    assert exc_info.value.status_code == 503


def test_run_supabase_call_reraises_non_transient_error_immediately():
    def _fn():
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        _run_async(deps.run_supabase_call(_fn, retries=3))


def test_is_pgrst002_matches_substring():
    assert deps._is_pgrst002(RuntimeError("schema cache: PGRST002")) is True
    assert deps._is_pgrst002(RuntimeError("other error")) is False


# ---------------------------------------------------------------------------
# get_current_user_email
# ---------------------------------------------------------------------------


def test_get_current_user_email_returns_email():
    fake_db = MagicMock()
    with patch.object(
        deps, "_auth_get_user", AsyncMock(return_value=SimpleNamespace(user=SimpleNamespace(email="a@x.com")))
    ):
        result = _run_async(deps.get_current_user_email(credentials=_creds(), db=fake_db))

    assert result == "a@x.com"


def test_get_current_user_email_returns_none_on_failure():
    fake_db = MagicMock()
    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("bad token"))):
        result = _run_async(deps.get_current_user_email(credentials=_creds(), db=fake_db))

    assert result is None


# ---------------------------------------------------------------------------
# get_current_athlete
# ---------------------------------------------------------------------------


def test_get_current_athlete_happy_path():
    fake_db = MagicMock()
    with patch.object(
        deps, "_auth_get_user", AsyncMock(return_value=SimpleNamespace(user=SimpleNamespace(id="user-1")))
    ), patch.object(deps, "_fetch_athlete_id_for_user", AsyncMock(return_value="athlete-1")):
        result = _run_async(deps.get_current_athlete(credentials=_creds(), db=fake_db))

    assert result == "athlete-1"


def test_get_current_athlete_falls_back_to_test_athlete_id(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "TEST_ATHLETE_ID", "test-athlete-1")
    fake_db = MagicMock()

    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("invalid token"))), patch.object(
        deps, "_run_supabase_call", AsyncMock(return_value=SimpleNamespace(data={"id": "test-athlete-1"}))
    ):
        result = _run_async(deps.get_current_athlete(credentials=_creds(), db=fake_db))

    assert result == "test-athlete-1"
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "TEST_ATHLETE_ID", None)


def test_get_current_athlete_raises_401_when_no_fallback(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    fake_db = MagicMock()

    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("invalid token"))):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps.get_current_athlete(credentials=_creds(), db=fake_db))

    assert exc_info.value.status_code == 401


def test_get_current_athlete_raises_503_on_persistent_pgrst002(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    fake_db = MagicMock()

    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("PGRST002"))), patch(
        "asyncio.sleep", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps.get_current_athlete(credentials=_creds(), db=fake_db))

    assert exc_info.value.status_code == 503


def test_fetch_athlete_id_for_user_raises_404_when_missing():
    fake_db = MagicMock()
    with patch.object(deps, "_run_supabase_call", AsyncMock(return_value=SimpleNamespace(data=[]))):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps._fetch_athlete_id_for_user(fake_db, "user-1"))

    assert exc_info.value.status_code == 404


def test_fetch_athlete_id_for_user_returns_id():
    fake_db = MagicMock()
    with patch.object(
        deps, "_run_supabase_call", AsyncMock(return_value=SimpleNamespace(data=[{"id": "athlete-9"}]))
    ):
        result = _run_async(deps._fetch_athlete_id_for_user(fake_db, "user-1"))

    assert result == "athlete-9"


# ---------------------------------------------------------------------------
# _resolve_rate_limits
# ---------------------------------------------------------------------------


def test_resolve_rate_limits_uses_tier_defaults_when_unset():
    rpm, rph = deps._resolve_rate_limits({}, "trial")
    assert (rpm, rph) == (15, 75)


def test_resolve_rate_limits_uses_overrides_when_present():
    rpm, rph = deps._resolve_rate_limits({"rate_limit_rpm": 999, "rate_limit_rph": 4000}, "free")
    assert (rpm, rph) == (999, 4000)


def test_resolve_rate_limits_falls_back_on_invalid_override():
    rpm, rph = deps._resolve_rate_limits({"rate_limit_rpm": "not-a-number"}, "premium")
    assert rpm == 40  # premium default


def test_resolve_rate_limits_never_returns_below_one():
    rpm, rph = deps._resolve_rate_limits({"rate_limit_rpm": -5, "rate_limit_rph": 0}, "free")
    assert rpm >= 1 and rph >= 1


# ---------------------------------------------------------------------------
# get_user_config
# ---------------------------------------------------------------------------


def test_get_user_config_reads_app_metadata():
    fake_db = MagicMock()
    fake_user = SimpleNamespace(
        id="user-1",
        app_metadata={
            "tier": "PREMIUM",
            "gemini_model": " gemini-pro ",
            "is_admin": True,
        },
    )
    with patch.object(deps, "_auth_get_user", AsyncMock(return_value=SimpleNamespace(user=fake_user))):
        result = _run_async(deps.get_user_config(credentials=_creds(), db=fake_db))

    assert result.tier == "premium"
    assert result.gemini_model == "gemini-pro"
    assert result.is_admin is True
    assert result.rate_limit_rpm == 40


def test_get_user_config_defaults_invalid_tier_to_free():
    fake_db = MagicMock()
    fake_user = SimpleNamespace(id="user-1", app_metadata={"tier": "not-a-real-tier"})
    with patch.object(deps, "_auth_get_user", AsyncMock(return_value=SimpleNamespace(user=fake_user))):
        result = _run_async(deps.get_user_config(credentials=_creds(), db=fake_db))

    assert result.tier == "free"


def test_get_user_config_raises_401_for_auth_errors():
    fake_db = MagicMock()
    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("invalid jwt"))):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(deps.get_user_config(credentials=_creds(), db=fake_db))

    assert exc_info.value.status_code == 401


def test_get_user_config_falls_back_to_free_on_unexpected_error():
    fake_db = MagicMock()
    with patch.object(deps, "_auth_get_user", AsyncMock(side_effect=RuntimeError("network blip"))):
        result = _run_async(deps.get_user_config(credentials=_creds(), db=fake_db))

    assert result.tier == "free"
    assert result.user_id == ""


# ---------------------------------------------------------------------------
# require_ai_rate_limit + backward-compat helpers
# ---------------------------------------------------------------------------


def test_require_ai_rate_limit_enforces_minute_and_hour_windows():
    config = deps.UserConfig(
        user_id="u1",
        tier="free",
        gemini_model="m",
        gemini_analysis_model="m2",
        rate_limit_rpm=5,
        rate_limit_rph=20,
        is_admin=False,
    )
    fake_limiter = MagicMock()
    fake_limiter.require = AsyncMock()

    with patch.object(deps, "_rate_limiter", fake_limiter):
        _run_async(deps.require_ai_rate_limit(athlete_id="athlete-1", config=config))

    assert fake_limiter.require.await_count == 2


def test_backward_compat_helpers_read_from_config():
    config = deps.UserConfig(
        user_id="u1",
        tier="trial",
        gemini_model="model-a",
        gemini_analysis_model="model-b",
        rate_limit_rpm=15,
        rate_limit_rph=75,
        is_admin=False,
    )

    assert _run_async(deps.get_current_user_tier(config=config)) == "trial"
    assert _run_async(deps.get_current_gemini_model(config=config)) == "model-a"
    assert _run_async(deps.get_current_gemini_analysis_model(config=config)) == "model-b"
