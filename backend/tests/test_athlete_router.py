from __future__ import annotations

from datetime import date
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_admin_db, get_current_athlete, get_current_user_email, get_user_db
from app.main import app
from app.routers import athlete as athlete_router


def _run_async(coro):
    return asyncio.run(coro)


def _override(db, admin_db=None, email=None):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db
    app.dependency_overrides[get_current_user_email] = lambda: email
    if admin_db is not None:
        app.dependency_overrides[get_admin_db] = lambda: admin_db


def _teardown():
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# _calc_biometrics_streak_days
# ---------------------------------------------------------------------------


def test_streak_days_empty_rows():
    assert athlete_router._calc_biometrics_streak_days([]) == 0


def test_streak_days_all_unparseable():
    assert athlete_router._calc_biometrics_streak_days([{"date": None}, {}]) == 0


def test_streak_days_consecutive_dates():
    rows = [{"date": "2026-05-20"}, {"date": "2026-05-19"}, {"date": "2026-05-18"}]
    assert athlete_router._calc_biometrics_streak_days(rows) == 3


def test_streak_days_breaks_on_gap():
    rows = [{"date": "2026-05-20"}, {"date": "2026-05-18"}]
    assert athlete_router._calc_biometrics_streak_days(rows) == 1


def test_streak_days_dedupes_and_skips_bad_dates():
    rows = [{"date": "2026-05-20"}, {"date": "2026-05-20"}, {"date": "not-a-date"}, {"date": "2026-05-19"}]
    assert athlete_router._calc_biometrics_streak_days(rows) == 2


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------


def test_cache_get_returns_none_without_redis():
    with patch.object(athlete_router, "get_redis", return_value=None):
        assert _run_async(athlete_router._cache_get("k")) is None


def test_cache_get_returns_parsed_json():
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value='{"a": 1}')
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        assert _run_async(athlete_router._cache_get("k")) == {"a": 1}


def test_cache_get_returns_none_on_error():
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        assert _run_async(athlete_router._cache_get("k")) is None


def test_cache_set_noop_without_redis():
    with patch.object(athlete_router, "get_redis", return_value=None):
        _run_async(athlete_router._cache_set("k", {"a": 1}))  # no raise


def test_cache_set_writes_via_setex():
    fake_redis = MagicMock()
    fake_redis.setex = AsyncMock()
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        _run_async(athlete_router._cache_set("k", {"a": 1}))
    fake_redis.setex.assert_awaited_once()


def test_cache_set_swallows_errors():
    fake_redis = MagicMock()
    fake_redis.setex = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        _run_async(athlete_router._cache_set("k", {"a": 1}))  # no raise


def test_cache_del_noop_without_redis():
    with patch.object(athlete_router, "get_redis", return_value=None):
        _run_async(athlete_router._cache_del("k"))


def test_cache_del_deletes_and_swallows_errors():
    fake_redis = MagicMock()
    fake_redis.delete = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        _run_async(athlete_router._cache_del("k"))  # no raise


def test_cache_set_state_noop_without_redis():
    with patch.object(athlete_router, "get_redis", return_value=None):
        _run_async(athlete_router._cache_set_state("k", {}))


def test_cache_set_state_writes_via_setex():
    fake_redis = MagicMock()
    fake_redis.setex = AsyncMock()
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        _run_async(athlete_router._cache_set_state("k", {"a": 1}))
    fake_redis.setex.assert_awaited_once()


def test_increment_zones_version_noop_without_redis():
    with patch.object(athlete_router, "get_redis", return_value=None):
        _run_async(athlete_router._increment_zones_version("athlete-1"))


def test_increment_zones_version_increments_and_swallows_errors():
    fake_redis = MagicMock()
    fake_redis.incr = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(athlete_router, "get_redis", return_value=fake_redis):
        _run_async(athlete_router._increment_zones_version("athlete-1"))  # no raise


# ---------------------------------------------------------------------------
# /onboard
# ---------------------------------------------------------------------------


class _GenericQuery:
    def __init__(self, rows=None, count=None, fail=False):
        self._rows = rows if rows is not None else []
        self._count = count
        self.fail = fail
        self.last_update = None
        self.last_delete_called = False

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def upsert(self, *_a, **_k):
        return self

    def update(self, payload):
        self.last_update = payload
        return self

    def delete(self):
        self.last_delete_called = True
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("db exploded")
        return SimpleNamespace(data=self._rows, count=self._count)


class _AthleteDb:
    def __init__(self, table_data: dict | None = None):
        self._table_data = table_data or {}
        self.queries: dict[str, _GenericQuery] = {}

    def table(self, name):
        if name not in self.queries:
            spec = self._table_data.get(name, {})
            self.queries[name] = _GenericQuery(**spec) if spec else _GenericQuery()
        return self.queries[name]


def test_onboard_athlete_writes_no_sample_data():
    db = _AthleteDb()
    _override(db)
    with patch.object(athlete_router, "get_redis", return_value=None):
        try:
            with TestClient(app) as client:
                res = client.post("/v1/athlete/onboard")
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "biometrics" not in db.queries and "training_plans" not in db.queries


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


def test_get_athlete_metrics_maps_rows():
    rows = [{"date": "2026-05-20", "daily_tss": 80, "ctl": 50, "atl": 40, "tsb": 10}]
    db = _AthleteDb({"tss_history": {"rows": rows}})
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/athlete/metrics")
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["trainingLoadData"][0]["ctl"] == 50


# ---------------------------------------------------------------------------
# /profile GET
# ---------------------------------------------------------------------------


def test_get_athlete_profile_returns_cached_with_fresh_weight():
    db = _AthleteDb({"biometrics": {"rows": [{"weight_kg": 71.5}]}})
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value={"display_name": "Ada"})):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/profile")
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["latest_weight_kg"] == 71.5


def test_get_athlete_profile_404_when_missing():
    db = _AthleteDb({"athletes": {"rows": []}})
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value=None)):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/profile")
        finally:
            _teardown()

    assert res.status_code == 404


def test_get_athlete_profile_500_on_query_failure():
    db = _AthleteDb({"athletes": {"fail": True}})
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value=None)):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/profile")
        finally:
            _teardown()

    assert res.status_code == 500


def test_get_athlete_profile_success_populates_cache():
    athlete_row = {"id": "athlete-1", "ftp": 250, "max_hr": 190}
    db = _AthleteDb({"athletes": {"rows": athlete_row}, "biometrics": {"rows": [{"weight_kg": 70}]}})
    # maybe_single returns a single dict as `.data`, not a list — adjust query rows.
    db.table("athletes")._rows = athlete_row
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value=None)), patch.object(
        athlete_router, "_cache_set", AsyncMock()
    ) as mock_cache_set:
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/profile")
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["latest_weight_kg"] == 70
    mock_cache_set.assert_awaited_once()


# ---------------------------------------------------------------------------
# /zones GET / PUT
# ---------------------------------------------------------------------------


def test_get_zones_returns_cached():
    db = _AthleteDb()
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value={"zones": [], "anchors": {}})):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/zones")
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json() == {"zones": [], "anchors": {}}


def test_get_zones_computes_from_athlete_row():
    athlete_row = {"lthr": 165, "max_hr": 190, "resting_hr": 48, "hr_zone_method": "lthr"}
    db = _AthleteDb()
    db.table("athletes")._rows = athlete_row
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value=None)), patch.object(
        athlete_router, "_cache_set", AsyncMock()
    ):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/zones")
        finally:
            _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["anchors"]["lthr"] == 165
    assert len(body["zones"]) > 0


def test_update_zones_requires_valid_fields():
    db = _AthleteDb()
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.put("/v1/athlete/zones", json={})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_zones_success_invalidates_cache():
    db = _AthleteDb()
    db.table("athletes")._rows = [{"id": "athlete-1"}]
    _override(db)
    with patch.object(athlete_router, "_cache_del", AsyncMock()) as mock_del, patch.object(
        athlete_router, "_increment_zones_version", AsyncMock()
    ) as mock_incr:
        try:
            with TestClient(app) as client:
                res = client.put("/v1/athlete/zones", json={"max_hr": 190})
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["status"] == "updated"
    assert mock_del.await_count == 2
    mock_incr.assert_awaited_once()


def test_update_zones_403_when_rls_blocks():
    db = _AthleteDb()
    db.table("athletes")._rows = []
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.put("/v1/athlete/zones", json={"max_hr": 190})
    finally:
        _teardown()

    assert res.status_code == 403


def test_update_zones_500_on_db_error():
    db = _AthleteDb({"athletes": {"fail": True}})
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.put("/v1/athlete/zones", json={"max_hr": 190})
    finally:
        _teardown()

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# /profile PATCH
# ---------------------------------------------------------------------------


def _profile_db(update_rows=None, fresh_row=None):
    db = _AthleteDb()
    q = db.table("athletes")
    q._rows = update_rows if update_rows is not None else [{"id": "athlete-1"}]
    return db, q


def test_update_athlete_profile_requires_fields():
    db, _ = _profile_db()
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_athlete_profile_rejects_invalid_measurement_units():
    db, _ = _profile_db()
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={"measurement_units": "furlongs"})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_athlete_profile_rejects_invalid_time_format():
    db, _ = _profile_db()
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={"time_format": "meridian"})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_athlete_profile_rejects_invalid_gender():
    db, _ = _profile_db()
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={"gender": "unspecified"})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_athlete_profile_rejects_invalid_hr_zone_method():
    db, _ = _profile_db()
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={"hr_zone_method": "bogus"})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_athlete_profile_403_when_rls_blocks():
    db = _AthleteDb()
    db.table("athletes")._rows = []
    _override(db, email="a@example.com")
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/athlete/profile", json={"ftp_watts": 260})
    finally:
        _teardown()

    assert res.status_code == 403


def test_update_athlete_profile_success_normalizes_and_syncs_marketing():
    db = _AthleteDb()
    q = db.table("athletes")
    q._rows = [{"id": "athlete-1"}]

    # `.single()` fetch-after-update path needs its own row shape (`.data` = dict).
    def _execute_override():
        return SimpleNamespace(data={"id": "athlete-1", "ftp": 260, "privacy_settings": {"marketing": True}})

    _override(db, email="a@example.com")
    with patch.object(athlete_router, "_cache_del", AsyncMock()), patch.object(
        athlete_router, "_increment_zones_version", AsyncMock()
    ), patch.object(athlete_router, "sync_marketing_contact", AsyncMock()) as mock_sync, patch.object(
        q, "execute", side_effect=[SimpleNamespace(data=[{"id": "athlete-1"}]), _execute_override()]
    ):
        try:
            with TestClient(app) as client:
                res = client.patch(
                    "/v1/athlete/profile",
                    json={
                        "measurement_units": "METRIC",
                        "time_format": "12-hour",
                        "gender": "Female",
                        "hr_zone_method": "max_hr_percent",
                        "privacy_settings": {"marketing": True},
                    },
                )
        finally:
            _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["updated_fields"]["measurement_units"] == "metric"
    assert body["updated_fields"]["time_format"] == "12h"
    assert body["updated_fields"]["gender"] == "female"
    assert body["updated_fields"]["hr_zone_method"] == "max_hr"
    mock_sync.assert_awaited_once_with("a@example.com", True)


def test_update_athlete_profile_500_when_refetch_returns_empty():
    db = _AthleteDb()
    q = db.table("athletes")

    _override(db, email=None)
    with patch.object(
        q, "execute", side_effect=[SimpleNamespace(data=[{"id": "athlete-1"}]), SimpleNamespace(data=None)]
    ):
        try:
            with TestClient(app) as client:
                res = client.patch("/v1/athlete/profile", json={"ftp_watts": 250})
        finally:
            _teardown()

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /
# ---------------------------------------------------------------------------


def test_delete_athlete_account_404_when_missing():
    db = _AthleteDb({"athletes": {"rows": None}})
    admin_db = _AthleteDb()
    _override(db, admin_db=admin_db)
    try:
        with TestClient(app) as client:
            res = client.request("DELETE", "/v1/athlete")
    finally:
        _teardown()

    assert res.status_code == 404


class _StateQuery:
    """Chainable fake that returns different rows depending on the selected columns."""

    def __init__(self, response, by_columns=None):
        self._response = response
        self._by_columns = by_columns or {}

    def select(self, columns="*", *_a, **_k):
        # get_athlete_state runs its biometrics queries concurrently, so answer by
        # which columns were selected, not by call order.
        if columns in self._by_columns:
            self._response = self._by_columns[columns]
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return self._response


class _StateDb:
    def __init__(self, *, display_name="Ada", tss_row=None, bio_row=None, window_rows=None, hist_rows=None):
        self._display_name = display_name
        self._tss_row = tss_row or {}
        self._bio_row = bio_row or {}
        self._window_rows = window_rows or []
        self._hist_rows = hist_rows or []
        self._biometrics_call = 0

    def table(self, name):
        if name == "athletes":
            data = [{"display_name": self._display_name}] if self._display_name is not None else []
            return _StateQuery(SimpleNamespace(data=data))
        if name == "tss_history":
            data = [self._tss_row] if self._tss_row else []
            return _StateQuery(SimpleNamespace(data=data))
        if name == "biometrics":
            return _StateQuery(
                SimpleNamespace(data=[]),
                by_columns={
                    "*": SimpleNamespace(data=[self._bio_row] if self._bio_row else []),
                    "date,hrv_rmssd,resting_hr": SimpleNamespace(data=self._window_rows),
                    "date": SimpleNamespace(data=self._hist_rows),
                },
            )
        raise AssertionError(f"unexpected table {name}")


def test_get_athlete_state_404_when_athlete_missing():
    db = _StateDb(display_name=None)
    _override(db)
    with patch.object(athlete_router, "get_redis", return_value=None):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/state")
        finally:
            _teardown()

    assert res.status_code == 404


def test_get_athlete_state_computes_hrv_zscore_and_readiness():
    window_rows = [{"hrv_rmssd": v, "resting_hr": 50 - i} for i, v in enumerate([50, 52, 51, 53, 54, 55, 56, 60])]
    db = _StateDb(
        display_name="Ada",
        tss_row={"ctl": 60, "atl": 45, "tsb": 15},
        bio_row={
            "hrv_rmssd": 60,
            "resting_hr": 42,
            "sleep_duration_min": 420,
            "sleep_score": 85,
            "recovery_score": 80,
            "readiness_score": 88,
        },
        window_rows=window_rows,
        hist_rows=[{"date": "2026-05-20"}, {"date": "2026-05-19"}],
    )
    _override(db)
    with patch.object(athlete_router, "get_redis", return_value=None):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/state")
        finally:
            _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["ctl"] == 60
    assert body["days_on_platform"] == 2
    assert body["readiness_label"] == "Optimal"
    assert body["hrv_z"] is not None


def test_get_athlete_state_returns_cached():
    cached_state = {
        "athlete_id": "athlete-1",
        "display_name": "Ada",
        "date": "2026-08-05",
        "days_on_platform": 5,
        "ctl": 50.0,
        "atl": 40.0,
        "tsb": 10.0,
        "hrv_rmssd": 55.0,
        "hrv_delta_7d": 1.0,
        "resting_hr": 48,
        "sleep_hours": 7.5,
        "sleep_score": 85,
        "recovery_score": 78,
        "readiness_score": 80,
        "readiness_label": "Optimal",
        "readiness_recommendation": "Calculated by Astraphe Intelligence.",
    }
    db = _StateDb()
    _override(db)
    with patch.object(athlete_router, "_cache_get", AsyncMock(return_value=cached_state)):
        try:
            with TestClient(app) as client:
                res = client.get("/v1/athlete/state")
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["athlete_id"] == "athlete-1"


def test_delete_athlete_account_keeps_data_when_auth_delete_fails():
    """The auth user goes first (it cascades); if that fails nothing is deleted. (S-L3)"""
    db = _AthleteDb()
    db.table("athletes")._rows = {"user_id": "user-1"}
    admin_db = MagicMock()
    admin_db.auth.admin.delete_user.side_effect = RuntimeError("auth service down")

    _override(db, admin_db=admin_db)
    try:
        with patch("app.services.account_deletion.revoke_provider_grants", AsyncMock(return_value={})):
            with TestClient(app) as client:
                res = client.request("DELETE", "/v1/athlete")
    finally:
        _teardown()

    assert res.status_code == 500
    admin_db.table.return_value.delete.assert_not_called()


def test_delete_athlete_account_revokes_grants_then_deletes_auth_user():
    db = _AthleteDb()
    db.table("athletes")._rows = {"user_id": "user-1"}
    admin_db = MagicMock()
    admin_db.table.return_value.delete.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    revoke = AsyncMock(return_value={"strava": True})

    _override(db, admin_db=admin_db)
    try:
        with patch("app.services.account_deletion.revoke_provider_grants", revoke):
            with TestClient(app) as client:
                res = client.request("DELETE", "/v1/athlete")
    finally:
        _teardown()

    assert res.status_code == 200
    revoke.assert_awaited_once()
    admin_db.auth.admin.delete_user.assert_called_once_with("user-1")


# ---------------------------------------------------------------------------
# Manual weight entries become today's biometrics reading
# ---------------------------------------------------------------------------


class _WeightQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def __getattr__(self, name):
        if name in ("not_", "is_", "order", "limit", "maybe_single"):
            return lambda *a, **k: self
        raise AttributeError(name)

    @property
    def not_(self):
        return self

    def upsert(self, payload, on_conflict=None):
        self.db.upserts.append((self.table, payload, on_conflict))
        return self

    def execute(self):
        if self.table == "athletes":
            return SimpleNamespace(data={"timezone_offset_min": 0})
        if "date" in self.filters:
            return SimpleNamespace(data=self.db.today_rows)
        return SimpleNamespace(data=[{"weight_kg": self.db.latest}] if self.db.latest is not None else [])


class _WeightDb:
    def __init__(self, latest=None, today_rows=None):
        self.latest, self.today_rows, self.upserts = latest, today_rows or [], []

    def table(self, name):
        return _WeightQuery(self, name)


def test_manual_weight_recorded_when_it_differs_from_latest_reading():
    db = _WeightDb(latest=85.05, today_rows=[{"metric_sources": {"hrv_rmssd": "whoop", "weight_kg": "whoop"}}])
    assert athlete_router._record_manual_weight_sync(db, "athlete-1", 83.914) is True
    [(table, payload, conflict)] = db.upserts
    assert table == "biometrics" and conflict == "athlete_id,date"
    assert payload["weight_kg"] == 83.91
    assert payload["metric_sources"] == {"hrv_rmssd": "whoop", "weight_kg": "manual"}
    assert len(payload["date"]) == 10


def test_manual_weight_recorded_when_there_are_no_readings():
    db = _WeightDb(latest=None)
    assert athlete_router._record_manual_weight_sync(db, "athlete-1", 70.0) is True
    assert db.upserts[0][1]["metric_sources"] == {"weight_kg": "manual"}


def test_manual_weight_skipped_when_it_matches_latest_reading():
    db = _WeightDb(latest=83.91)
    assert athlete_router._record_manual_weight_sync(db, "athlete-1", 83.93) is False
    assert db.upserts == []


def test_changing_ftp_records_anchor_history_and_rescores_from_today():
    """FTP / threshold pace changes are dated: earlier workouts keep the values they were done
    at, and only workouts from today on are re-scored."""
    db = _AthleteDb()
    q = db.table("athletes")
    fresh = {"id": "athlete-1", "ftp_watts": 255, "threshold_pace": "8:00", "measurement_units": "imperial"}
    _override(db, email=None)
    admin = MagicMock()
    with patch.object(athlete_router, "_cache_del", AsyncMock()), patch.object(
        athlete_router, "_increment_zones_version", AsyncMock()
    ), patch.object(q, "execute", side_effect=[SimpleNamespace(data=[{"id": "athlete-1"}]), SimpleNamespace(data=fresh)]), patch.object(
        athlete_router, "get_admin_db", return_value=admin
    ), patch.object(athlete_router, "athlete_local_date", return_value=date(2026, 11, 10)), patch.object(
        athlete_router, "record_anchor_change"
    ) as record, patch.object(athlete_router, "spawn_background") as spawn, patch.object(
        athlete_router, "rescore_and_rebuild", MagicMock()
    ):
        try:
            with TestClient(app) as client:
                res = client.patch("/v1/athlete/profile", json={"ftp_watts": 255})
        finally:
            _teardown()

    assert res.status_code == 200
    record.assert_called_once_with(admin, "athlete-1", fresh, date(2026, 11, 10))
    spawn.assert_called_once()


def test_a_profile_change_without_anchors_leaves_history_alone():
    db = _AthleteDb()
    q = db.table("athletes")
    _override(db, email=None)
    with patch.object(athlete_router, "_cache_del", AsyncMock()), patch.object(
        athlete_router, "_increment_zones_version", AsyncMock()
    ), patch.object(q, "execute", side_effect=[SimpleNamespace(data=[{"id": "athlete-1"}]), SimpleNamespace(data={"id": "athlete-1"})]), patch.object(
        athlete_router, "record_anchor_change"
    ) as record:
        try:
            with TestClient(app) as client:
                res = client.patch("/v1/athlete/profile", json={"time_format": "24h"})
        finally:
            _teardown()
    assert res.status_code == 200
    record.assert_not_called()
