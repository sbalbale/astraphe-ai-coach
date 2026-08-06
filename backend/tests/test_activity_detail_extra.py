from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.dependencies import get_user_db
from app.main import app
from app.routers import activity_detail


def _no_redis():
    return patch.object(activity_detail, "get_redis", return_value=None)


def test_hr_from_time_series_edge_cases():
    assert activity_detail._hr_from_time_series(None) == []
    assert activity_detail._hr_from_time_series("not-a-dict") == []
    assert activity_detail._hr_from_time_series({}) == []
    assert activity_detail._hr_from_time_series({"heartrate": "not-a-list"}) == []
    assert activity_detail._hr_from_time_series({"heartrate": [1, 2, 3]}) == [1, 2, 3]


def _seed_common(fake_db, test_athlete_id, workout_id):
    fake_db._table_seeds["activity_laps"] = [
        {"workout_id": workout_id, "athlete_id": test_athlete_id, "lap_index": 1}
    ]
    fake_db._table_seeds["athletes"] = [
        {
            "id": test_athlete_id,
            "lthr": None,
            "threshold_hr": 170,
            "max_hr": 190,
            "resting_hr": 50,
            "hr_zone_method": "lthr",
        }
    ]
    fake_db._table_seeds["workouts"] = [
        {
            "id": workout_id,
            "athlete_id": test_athlete_id,
            "sport": "run",
            "intervals": [{"lap": 1}],
            "intervals_source": "strava",
            "splits_metric": [],
            "duration_seconds": 1800,
            "hr_zone_1_pct": 10,
            "hr_zone_2_pct": 40,
            "hr_zone_3_pct": 30,
            "hr_zone_4_pct": 15,
            "hr_zone_5_pct": 5,
        }
    ]


def test_get_activity_detail_returns_cached_payload(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-cached"
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis(), patch.object(
        activity_detail, "_cache_get", AsyncMock(return_value={"streams": None, "laps": [], "intervals": {}, "zones": {}})
    ):
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/detail")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200


def test_get_activity_detail_computes_zones_from_stream(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-with-stream"
    _seed_common(fake_db, test_athlete_id, workout_id)
    fake_db._table_seeds["activity_streams"] = [
        {
            "time_series": {"heartrate": [140, 150, 160]},
            "storage_path": None,
            "resolution_seconds": 1,
            "created_at": "t",
        }
    ]
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis():
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/detail")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    body = res.json()
    assert body["streams"] is not None
    assert body["zones"]["source"] == "stream"
    assert body["intervals"]["source"] == "strava"


def test_get_activity_detail_falls_back_to_zone_summary_when_no_streams(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-no-stream"
    _seed_common(fake_db, test_athlete_id, workout_id)
    fake_db._table_seeds["activity_streams"] = []
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis():
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/detail")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    body = res.json()
    assert body["streams"] is None
    assert body["zones"]["source"] == "summary"
    assert body["zones"]["data_points"] == 1800


def test_get_streams_404_when_missing(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    fake_db._table_seeds["activity_streams"] = []
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis():
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/streams")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 404


def test_get_streams_returns_row_when_present(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    fake_db._table_seeds["activity_streams"] = [
        {"time_series": {"heartrate": [1, 2]}, "storage_path": None, "resolution_seconds": 1, "created_at": "t"}
    ]
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis():
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/streams")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json()["time_series"]["heartrate"] == [1, 2]


def test_get_laps_returns_seeded_rows(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    fake_db._table_seeds["activity_laps"] = [{"workout_id": workout_id, "lap_index": 1}]
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        res = coach_client.get(f"/v1/activities/{workout_id}/laps")
    finally:
        app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json() == [{"workout_id": workout_id, "lap_index": 1}]


def test_get_intervals_404_when_workout_missing(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-missing"
    fake_db._table_seeds["workouts"] = []
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        res = coach_client.get(f"/v1/activities/{workout_id}/intervals")
    finally:
        app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 404


def test_get_intervals_returns_payload(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    fake_db._table_seeds["workouts"] = [
        {"id": workout_id, "intervals": [{"a": 1}], "intervals_source": "strava", "splits_metric": [], "sport": "row"}
    ]
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        res = coach_client.get(f"/v1/activities/{workout_id}/intervals")
    finally:
        app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json()["sport"] == "row"


def test_hydrate_streams_delegates_and_invalidates_cache(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis(), patch(
        "app.services.strava.hydrate_workout_streams", AsyncMock(return_value={"status": "queued"})
    ) as mock_hydrate:
        try:
            res = coach_client.post(f"/v1/activities/{workout_id}/hydrate-streams")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json() == {"status": "queued"}
    mock_hydrate.assert_awaited_once()


def test_refetch_strava_delegates_and_invalidates_cache(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis(), patch(
        "app.services.strava.refetch_workout_from_strava", AsyncMock(return_value={"status": "refetching"})
    ) as mock_refetch:
        try:
            res = coach_client.post(f"/v1/activities/{workout_id}/refetch-strava")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json() == {"status": "refetching"}
    mock_refetch.assert_awaited_once()


def test_get_workout_zones_returns_cached(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis(), patch.object(activity_detail, "_cache_get", AsyncMock(return_value={"cached": True})):
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/zones")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert res.json() == {"cached": True}


def test_get_workout_zones_computes_when_uncached(coach_client, fake_db, test_athlete_id):
    workout_id = "workout-x"
    _seed_common(fake_db, test_athlete_id, workout_id)
    fake_db._table_seeds["activity_streams"] = []
    app.dependency_overrides[get_user_db] = lambda: fake_db
    with _no_redis():
        try:
            res = coach_client.get(f"/v1/activities/{workout_id}/zones")
        finally:
            app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 200
    assert "distribution" in res.json()
