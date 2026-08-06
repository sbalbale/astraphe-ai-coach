from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import whoop


def _run_async(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._json_data


class _FakeAsyncClient:
    """Mimics httpx.AsyncClient as an async context manager with queued responses."""

    def __init__(self, *_a, get=None, post=None, **_k):
        self._get_response = get
        self._post_response = post
        self.get_calls: list[tuple] = []
        self.post_calls: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        resp = self._get_response
        return resp(url, kwargs) if callable(resp) else resp

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        resp = self._post_response
        return resp(url, kwargs) if callable(resp) else resp


def _patch_client(**kwargs):
    return patch.object(whoop.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(*a, **kwargs, **k))


# ---------------------------------------------------------------------------
# OAuth credential helpers
# ---------------------------------------------------------------------------


def test_whoop_oauth_credentials_raises_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", None)

    with pytest.raises(HTTPException) as exc_info:
        whoop._whoop_oauth_credentials()
    assert exc_info.value.status_code == 500


def test_whoop_oauth_credentials_returns_stripped_values(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", " client-1 ")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", " secret-1 \n")

    client_id, client_secret = whoop._whoop_oauth_credentials()
    assert client_id == "client-1"
    assert client_secret == "secret-1"


# ---------------------------------------------------------------------------
# exchange_oauth_code / refresh_oauth_token
# ---------------------------------------------------------------------------


def test_exchange_oauth_code_success(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", "secret-1")
    resp = _FakeResponse(status_code=200, json_data={"access_token": "tok"})

    with _patch_client(post=resp):
        result = _run_async(whoop.exchange_oauth_code("code-1", "https://redirect"))

    assert result == {"access_token": "tok"}


def test_exchange_oauth_code_raises_on_failure(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", "secret-1")
    resp = _FakeResponse(status_code=400, text="bad code")

    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(whoop.exchange_oauth_code("bad-code", "https://redirect"))
    assert exc_info.value.status_code == 400


def test_refresh_oauth_token_success(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", "secret-1")
    resp = _FakeResponse(status_code=200, json_data={"access_token": "new-tok"})

    with _patch_client(post=resp):
        result = _run_async(whoop.refresh_oauth_token("refresh-1"))

    assert result == {"access_token": "new-tok"}


def test_refresh_oauth_token_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", "secret-1")
    resp = _FakeResponse(status_code=401, text="invalid_grant")

    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(whoop.refresh_oauth_token("bad-refresh"))
    assert exc_info.value.status_code == 401


def test_refresh_oauth_token_raises_502_on_non_json_body(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "WHOOP_CLIENT_SECRET", "secret-1")
    resp = _FakeResponse(status_code=200, text="<html>oops</html>", json_error=True)

    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(whoop.refresh_oauth_token("refresh-1"))
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# recovery helpers
# ---------------------------------------------------------------------------


def test_recovery_is_scored_false_cases():
    assert whoop.recovery_is_scored(None) is False
    assert whoop.recovery_is_scored({"score_state": "PENDING"}) is False
    assert whoop.recovery_is_scored({"score_state": "SCORED", "score": {}}) is False
    assert whoop.recovery_is_scored({"score_state": "SCORED", "score": "not-a-dict"}) is False


def test_recovery_is_scored_true_case():
    assert whoop.recovery_is_scored({"score_state": "SCORED", "score": {"recovery_score": 80}}) is True


def test_recovery_score_to_vitals_prefers_hrv_rmssd_milli():
    vitals = whoop.recovery_score_to_vitals(
        {"hrv_rmssd_milli": 55, "hrv_rmssd_ms": 60, "resting_heart_rate": 48}
    )
    assert vitals["hrv_rmssd"] == 55
    assert vitals["resting_hr"] == 48


def test_recovery_score_to_vitals_falls_back_to_ms_field():
    vitals = whoop.recovery_score_to_vitals({"hrv_rmssd_ms": 60})
    assert vitals["hrv_rmssd"] == 60


def test_build_whoop_vitals_from_recovery_handles_non_dict_score():
    vitals = whoop.build_whoop_vitals_from_recovery({"score": "not-a-dict"})
    assert vitals["hrv_rmssd"] is None


def test_fetch_recovery_for_sleep_returns_none_without_cycle_id():
    async def _fake_fetch_sleep(_token, _sleep_id):
        return {"cycle_id": None}

    with patch.object(whoop, "fetch_sleep_data", _fake_fetch_sleep):
        result = _run_async(whoop.fetch_recovery_for_sleep("tok", "sleep-1"))
    assert result is None


def test_fetch_recovery_for_sleep_returns_none_on_404():
    async def _fake_fetch_recovery(_token, _cycle_id):
        raise HTTPException(status_code=404)

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(
            whoop.fetch_recovery_for_sleep("tok", "sleep-1", sleep_data={"cycle_id": 42})
        )
    assert result is None


def test_fetch_recovery_for_sleep_reraises_non_404():
    async def _fake_fetch_recovery(_token, _cycle_id):
        raise HTTPException(status_code=500)

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        with pytest.raises(HTTPException):
            _run_async(whoop.fetch_recovery_for_sleep("tok", "sleep-1", sleep_data={"cycle_id": 42}))


def test_fetch_recovery_for_sleep_returns_none_when_unscored():
    async def _fake_fetch_recovery(_token, _cycle_id):
        return {"score_state": "PENDING"}

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(
            whoop.fetch_recovery_for_sleep("tok", "sleep-1", sleep_data={"cycle_id": 42})
        )
    assert result is None


def test_fetch_recovery_for_sleep_returns_scored_recovery():
    async def _fake_fetch_recovery(_token, _cycle_id):
        return {"score_state": "SCORED", "score": {"recovery_score": 80}}

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(
            whoop.fetch_recovery_for_sleep("tok", "sleep-1", sleep_data={"cycle_id": 42})
        )
    assert result["score"]["recovery_score"] == 80


def test_fetch_recovery_for_event_id_numeric_uses_cycle_lookup():
    async def _fake_fetch_recovery(_token, cycle_id):
        assert cycle_id == 123
        return {"score_state": "SCORED", "score": {"recovery_score": 90}}

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(whoop.fetch_recovery_for_event_id("tok", "123"))
    assert result["score"]["recovery_score"] == 90


def test_fetch_recovery_for_event_id_numeric_returns_none_when_unscored():
    async def _fake_fetch_recovery(_token, _cycle_id):
        return {"score_state": "PENDING_SCORE"}

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(whoop.fetch_recovery_for_event_id("tok", "123"))
    assert result is None


def test_fetch_recovery_for_event_id_numeric_404_returns_none():
    async def _fake_fetch_recovery(_token, _cycle_id):
        raise HTTPException(status_code=404)

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        result = _run_async(whoop.fetch_recovery_for_event_id("tok", "999"))
    assert result is None


def test_fetch_recovery_for_event_id_numeric_reraises_non_404():
    async def _fake_fetch_recovery(_token, _cycle_id):
        raise HTTPException(status_code=500)

    with patch.object(whoop, "fetch_recovery_data", _fake_fetch_recovery):
        with pytest.raises(HTTPException):
            _run_async(whoop.fetch_recovery_for_event_id("tok", "999"))


def test_fetch_recovery_for_event_id_uuid_delegates_to_sleep_lookup():
    async def _fake_fetch_for_sleep(_token, eid, **_k):
        assert eid == "abc-uuid"
        return {"cycle_id": 1}

    with patch.object(whoop, "fetch_recovery_for_sleep", _fake_fetch_for_sleep):
        result = _run_async(whoop.fetch_recovery_for_event_id("tok", "abc-uuid"))
    assert result == {"cycle_id": 1}


# ---------------------------------------------------------------------------
# _json_or_error / fetch_* wrappers
# ---------------------------------------------------------------------------


def test_json_or_error_raises_on_non_2xx():
    resp = _FakeResponse(status_code=404, text="not found")
    with pytest.raises(HTTPException) as exc_info:
        whoop._json_or_error(resp, "test")
    assert exc_info.value.status_code == 404


def test_json_or_error_raises_502_on_non_json_success():
    resp = _FakeResponse(status_code=200, text="<html>", json_error=True)
    with pytest.raises(HTTPException) as exc_info:
        whoop._json_or_error(resp, "test")
    assert exc_info.value.status_code == 502


def test_json_or_error_returns_parsed_json():
    resp = _FakeResponse(status_code=200, json_data={"a": 1})
    assert whoop._json_or_error(resp, "test") == {"a": 1}


def test_fetch_recovery_data_calls_v2_cycle_endpoint():
    resp = _FakeResponse(status_code=200, json_data={"score_state": "SCORED"})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_recovery_data("tok", 42))
    assert result == {"score_state": "SCORED"}


def test_fetch_sleep_data_calls_v2_endpoint():
    resp = _FakeResponse(status_code=200, json_data={"cycle_id": 1})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_sleep_data("tok", "sleep-uuid"))
    assert result == {"cycle_id": 1}


def test_fetch_workout_data_uses_v2_for_non_numeric_id():
    resp = _FakeResponse(status_code=200, json_data={"id": "uuid-1"})
    with _patch_client(get=resp) as patched:
        result = _run_async(whoop.fetch_workout_data("tok", "uuid-1"))
    assert result == {"id": "uuid-1"}


def test_fetch_workout_data_uses_v1_for_numeric_id():
    resp = _FakeResponse(status_code=200, json_data={"id": 555})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_workout_data("tok", "555"))
    assert result == {"id": 555}


def test_fetch_profile_calls_v2_endpoint():
    resp = _FakeResponse(status_code=200, json_data={"first_name": "Ada"})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_profile("tok"))
    assert result == {"first_name": "Ada"}


def test_fetch_body_measurement_calls_v2_endpoint():
    resp = _FakeResponse(status_code=200, json_data={"weight_kilograms": 70})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_body_measurement("tok"))
    assert result == {"weight_kilograms": 70}


# ---------------------------------------------------------------------------
# _v2_base
# ---------------------------------------------------------------------------


def test_v2_base_converts_v1_suffix(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_API_BASE", "https://api.prod.whoop.com/v1")
    assert whoop._v2_base() == "https://api.prod.whoop.com/v2"


def test_v2_base_converts_developer_v1_suffix(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_API_BASE", "https://api.prod.whoop.com/developer/v1")
    assert whoop._v2_base() == "https://api.prod.whoop.com/developer/v2"


def test_v2_base_keeps_developer_v2_as_is(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_API_BASE", "https://api.prod.whoop.com/developer/v2")
    assert whoop._v2_base() == "https://api.prod.whoop.com/developer/v2"


def test_v2_base_falls_back_for_unrecognized_shape(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_API_BASE", "https://weird.example.com/other")
    assert whoop._v2_base() == "https://api.prod.whoop.com/developer/v2"


# ---------------------------------------------------------------------------
# fetch_collection
# ---------------------------------------------------------------------------


def test_fetch_collection_single_page():
    resp = _FakeResponse(status_code=200, json_data={"records": [{"id": 1}, {"id": 2}]})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_collection("tok", "recovery", "start", "end"))
    assert result == [{"id": 1}, {"id": 2}]


def test_fetch_collection_paginates_until_no_next_token():
    responses = [
        _FakeResponse(status_code=200, json_data={"records": [{"id": 1}], "next_token": "page-2"}),
        _FakeResponse(status_code=200, json_data={"records": [{"id": 2}]}),
    ]
    calls = {"n": 0}

    def _get(_url, _kwargs):
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    with _patch_client(get=_get):
        result = _run_async(whoop.fetch_collection("tok", "activity/sleep"))
    assert result == [{"id": 1}, {"id": 2}]
    assert calls["n"] == 2


def test_fetch_collection_raises_on_error_status():
    resp = _FakeResponse(status_code=500, text="server error")
    with _patch_client(get=resp):
        with pytest.raises(HTTPException):
            _run_async(whoop.fetch_collection("tok", "recovery"))


def test_fetch_collection_ignores_non_list_records():
    resp = _FakeResponse(status_code=200, json_data={"records": "not-a-list"})
    with _patch_client(get=resp):
        result = _run_async(whoop.fetch_collection("tok", "recovery"))
    assert result == []


# ---------------------------------------------------------------------------
# hr_zone_pct_from_whoop_zone_millis
# ---------------------------------------------------------------------------


def test_hr_zone_pct_returns_none_tuple_for_empty_or_zero_total():
    assert whoop.hr_zone_pct_from_whoop_zone_millis(None) == (None, None, None, None, None)
    assert whoop.hr_zone_pct_from_whoop_zone_millis({}) == (None, None, None, None, None)


def test_hr_zone_pct_folds_zone_zero_into_zone_one_and_sums_to_100():
    zones = {
        "zone_zero_milli": 60_000,
        "zone_one_milli": 60_000,
        "zone_two_milli": 120_000,
        "zone_three_milli": 60_000,
        "zone_four_milli": 60_000,
        "zone_five_milli": 60_000,
    }
    pcts = whoop.hr_zone_pct_from_whoop_zone_millis(zones)
    assert sum(pcts) == 100
    assert all(p is not None for p in pcts)
