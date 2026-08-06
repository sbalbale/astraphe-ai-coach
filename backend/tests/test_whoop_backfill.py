from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import whoop_backfill


def _run_async(coro):
    return asyncio.run(coro)


def test_parse_dt_handles_zulu_suffix():
    dt = whoop_backfill._parse_dt("2026-05-20T10:00:00.000Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_pct_returns_none_for_missing_or_zero_total():
    assert whoop_backfill._pct(None, 100) is None
    assert whoop_backfill._pct(50, None) is None
    assert whoop_backfill._pct(50, 0) is None


def test_pct_computes_rounded_percentage():
    assert whoop_backfill._pct(25, 100) == 25.0
    assert whoop_backfill._pct(33.333, 100) == 33.3


class _TokenQuery:
    def __init__(self, row):
        self._row = row

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self._row)


def test_load_whoop_tokens_returns_none_when_no_row():
    db = MagicMock()
    db.table.return_value = _TokenQuery(None)

    result = whoop_backfill._load_whoop_tokens(db, "athlete-1")
    assert result == (None, None)


def test_load_whoop_tokens_returns_tokens():
    db = MagicMock()
    db.table.return_value = _TokenQuery({"access_token": "a", "refresh_token": "r"})

    result = whoop_backfill._load_whoop_tokens(db, "athlete-1")
    assert result == ("a", "r")


def test_ensure_valid_access_token_returns_existing_when_still_valid():
    db = MagicMock()
    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={})):
        result = _run_async(
            whoop_backfill._ensure_valid_whoop_access_token("athlete-1", "tok", "refresh", db)
        )
    assert result == "tok"


def test_ensure_valid_access_token_reraises_non_401_errors():
    db = MagicMock()
    err = HTTPException(status_code=500, detail="whoop down")
    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(side_effect=err)):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(whoop_backfill._ensure_valid_whoop_access_token("athlete-1", "tok", "refresh", db))
    assert exc_info.value.status_code == 500


def test_ensure_valid_access_token_raises_401_without_refresh_token():
    db = MagicMock()
    err = HTTPException(status_code=401, detail="expired")
    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(side_effect=err)):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(whoop_backfill._ensure_valid_whoop_access_token("athlete-1", "tok", None, db))
    assert exc_info.value.status_code == 401


def test_ensure_valid_access_token_refreshes_and_persists():
    db = MagicMock()
    err = HTTPException(status_code=401, detail="expired")
    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(side_effect=err)), patch.object(
        whoop_backfill.whoop,
        "refresh_oauth_token",
        AsyncMock(return_value={"access_token": "new-tok", "refresh_token": "new-refresh", "expires_in": 3600}),
    ):
        result = _run_async(
            whoop_backfill._ensure_valid_whoop_access_token("athlete-1", "old-tok", "old-refresh", db)
        )

    assert result == "new-tok"
    db.table.return_value.update.assert_called_once()


def test_ensure_valid_access_token_raises_502_when_refresh_has_no_access_token():
    db = MagicMock()
    err = HTTPException(status_code=401, detail="expired")
    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(side_effect=err)), patch.object(
        whoop_backfill.whoop, "refresh_oauth_token", AsyncMock(return_value={})
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(
                whoop_backfill._ensure_valid_whoop_access_token("athlete-1", "old-tok", "old-refresh", db)
            )
    assert exc_info.value.status_code == 502


def test_backfill_historical_data_swallows_impl_errors(capsys):
    with patch.object(
        whoop_backfill, "_backfill_historical_data_impl", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        _run_async(whoop_backfill.backfill_historical_data("athlete-1", "tok"))  # should not raise

    assert "FAILED athlete_id=athlete-1" in capsys.readouterr().out


def test_backfill_biometrics_only_delegates_without_workouts():
    with patch.object(whoop_backfill, "backfill_historical_data", AsyncMock()) as mock_bf:
        _run_async(whoop_backfill.backfill_biometrics_only("athlete-1", "tok", days=30))

    mock_bf.assert_awaited_once_with("athlete-1", "tok", None, 30, include_workouts=False)


def test_backfill_recent_swallows_token_listing_error(capsys):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")

    with patch.object(whoop_backfill, "get_admin_db", return_value=db):
        _run_async(whoop_backfill.backfill_recent(hours=12))  # should not raise

    assert "failed to list WHOOP tokens" in capsys.readouterr().out


def test_backfill_recent_swallows_per_athlete_error(capsys):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "w1", "access_token": "tok-1"}]
    )

    with patch.object(whoop_backfill, "get_admin_db", return_value=db), patch.object(
        whoop_backfill, "backfill_historical_data", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        _run_async(whoop_backfill.backfill_recent(hours=12))  # should not raise

    assert "failed athlete_id=w1" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _backfill_historical_data_impl — broad integration-style coverage
# ---------------------------------------------------------------------------


class _ImplQuery:
    """Generic chainable fake covering every table used in the impl function."""

    def __init__(self, db: "_ImplDb", table_name: str):
        self.db = db
        self.table_name = table_name
        self._single = False
        self._count_mode = False

    def select(self, *_a, count=None, **_k):
        if count:
            self._count_mode = True
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def update(self, payload):
        self.db.updates.setdefault(self.table_name, []).append(payload)
        return self

    def upsert(self, payload, **_k):
        self.db.upserts.setdefault(self.table_name, []).append(payload)
        return self

    def execute(self):
        if self.table_name == "athletes" and self._single:
            return SimpleNamespace(data={"timezone_offset_min": 0})
        if self.table_name == "biometrics" and self._count_mode:
            return SimpleNamespace(count=3)
        if self.table_name == "biometrics" and not self._count_mode:
            return SimpleNamespace(
                data=[
                    {"date": "2026-05-20", "hrv_rmssd": 55, "resting_hr": 48, "recovery_score": 70, "sleep_score": 80},
                    {"date": None},  # skipped: missing date
                ]
            )
        return SimpleNamespace(data=[])


class _ImplDb:
    def __init__(self):
        self.updates: dict[str, list[dict]] = {}
        self.upserts: dict[str, list[dict]] = {}

    def table(self, name):
        return _ImplQuery(self, name)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_backfill_historical_data_impl_covers_main_flow():
    now = datetime.now(timezone.utc)
    sleep_start = _iso(now)
    sleep_end = _iso(now)

    sleeps = [
        {
            "start": sleep_start,
            "end": sleep_end,
            "score_state": "SCORED",
            "cycle_id": "cyc-1",
            "id": "sleep-1",
            "nap": False,
            "score": {
                "stage_summary": {
                    "total_light_sleep_time_milli": 3_600_000,
                    "total_slow_wave_sleep_time_milli": 1_800_000,
                    "total_rem_sleep_time_milli": 1_800_000,
                    "total_awake_time_milli": 300_000,
                },
                "sleep_performance_percentage": 85,
            },
        },
        {"start": None},  # skipped: missing start
        {"start": sleep_start, "score_state": "PENDING_SCORE"},  # skipped: not scored
    ]

    recoveries = [
        {
            "cycle_id": "cyc-1",
            "score": {
                "hrv_rmssd_milli": 60,
                "resting_heart_rate": 50,
                "recovery_score": 75,
            },
        },
        {"cycle_id": "unknown-cycle", "created_at": None},  # skipped: no created_at fallback
    ]

    workouts = [
        {
            "start": sleep_start,
            "end": sleep_end,
            "v1_id": "w1",
            "sport_name": "Weightlifting",
            "score": {"zone_durations": {}, "average_heart_rate": 120, "max_heart_rate": 150, "distance_meter": 0},
        },
        {
            "start": sleep_start,
            "end": sleep_end,
            "id": "w2",
            "sport_name": "cycling",
            "score": {},
        },
        {"start": None},  # skipped: missing start/end
    ]

    async def _fake_fetch_collection(_token, kind, *_a, **_k):
        if kind == "activity/sleep":
            return sleeps
        if kind == "recovery":
            return recoveries
        if kind == "activity/workout":
            return workouts
        return []

    db = _ImplDb()

    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={
        "first_name": "Ada",
        "user_id": "whoop-user-1",
    })), patch.object(
        whoop_backfill.whoop,
        "fetch_body_measurement",
        AsyncMock(return_value={"weight_kilograms": 70.1234, "height_meters": 1.75, "max_heart_rate": 190}),
    ), patch.object(
        whoop_backfill.whoop, "fetch_collection", AsyncMock(side_effect=_fake_fetch_collection)
    ), patch.object(
        whoop_backfill.whoop, "recovery_is_scored", side_effect=lambda rec: "score" in rec
    ), patch.object(
        whoop_backfill.whoop, "hr_zone_pct_from_whoop_zone_millis", return_value=(10, 20, 30, 20, 20)
    ), patch.object(
        whoop_backfill, "process_and_save_biometrics", MagicMock()
    ) as mock_save_bio, patch.object(
        whoop_backfill, "process_and_save_workout", AsyncMock()
    ) as mock_save_workout, patch.object(
        whoop_backfill, "recalculate_tss_history", MagicMock()
    ) as mock_recalc, patch.object(
        whoop_backfill, "invalidate_context_cache", MagicMock()
    ) as mock_invalidate:
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "tok", db, days=30, include_workouts=True
            )
        )

    # Profile + measurements updated athlete + oauth token + biometrics upsert.
    assert db.updates["oauth_tokens"][0] == {"external_user_id": "whoop-user-1"}
    assert db.updates["athletes"][0]["display_name"] == "Ada"
    assert db.upserts["biometrics"][0]["weight_kg"] == 70.12

    # One valid sleep saved (2 skipped), one valid recovery saved (1 skipped).
    assert mock_save_bio.call_count >= 2  # sleep + recovery + readiness refresh row

    # Two workouts attempted (one skipped for missing start/end).
    assert mock_save_workout.await_count == 2
    saved_sports = {call.args[0].workout_type for call in mock_save_workout.await_args_list}
    assert saved_sports == {"strength", "cycling"}

    mock_recalc.assert_called_once_with("athlete-1", db)
    mock_invalidate.assert_called_once_with("athlete-1")


def test_backfill_historical_data_impl_continues_when_profile_fetch_fails(capsys):
    db = _ImplDb()

    # First fetch_profile call is the token-validity check (must succeed so we
    # reach the later profile-info fetch, which is the one wrapped in try/except).
    calls = {"n": 0}

    async def _fetch_profile(_token):
        calls["n"] += 1
        if calls["n"] == 1:
            return {}
        raise RuntimeError("whoop down")

    with patch.object(whoop_backfill.whoop, "fetch_profile", _fetch_profile), patch.object(
        whoop_backfill.whoop, "fetch_collection", AsyncMock(return_value=[])
    ), patch.object(whoop_backfill, "recalculate_tss_history", MagicMock()), patch.object(
        whoop_backfill, "invalidate_context_cache", MagicMock()
    ):
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "tok", db, days=30, include_workouts=False
            )
        )

    assert "Failed to update profile/measurements" in capsys.readouterr().out


def test_backfill_historical_data_impl_uses_provided_stored_tokens():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "stored-tok", "refresh_token": "stored-refresh"}
    )
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"timezone_offset_min": 0}
    )
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[], count=0
    )

    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={})) as mock_fetch_profile, patch.object(
        whoop_backfill.whoop, "fetch_body_measurement", AsyncMock(return_value={})
    ), patch.object(whoop_backfill.whoop, "fetch_collection", AsyncMock(return_value=[])), patch.object(
        whoop_backfill, "recalculate_tss_history", MagicMock()
    ), patch.object(whoop_backfill, "invalidate_context_cache", MagicMock()):
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "unused-tok", db, days=30, include_workouts=False
            )
        )

    # The stored token from oauth_tokens should be used, not the passed-in one.
    assert mock_fetch_profile.await_args_list[0].args[0] == "stored-tok"


def test_backfill_historical_data_impl_falls_back_when_timezone_fetch_fails():
    """Athlete-timezone lookup failure should default offset to 0 rather than raise."""

    class _FailingTzQuery(_ImplQuery):
        def execute(self):
            if self.table_name == "athletes" and self._single:
                raise RuntimeError("db down")
            return super().execute()

    class _FailingTzDb(_ImplDb):
        def table(self, name):
            return _FailingTzQuery(self, name)

    db = _FailingTzDb()
    now = datetime.now(timezone.utc)

    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={})), patch.object(
        whoop_backfill.whoop, "fetch_body_measurement", AsyncMock(return_value={})
    ), patch.object(whoop_backfill.whoop, "fetch_collection", AsyncMock(return_value=[])), patch.object(
        whoop_backfill, "recalculate_tss_history", MagicMock()
    ), patch.object(whoop_backfill, "invalidate_context_cache", MagicMock()):
        # Should not raise despite the timezone lookup failing.
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "tok", db, days=30, include_workouts=False
            )
        )


def test_backfill_historical_data_impl_normalizes_additional_sport_names():
    now = datetime.now(timezone.utc)
    sleep_start = _iso(now)

    workouts = [
        {"start": sleep_start, "end": sleep_start, "id": "w-run", "sport_name": "Treadmill Run", "score": {}},
        {"start": sleep_start, "end": sleep_start, "id": "w-row", "sport_name": "Rower", "score": {}},
        {"start": sleep_start, "end": sleep_start, "id": "w-mobility", "sport_name": "Stretching", "score": {}},
    ]

    async def _fake_fetch_collection(_token, kind, *_a, **_k):
        if kind == "activity/workout":
            return workouts
        return []

    db = _ImplDb()

    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={})), patch.object(
        whoop_backfill.whoop, "fetch_body_measurement", AsyncMock(return_value={})
    ), patch.object(
        whoop_backfill.whoop, "fetch_collection", AsyncMock(side_effect=_fake_fetch_collection)
    ), patch.object(
        whoop_backfill.whoop, "hr_zone_pct_from_whoop_zone_millis", return_value=(20, 20, 20, 20, 20)
    ), patch.object(
        whoop_backfill, "process_and_save_workout", AsyncMock()
    ) as mock_save_workout, patch.object(
        whoop_backfill, "recalculate_tss_history", MagicMock()
    ), patch.object(whoop_backfill, "invalidate_context_cache", MagicMock()):
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "tok", db, days=30, include_workouts=True
            )
        )

    saved_sports = {call.args[0].workout_type for call in mock_save_workout.await_args_list}
    assert saved_sports == {"run", "row", "mobility"}


def test_backfill_historical_data_impl_skip_and_exception_branches():
    now = datetime.now(timezone.utc)
    sleep_start = _iso(now)

    sleeps = [
        # Zero total sleep duration -> skipped.
        {
            "start": sleep_start,
            "end": sleep_start,
            "score_state": "SCORED",
            "id": "sleep-zero",
            "nap": True,  # also exercises the "nap -> don't record cycle_wake_dates" branch
            "cycle_id": "cyc-nap",
            "score": {"stage_summary": {}},
        },
        # Valid sleep that triggers an upsert exception (caught + logged).
        {
            "start": sleep_start,
            "end": sleep_start,
            "score_state": "SCORED",
            "id": "sleep-error",
            "nap": False,
            "cycle_id": "cyc-error",
            "score": {
                "stage_summary": {
                    "total_light_sleep_time_milli": 3_600_000,
                    "total_slow_wave_sleep_time_milli": 1_800_000,
                    "total_rem_sleep_time_milli": 1_800_000,
                },
                "sleep_performance_percentage": 80,
            },
        },
    ]
    recoveries = [
        # Unknown cycle_id and no created_at -> skipped.
        {"cycle_id": "unknown-cycle", "score": {"recovery_score": 1}},
        # Unknown cycle_id but has created_at -> falls back to created_at date, then errors on save.
        {
            "cycle_id": "another-unknown",
            "created_at": sleep_start,
            "score": {"recovery_score": 2},
        },
    ]
    workouts = [
        {
            "start": sleep_start,
            "end": sleep_start,
            "id": "w-error",
            "sport_name": "run",
            "score": {},
        }
    ]

    async def _fake_fetch_collection(_token, kind, *_a, **_k):
        if kind == "activity/sleep":
            return sleeps
        if kind == "recovery":
            return recoveries
        if kind == "activity/workout":
            return workouts
        return []

    db = _ImplDb()

    with patch.object(whoop_backfill.whoop, "fetch_profile", AsyncMock(return_value={})), patch.object(
        whoop_backfill.whoop, "fetch_body_measurement", AsyncMock(return_value={})
    ), patch.object(
        whoop_backfill.whoop, "fetch_collection", AsyncMock(side_effect=_fake_fetch_collection)
    ), patch.object(
        whoop_backfill.whoop, "recovery_is_scored", return_value=True
    ), patch.object(
        whoop_backfill.whoop, "hr_zone_pct_from_whoop_zone_millis", return_value=(20, 20, 20, 20, 20)
    ), patch.object(
        whoop_backfill, "process_and_save_biometrics", side_effect=RuntimeError("db down")
    ), patch.object(
        whoop_backfill, "process_and_save_workout", AsyncMock(side_effect=RuntimeError("db down"))
    ), patch.object(
        whoop_backfill, "recalculate_tss_history", MagicMock()
    ), patch.object(whoop_backfill, "invalidate_context_cache", MagicMock()):
        # Should complete without raising despite every save attempt failing.
        _run_async(
            whoop_backfill._backfill_historical_data_impl(
                "athlete-1", "tok", db, days=30, include_workouts=True
            )
        )
