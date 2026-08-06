from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import strava as strava_service


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# reset_rowing_intervals
# ---------------------------------------------------------------------------


def test_reset_rowing_intervals_noop_when_nothing_matches():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.not_.is_.return_value.in_.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    assert _run_async(strava_service.reset_rowing_intervals(db)) == 0


def test_reset_rowing_intervals_updates_matching_rows():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.not_.is_.return_value.in_.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "w1"}, {"id": "w2"}]
    )
    result = _run_async(strava_service.reset_rowing_intervals(db))
    assert result == 2
    db.table.return_value.update.assert_called_once()


# ---------------------------------------------------------------------------
# reprocess_rowing_intervals_from_stored_data
# ---------------------------------------------------------------------------


class _ReprocessQuery:
    def __init__(self, response):
        self._response = response

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, *_a, **_k):
        return self

    def execute(self):
        return self._response


def _reprocess_db(**overrides):
    responses = {
        "workouts": SimpleNamespace(data={"id": "w1", "athlete_id": "athlete-1", "sport": "row", "raw_strava_payload": {"laps": []}}),
        "athletes": SimpleNamespace(data={"max_hr": 190}),
        "activity_streams": SimpleNamespace(data=None),
        "activity_laps": SimpleNamespace(data=[]),
    }
    responses.update(overrides)
    db = MagicMock()
    db.table.side_effect = lambda name: _ReprocessQuery(responses.get(name, SimpleNamespace(data=None)))
    return db


def test_reprocess_rowing_intervals_skip_when_workout_missing():
    db = _reprocess_db(workouts=SimpleNamespace(data=None))
    status, msg = strava_service.reprocess_rowing_intervals_from_stored_data(db, "w1")
    assert status == "skip"
    assert "not found" in msg


def test_reprocess_rowing_intervals_skip_when_not_rowing():
    db = _reprocess_db(workouts=SimpleNamespace(data={"id": "w1", "sport": "run"}))
    status, msg = strava_service.reprocess_rowing_intervals_from_stored_data(db, "w1")
    assert status == "skip"
    assert "not row" in msg


def test_reprocess_rowing_intervals_skip_without_raw_payload():
    db = _reprocess_db(workouts=SimpleNamespace(data={"id": "w1", "sport": "row", "raw_strava_payload": None}))
    status, msg = strava_service.reprocess_rowing_intervals_from_stored_data(db, "w1")
    assert status == "skip"
    assert "raw_strava_payload" in msg


def test_reprocess_rowing_intervals_success():
    db = _reprocess_db()
    with patch.object(strava_service, "_load_cached_laps_for_workout", return_value=None):
        status, msg = strava_service.reprocess_rowing_intervals_from_stored_data(db, "w1")
    assert status == "ok"
    assert "source=" in msg


def test_reprocess_rowing_intervals_returns_error_on_exception():
    db = MagicMock()
    db.table.side_effect = RuntimeError("db exploded")
    status, msg = strava_service.reprocess_rowing_intervals_from_stored_data(db, "w1")
    assert status == "error"
    assert "db exploded" in msg


# ---------------------------------------------------------------------------
# refetch_workout_from_strava
# ---------------------------------------------------------------------------


class _RefetchQuery:
    def __init__(self, responses, table_name):
        self.responses = responses
        self.table_name = table_name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, *_a, **_k):
        return self

    def execute(self):
        return self.responses[self.table_name]


def _refetch_db(**overrides):
    responses = {
        "workouts": SimpleNamespace(data={"id": "w1", "strava_activity_id": 111}),
        "athletes": SimpleNamespace(data={"strava_athlete_id": 999}),
    }
    responses.update(overrides)
    db = MagicMock()
    db.table.side_effect = lambda name: _RefetchQuery(responses, name)
    return db


def test_refetch_workout_404_when_workout_missing():
    db = _refetch_db(workouts=SimpleNamespace(data=None))
    with pytest.raises(HTTPException) as exc_info:
        _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 404


def test_refetch_workout_400_without_strava_activity_id():
    db = _refetch_db(workouts=SimpleNamespace(data={"id": "w1", "strava_activity_id": None}))
    with pytest.raises(HTTPException) as exc_info:
        _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 400


def test_refetch_workout_400_without_linked_strava_athlete():
    db = _refetch_db(athletes=SimpleNamespace(data={"strava_athlete_id": None}))
    with pytest.raises(HTTPException) as exc_info:
        _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 400


def test_refetch_workout_503_without_valid_token():
    db = _refetch_db()
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 503


def test_refetch_workout_429_on_rate_limit():
    db = _refetch_db()
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service,
        "ingest_strava_activity",
        AsyncMock(side_effect=strava_service.StravaRateLimitError(retry_after=30)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 429


def test_refetch_workout_502_when_no_result():
    db = _refetch_db()
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "ingest_strava_activity", AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 502


def test_refetch_workout_success():
    db = _refetch_db(workouts=SimpleNamespace(data={"id": "w1", "strava_activity_id": 111, "title": "Ride"}))
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "ingest_strava_activity", AsyncMock(return_value={"id": "w1"})
    ), patch.object(strava_service, "_load_stored_streams_dict", return_value={"latlng": {"data": [[1, 2], [3, 4]]}}):
        result = _run_async(strava_service.refetch_workout_from_strava(db, "athlete-1", "w1"))

    assert result["status"] == "ok"
    assert result["has_latlng_stream"] is True


# ---------------------------------------------------------------------------
# hydrate_workout_streams
# ---------------------------------------------------------------------------


def _hydrate_db(**overrides):
    responses = {
        "workouts": SimpleNamespace(data={"id": "w1", "strava_activity_id": 111}),
        "athletes": SimpleNamespace(data={"max_hr": 190}),
    }
    responses.update(overrides)
    db = MagicMock()
    db.table.side_effect = lambda name: _RefetchQuery(responses, name)
    return db


def test_hydrate_workout_streams_404_when_missing():
    db = _hydrate_db(workouts=SimpleNamespace(data=None))
    with pytest.raises(HTTPException) as exc_info:
        _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 404


def test_hydrate_workout_streams_400_without_strava_id():
    db = _hydrate_db(workouts=SimpleNamespace(data={"id": "w1", "strava_activity_id": None}))
    with pytest.raises(HTTPException) as exc_info:
        _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 400


def test_hydrate_workout_streams_already_stored():
    db = _hydrate_db()
    with patch.object(strava_service, "_load_stored_streams_dict", return_value={"heartrate": {}}):
        result = _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))
    assert result == {"status": "already_stored"}


def test_hydrate_workout_streams_503_without_token():
    db = _hydrate_db()
    with patch.object(strava_service, "_load_stored_streams_dict", return_value={}), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))
    assert exc_info.value.status_code == 503


def test_hydrate_workout_streams_success_with_hr_zone_update():
    db = _hydrate_db()
    streams = {"heartrate": {"data": [140, 150, 160]}}
    with patch.object(strava_service, "_load_stored_streams_dict", return_value={}), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value="tok")
    ), patch.object(strava_service, "get_activity_streams", AsyncMock(return_value=streams)), patch.object(
        strava_service, "_upsert_activity_streams"
    ):
        result = _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))

    assert result["status"] == "hydrated"
    assert "heartrate" in result["stream_types"]


def test_hydrate_workout_streams_empty_when_no_streams_returned():
    db = _hydrate_db()
    with patch.object(strava_service, "_load_stored_streams_dict", return_value={}), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value="tok")
    ), patch.object(strava_service, "get_activity_streams", AsyncMock(return_value={})), patch.object(
        strava_service, "_upsert_activity_streams"
    ):
        result = _run_async(strava_service.hydrate_workout_streams(db, "athlete-1", "w1"))

    assert result["status"] == "empty"


# ---------------------------------------------------------------------------
# backfill_recent
# ---------------------------------------------------------------------------


def test_backfill_recent_swallows_token_list_failure(capsys):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")
    with patch("app.dependencies.get_admin_db", return_value=db):
        _run_async(strava_service.backfill_recent(hours=12))
    assert "failed to list Strava tokens" in capsys.readouterr().out


def test_backfill_recent_skips_rows_missing_ids(capsys):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[
            {"athlete_id": None, "external_user_id": "1"},
            {"athlete_id": "a1", "external_user_id": None},
            {"athlete_id": "a2", "external_user_id": "not-a-number"},
        ]
    )
    with patch("app.dependencies.get_admin_db", return_value=db):
        _run_async(strava_service.backfill_recent(hours=12))
    out = capsys.readouterr().out
    assert "skip athlete_id=a2" in out


def test_backfill_recent_ingests_for_valid_athletes():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "a1", "external_user_id": "999"}]
    )
    with patch("app.dependencies.get_admin_db", return_value=db), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value="tok")
    ), patch.object(strava_service, "backfill_historical_data", AsyncMock(return_value=3)) as mock_backfill:
        _run_async(strava_service.backfill_recent(hours=12))

    mock_backfill.assert_awaited_once()


def test_backfill_recent_swallows_per_athlete_error(capsys):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "a1", "external_user_id": "999"}]
    )
    with patch("app.dependencies.get_admin_db", return_value=db), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value="tok")
    ), patch.object(strava_service, "backfill_historical_data", AsyncMock(side_effect=RuntimeError("boom"))):
        _run_async(strava_service.backfill_recent(hours=12))
    assert "failed athlete_id=a1" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# backfill_historical_data
# ---------------------------------------------------------------------------


class _BackfillListResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or []
        self.headers = headers or {}

    def json(self):
        return self._json_data


class _BackfillAsyncClient:
    """Fakes httpx.AsyncClient for backfill_historical_data.

    The production code does ``async with httpx.AsyncClient(...) as client`` *inside*
    its polling loop, so a fresh instance is constructed on every page fetch. A plain
    per-instance call counter would therefore reset to 0 every iteration and keep
    re-serving ``pages[0]`` forever. ``counter`` is an external mutable ``[int]`` box
    shared across instances (via the lambda factory closure) so pagination position
    actually advances.
    """

    def __init__(self, *_a, pages=None, counter=None, **_k):
        self._pages = pages or []
        self._counter = counter if counter is not None else [0]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, *_a, **_k):
        idx = min(self._counter[0], len(self._pages) - 1)
        resp = self._pages[idx]
        self._counter[0] += 1
        return resp


def test_backfill_historical_data_ingests_and_stops_at_cutoff():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    old_activity = {"id": 1, "start_date": "2000-01-01T00:00:00Z"}
    recent_activity = {"id": 2, "start_date": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    page1 = _BackfillListResponse(json_data=[recent_activity, old_activity])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "ingest_strava_activity", AsyncMock()) as mock_ingest, patch.object(
        strava_service, "_finalize_strava_sync", AsyncMock()
    ) as mock_finalize, patch.object(strava_service.asyncio, "sleep", AsyncMock()):
        total = _run_async(
            strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30)
        )

    assert total == 1  # only the recent activity is ingested; old one hits the cutoff
    mock_ingest.assert_awaited_once()
    mock_finalize.assert_awaited_once()


def test_backfill_historical_data_skips_already_fetched_primary():
    activity = {"id": 1, "start_date": "2026-05-20T10:00:00Z"}
    page1 = _BackfillListResponse(json_data=[activity])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "w1"}
    )

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "ingest_strava_activity", AsyncMock()) as mock_ingest, patch.object(
        strava_service, "_finalize_strava_sync", AsyncMock()
    ), patch.object(strava_service.asyncio, "sleep", AsyncMock()):
        total = _run_async(
            strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30)
        )

    assert total == 0
    mock_ingest.assert_not_called()


def test_backfill_historical_data_empty_first_page_stops_immediately():
    db = MagicMock()
    page1 = _BackfillListResponse(json_data=[])

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()) as mock_finalize, patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0
    mock_finalize.assert_awaited_once()


def test_backfill_historical_data_uses_hours_window_when_set():
    db = MagicMock()
    page1 = _BackfillListResponse(json_data=[])

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()), patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ):
        total = _run_async(
            strava_service.backfill_historical_data("athlete-1", 999, "tok", db, hours=6)
        )

    assert total == 0


def test_backfill_historical_data_list_429_then_success():
    retry_resp = _BackfillListResponse(status_code=429)
    ok_resp = _BackfillListResponse(status_code=200, json_data=[])
    db = MagicMock()

    with patch.object(
        strava_service.httpx,
        "AsyncClient",
        lambda *a, **k: _BackfillAsyncClient(*a, pages=[retry_resp, ok_resp], **k),
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()), patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ) as mock_sleep:
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0
    mock_sleep.assert_awaited()  # slept once for the 429 backoff (plus the per-page pacing sleep)


def test_backfill_historical_data_list_error_status_breaks():
    error_resp = _BackfillListResponse(status_code=500)
    db = MagicMock()

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[error_resp], **k)
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()) as mock_finalize, patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0
    mock_finalize.assert_awaited_once()


def test_backfill_historical_data_activity_rate_limited_then_succeeds():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    activity = {"id": 1, "start_date": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    page1 = _BackfillListResponse(json_data=[activity])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )

    ingest_calls = {"n": 0}

    async def _fake_ingest(**_kwargs):
        ingest_calls["n"] += 1
        if ingest_calls["n"] == 1:
            raise strava_service.StravaRateLimitError(retry_after=1)
        return {"id": "w1"}

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "ingest_strava_activity", _fake_ingest), patch.object(
        strava_service, "_finalize_strava_sync", AsyncMock()
    ), patch.object(strava_service.asyncio, "sleep", AsyncMock()):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 1
    assert ingest_calls["n"] == 2


def test_backfill_historical_data_activity_exception_is_swallowed():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    activity = {"id": 1, "start_date": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    page1 = _BackfillListResponse(json_data=[activity])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(
        strava_service, "ingest_strava_activity", AsyncMock(side_effect=RuntimeError("boom"))
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()), patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0


def test_hydrate_streams_background_swallows_errors(capsys):
    with patch.object(
        strava_service, "hydrate_workout_streams", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        _run_async(strava_service._hydrate_streams_background(MagicMock(), "athlete-1", "w1"))

    assert "strava.hydrate_bg" in capsys.readouterr().out


def test_backfill_historical_data_skips_activity_with_no_id():
    activity = {"start_date": "2026-05-20T10:00:00Z"}  # no "id" key
    page1 = _BackfillListResponse(json_data=[activity])
    db = MagicMock()

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(strava_service, "ingest_strava_activity", AsyncMock()) as mock_ingest, patch.object(
        strava_service, "_finalize_strava_sync", AsyncMock()
    ), patch.object(strava_service.asyncio, "sleep", AsyncMock()):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0
    mock_ingest.assert_not_called()


def test_backfill_historical_data_paginates_to_next_page():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # A full page (== per_page=50) triggers fetching the next page, which is empty -> stop.
    page1_activities = [{"id": i, "start_date": recent} for i in range(50)]
    page1 = _BackfillListResponse(json_data=page1_activities)
    page2 = _BackfillListResponse(json_data=[])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    counter = [0]

    with patch.object(
        strava_service.httpx,
        "AsyncClient",
        lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1, page2], counter=counter, **k),
    ), patch.object(strava_service, "ingest_strava_activity", AsyncMock()) as mock_ingest, patch.object(
        strava_service, "_finalize_strava_sync", AsyncMock()
    ), patch.object(strava_service.asyncio, "sleep", AsyncMock()):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 50
    assert mock_ingest.await_count == 50


def test_backfill_historical_data_gives_up_after_repeated_activity_rate_limits(capsys):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    activity = {"id": 1, "start_date": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    page1 = _BackfillListResponse(json_data=[activity])
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )

    with patch.object(
        strava_service.httpx, "AsyncClient", lambda *a, **k: _BackfillAsyncClient(*a, pages=[page1], **k)
    ), patch.object(
        strava_service,
        "ingest_strava_activity",
        AsyncMock(side_effect=strava_service.StravaRateLimitError(retry_after=1)),
    ), patch.object(strava_service, "_finalize_strava_sync", AsyncMock()), patch.object(
        strava_service.asyncio, "sleep", AsyncMock()
    ):
        total = _run_async(strava_service.backfill_historical_data("athlete-1", 999, "tok", db, days=30))

    assert total == 0
    assert "Gave up activity 1 after" in capsys.readouterr().out


def test_backfill_recent_skips_athlete_without_valid_token():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "a1", "external_user_id": "999"}]
    )
    with patch("app.dependencies.get_admin_db", return_value=db), patch.object(
        strava_service, "get_valid_token", AsyncMock(return_value=None)
    ), patch.object(strava_service, "backfill_historical_data", AsyncMock()) as mock_backfill:
        _run_async(strava_service.backfill_recent(hours=12))

    mock_backfill.assert_not_called()
