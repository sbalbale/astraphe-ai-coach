from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.services import weight as w


class _Q:
    """Chainable fake over an in-memory table, honouring eq filters, insert/update/upsert/delete."""

    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload, self.single = db, name, {}, "select", None, False

    def select(self, *_a, **_k):
        return self

    def eq(self, f, v):
        self.filters[f] = v
        return self

    def __getattr__(self, _a):  # gte / is_ / order / limit / like ...
        return lambda *a, **k: self

    def maybe_single(self):
        self.single = True
        return self

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def upsert(self, p, **_k):
        self.op, self.payload = "upsert", p
        return self

    def delete(self):
        self.op = "delete"
        return self

    def _match(self, r):
        return all(str(r.get(f)) == str(v) for f, v in self.filters.items())

    def execute(self):
        rows = self.db.rows.setdefault(self.name, [])
        self.db.calls.append((self.name, self.op, self.payload))
        if self.op == "insert":
            row = {"id": f"new-{len(rows)}", **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[row])
        if self.op == "upsert":
            for p in self.payload if isinstance(self.payload, list) else [self.payload]:
                rows.append(dict(p))
            return SimpleNamespace(data=[])
        if self.op == "update":
            for r in rows:
                if self._match(r):
                    r.update(self.payload)
            return SimpleNamespace(data=[])
        if self.op == "delete":
            self.db.rows[self.name] = [r for r in rows if not self._match(r)]
            return SimpleNamespace(data=[])
        hits = [r for r in rows if self._match(r)]
        return SimpleNamespace(data=(hits[0] if hits else None) if self.single else hits)


class _Db:
    def __init__(self, **rows):
        self.rows, self.calls = {k: list(v) for k, v in rows.items()}, []

    def table(self, name):
        return _Q(self, name)


# ---- daily value ---------------------------------------------------------------


def test_pick_daily_prefers_manual_then_latest_and_skips_deleted():
    rows = [
        {"weight_kg": 80, "source": "garmin", "measured_at": "2026-11-08T12:00:00Z"},
        {"weight_kg": 81, "source": "garmin", "measured_at": "2026-11-08T13:00:00Z"},
        {"weight_kg": 79, "source": "manual", "measured_at": "2026-11-08T07:00:00Z", "deleted_at": "x"},
    ]
    assert w.pick_daily(rows)["weight_kg"] == 81
    rows[2]["deleted_at"] = None
    assert w.pick_daily(rows)["weight_kg"] == 79
    assert w.pick_daily([]) is None


def test_refresh_daily_weight_sets_and_clears():
    db = _Db(
        weigh_ins=[{"athlete_id": "a", "date": "2026-11-08", "weight_kg": 80.0, "source": "garmin", "measured_at": "t"}],
        biometrics=[{"athlete_id": "a", "date": "2026-11-08", "weight_kg": 70.0, "metric_sources": {"weight_kg": "whoop", "hrv_rmssd": "garmin"}}],
    )
    assert w.refresh_daily_weight(db, "a", date(2026, 11, 8)) == 80.0
    upsert = [c for c in db.calls if c[1] == "upsert"][0][2]
    assert upsert["weight_kg"] == 80.0 and upsert["metric_sources"] == {"weight_kg": "garmin", "hrv_rmssd": "garmin"}

    db = _Db(weigh_ins=[], biometrics=[{"athlete_id": "a", "date": "2026-11-08", "weight_kg": 70.0, "metric_sources": {"weight_kg": "manual"}}])
    assert w.refresh_daily_weight(db, "a", date(2026, 11, 8)) is None
    assert db.rows["biometrics"][0]["weight_kg"] is None
    assert db.rows["biometrics"][0]["metric_sources"] == {}


# ---- logging / delete ------------------------------------------------------------


def test_log_today_is_timestamped_earlier_day_is_not():
    now = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)  # 08:00 local at UTC-5
    with patch.object(w, "_offset_min", return_value=-300), patch.object(w, "refresh_daily_weight") as refresh:
        db = _Db()
        today = w.log_weigh_in(db, "a", 82.5, None, now=now)
        earlier = w.log_weigh_in(db, "a", 82.9, date(2026, 11, 8), now=now)
    assert today["date"] == "2026-11-09" and today["time_known"] is True and today["source"] == "manual"
    assert today["measured_at"] == now.isoformat()
    assert earlier["time_known"] is False and earlier["measured_at"] == "2026-11-08T17:00:00+00:00"
    assert today["external_id"].startswith("app:") and today["external_id"] != earlier["external_id"]
    assert refresh.call_count == 2


def test_set_deleted_soft_deletes_and_restores():
    db = _Db(weigh_ins=[{"id": "x", "athlete_id": "a", "date": "2026-11-08", "weight_kg": 80, "source": "manual", "measured_at": "t"}])
    with patch.object(w, "refresh_daily_weight") as refresh:
        assert w.set_deleted(db, "a", "x", True)["id"] == "x"
        assert db.rows["weigh_ins"][0]["deleted_at"]
        w.set_deleted(db, "a", "x", False)
        assert db.rows["weigh_ins"][0]["deleted_at"] is None
        assert w.set_deleted(db, "a", "missing", True) is None
    assert refresh.call_count == 2


# ---- Garmin ----------------------------------------------------------------------

GARMIN = {
    "dailyWeightSummaries": [
        {
            "summaryDate": "2026-09-01",
            "allWeightMetrics": [
                {"samplePk": 1788305029159, "date": 1788290622006, "calendarDate": "2026-09-01", "weight": 82779.0,
                 "bodyFat": 14.2, "sourceType": "INDEX_SCALE", "timestampGMT": 1788305022006},
                {"samplePk": 2, "calendarDate": "2026-09-01", "weight": 5000.0, "timestampGMT": 1788305022006},  # 5 kg: bad
                {"samplePk": None, "weight": 80000.0},
            ],
        }
    ]
}


def test_parse_garmin_weigh_ins():
    [r] = w.parse_garmin_weigh_ins(GARMIN)
    assert r["weight_kg"] == 82.78 and r["body_fat_pct"] == 14.2 and r["external_id"] == "1788305029159"
    assert r["date"] == "2026-09-01" and r["measured_at"].startswith("2026-09-01T23:23:42")
    assert w.parse_garmin_weigh_ins(None) == [] and w.parse_garmin_weigh_ins({}) == []


def test_save_garmin_weigh_ins_replaces_daily_copy_and_refreshes():
    db = _Db(weigh_ins=[{"athlete_id": "a", "source": "garmin", "date": "2026-09-01", "external_id": "daily:2026-09-01"}])
    with patch.object(w, "refresh_daily_weight") as refresh:
        assert w.save_garmin_weigh_ins(db, "a", w.parse_garmin_weigh_ins(GARMIN)) == 1
    upsert = [c for c in db.calls if c[1] == "upsert"][0][2]
    assert "deleted_at" not in upsert[0]  # a re-sync never restores a deleted weigh-in
    assert ("weigh_ins", "delete", None) in db.calls
    refresh.assert_called_once_with(db, "a", date(2026, 9, 1))
    assert w.save_garmin_weigh_ins(db, "a", []) == 0


# ---- router -----------------------------------------------------------------------


def _client():
    app.dependency_overrides[get_current_athlete] = lambda: "a"
    app.dependency_overrides[get_user_db] = lambda: _Db()
    return TestClient(app)


def test_router_validation_and_not_found():
    try:
        with patch("app.routers.weight.athlete_local_date", return_value=date(2026, 11, 9)), _client() as c:
            assert c.post("/v1/weight", json={"weight_kg": 5}).status_code == 422
            assert c.post("/v1/weight", json={"weight_kg": 80, "date": "2026-11-10"}).status_code == 400
            assert c.delete("/v1/weight/missing").status_code == 404
            with patch.object(w, "log_weigh_in", return_value={"id": "n"}) as log:
                res = c.post("/v1/weight", json={"weight_kg": 80.456, "date": "2026-11-08"})
            assert res.status_code == 200 and log.call_args.args[2] == 80.46
            with patch.object(w, "set_goal") as goal:
                assert c.put("/v1/weight/goal", json={"goal_weight_kg": None}).json()["goal_weight_kg"] is None
            goal.assert_called_once()
    finally:
        app.dependency_overrides = {}


# ---- resting HR source (profile) ------------------------------------------------------


def test_normalize_profile_resting_hr_source():
    from app.services.athlete_profile import normalize_profile_update as norm

    assert norm({"resting_hr": 48})["resting_hr_source"] == "manual"
    assert norm({"resting_hr": 48, "resting_hr_source": "measured"}) == {"resting_hr_source": "measured"}
    assert norm({"resting_hr": None}) == {}


def test_refresh_measured_resting_hr():
    from app.services.hr_anchors import refresh_measured_resting_hr

    rows = [{"athlete_id": "a", "resting_hr": v} for v in (50, 52, 51, None)]
    db = _Db(biometrics=rows, athletes=[{"id": "a"}])
    assert refresh_measured_resting_hr(db, "a", date(2026, 11, 9)) == 51
    assert db.rows["athletes"][0] == {"id": "a", "resting_hr": 51, "resting_hr_source": "measured"}
    assert refresh_measured_resting_hr(_Db(biometrics=[{"resting_hr": 50}]), "a", date(2026, 11, 9)) is None
