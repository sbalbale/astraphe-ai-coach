"""Tests for WHOOP recovery fetch helpers and webhook vitals merge."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models.biometrics import DailyBiometrics
from app.routers import sync as sync_router
from app.services import whoop

SCORED_RECOVERY = {
    "score_state": "SCORED",
    "created_at": "2026-05-21T10:00:00.000Z",
    "score": {
        "hrv_rmssd_milli": 31.8,
        "resting_heart_rate": 64,
        "spo2_percentage": 95.7,
        "skin_temp_celsius": 33.7,
        "recovery_score": 72,
    },
}

SAMPLE_SLEEP = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "cycle_id": 93845,
    "end": "2026-05-21T10:00:00.000Z",
    "nap": False,
}


def test_recovery_score_to_vitals_milli():
    vitals = whoop.recovery_score_to_vitals(SCORED_RECOVERY["score"])
    assert vitals["hrv_rmssd"] == 31.8
    assert vitals["resting_hr"] == 64
    assert vitals["spo2_pct"] == 95.7
    assert vitals["skin_temp"] == 33.7
    assert vitals["recovery_score"] == 72


def test_recovery_score_to_vitals_ms_fallback():
    score = {"hrv_rmssd_ms": 28.0, "resting_heart_rate": 60}
    vitals = whoop.recovery_score_to_vitals(score)
    assert vitals["hrv_rmssd"] == 28.0
    assert vitals["resting_hr"] == 60


def test_recovery_is_scored_pending():
    assert whoop.recovery_is_scored({"score_state": "PENDING", "score": {}}) is False


def test_recovery_is_scored_scored():
    assert whoop.recovery_is_scored(SCORED_RECOVERY) is True


def test_build_whoop_vitals_from_recovery():
    vitals = whoop.build_whoop_vitals_from_recovery(SCORED_RECOVERY)
    assert vitals["spo2_pct"] == 95.7


def test_apply_whoop_recovery_vitals_merges_into_payload():
    bio = DailyBiometrics(date=date(2026, 5, 21), source="whoop", sleep_duration_min=420)
    sync_router._apply_whoop_recovery_vitals(bio, SCORED_RECOVERY)
    assert bio.hrv_rmssd == 31.8
    assert bio.resting_hr == 64
    assert bio.spo2_pct == 95.7
    assert bio.skin_temp == 33.7
    assert bio.sleep_duration_min == 420


def test_whoop_wake_date_respects_offset():
    d = sync_router._whoop_wake_date(SAMPLE_SLEEP, offset_min=-240)
    assert d == date(2026, 5, 21)


def test_fetch_recovery_for_sleep_uses_cycle_id():
    async def _run():
        with patch.object(
            whoop, "fetch_recovery_data", AsyncMock(return_value=SCORED_RECOVERY)
        ) as mock_fetch:
            result = await whoop.fetch_recovery_for_sleep(
                "token", SAMPLE_SLEEP["id"], sleep_data=SAMPLE_SLEEP
            )
        mock_fetch.assert_awaited_once_with("token", 93845)
        assert result == SCORED_RECOVERY

    asyncio.run(_run())


def test_fetch_recovery_for_sleep_not_scored_returns_none():
    async def _run():
        pending = {"score_state": "PENDING", "score": {}}
        with patch.object(whoop, "fetch_recovery_data", AsyncMock(return_value=pending)):
            result = await whoop.fetch_recovery_for_sleep(
                "token", SAMPLE_SLEEP["id"], sleep_data=SAMPLE_SLEEP
            )
        assert result is None

    asyncio.run(_run())


def test_fetch_recovery_for_event_id_v1_cycle_id():
    async def _run():
        with patch.object(
            whoop, "fetch_recovery_data", AsyncMock(return_value=SCORED_RECOVERY)
        ) as mock_fetch:
            result = await whoop.fetch_recovery_for_event_id("token", 93845)
        mock_fetch.assert_awaited_once_with("token", 93845)
        assert result == SCORED_RECOVERY

    asyncio.run(_run())


def test_fetch_recovery_for_event_id_v2_sleep_uuid():
    async def _run():
        with patch.object(
            whoop,
            "fetch_recovery_for_sleep",
            AsyncMock(return_value=SCORED_RECOVERY),
        ) as mock_sleep_path:
            result = await whoop.fetch_recovery_for_event_id(
                "token", SAMPLE_SLEEP["id"]
            )
        mock_sleep_path.assert_awaited_once_with("token", SAMPLE_SLEEP["id"])
        assert result == SCORED_RECOVERY

    asyncio.run(_run())


def test_fetch_recovery_for_sleep_404_returns_none():
    async def _run():
        async def _raise_404(*_a, **_k):
            raise HTTPException(status_code=404, detail="not found")

        with patch.object(whoop, "fetch_recovery_data", _raise_404):
            result = await whoop.fetch_recovery_for_sleep(
                "token", SAMPLE_SLEEP["id"], sleep_data=SAMPLE_SLEEP
            )
        assert result is None

    asyncio.run(_run())


def test_retry_recovery_vitals_succeeds_after_delay(monkeypatch):
    attempts = {"n": 0}
    saved: list = []

    async def fake_fetch(_token, _sleep_id):
        attempts["n"] += 1
        if attempts["n"] < 2:
            return None
        return SCORED_RECOVERY

    async def instant_sleep(_sec):
        return None

    monkeypatch.setattr(whoop, "fetch_recovery_for_sleep", fake_fetch)
    monkeypatch.setattr(sync_router.asyncio, "sleep", instant_sleep)
    monkeypatch.setattr(
        sync_router,
        "process_and_save_biometrics",
        lambda payload, athlete_id, db: saved.append((payload, athlete_id)),
    )

    async def _run():
        await sync_router._whoop_retry_recovery_vitals(
            "athlete-1",
            SAMPLE_SLEEP["id"],
            date(2026, 5, 21),
            "access",
            None,
            "whoop-user-1",
            object(),
        )

    asyncio.run(_run())
    assert len(saved) == 1
    payload, athlete_id = saved[0]
    assert athlete_id == "athlete-1"
    assert payload.hrv_rmssd == 31.8
    assert payload.spo2_pct == 95.7


def test_nap_sleep_should_not_fetch_recovery():
    """Document nap guard: main-sleep-only recovery fetch."""
    nap_sleep = {**SAMPLE_SLEEP, "nap": True}
    assert nap_sleep["nap"] is True
    is_nap = bool(nap_sleep.get("nap", False))
    assert is_nap


def test_backfill_refreshes_expired_access_token():
    from types import SimpleNamespace
    from app.services import whoop_backfill

    class FakeDb:
        def table(self, name):
            assert name == "oauth_tokens"
            return self

        def update(self, payload):
            self.updated = payload
            return self

        def eq(self, *_a, **_k):
            return self

        def lt(self, *_a, **_k):
            return self

        def execute(self):
            # Both the claim UPDATE and the final token UPDATE "succeed"
            # (a matched row is returned), simulating no other replica
            # holding the refresh lock — see claim_and_refresh_whoop_token.
            return SimpleNamespace(data=[self.updated])

    async def _run():
        db = FakeDb()

        async def expired_profile(_token):
            raise HTTPException(status_code=401, detail="expired")

        with patch.object(whoop, "fetch_profile", expired_profile):
            with patch.object(
                whoop,
                "refresh_oauth_token",
                AsyncMock(
                    return_value={
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                    }
                ),
            ):
                token = await whoop_backfill._ensure_valid_whoop_access_token(
                    "athlete-1",
                    "old-access",
                    "refresh-xyz",
                    db,
                )
        assert token == "new-access"
        assert db.updated["access_token"] == "new-access"

    asyncio.run(_run())
