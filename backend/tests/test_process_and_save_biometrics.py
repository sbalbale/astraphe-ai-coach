from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.biometrics import DailyBiometrics
from app.services import processing


class _BioQuery:
    def __init__(self, db: "_BioDb", table_name: str, response):
        self.db = db
        self.table_name = table_name
        self._response = response if response is not None else SimpleNamespace(data=None)

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.db.updates.setdefault(self.table_name, []).append(payload)
        return self

    def upsert(self, payload, **_k):
        self.db.upserts.setdefault(self.table_name, []).append(payload)
        return self

    def execute(self):
        return self._response


class _BioDb:
    """
    Queue-based fake: each call to db.table(name) pops the next queued response
    for that table name, matching the exact call order process_and_save_biometrics
    issues its queries in. Recorded updates/upserts are inspectable afterward.
    """

    def __init__(self, responses: dict[str, list]):
        self._queues = {k: list(v) for k, v in responses.items()}
        self.updates: dict[str, list] = {}
        self.upserts: dict[str, list] = {}

    def table(self, name):
        queue = self._queues.get(name, [])
        response = queue.pop(0) if queue else SimpleNamespace(data=None)
        return _BioQuery(self, name, response)


def _default_responses(**overrides) -> dict[str, list]:
    responses = {
        "sleep_periods": [SimpleNamespace(data=[])],
        "biometrics": [
            SimpleNamespace(data=None),  # prev day
            SimpleNamespace(data=[]),  # 42d history
            SimpleNamespace(data=None),  # existing today row
        ],
        "athletes": [
            SimpleNamespace(data={"max_hr": 190, "threshold_hr": 165}),  # fetched in parallel block
        ],
        "tss_history": [
            SimpleNamespace(data={"ctl": 40.0}),  # current ctl
            SimpleNamespace(data=[{"atl": 30.0}, {"atl": 35.0}]),  # 30d atl history
        ],
        "workouts": [SimpleNamespace(data=[])],
    }
    responses.update(overrides)
    return responses


def _payload(**overrides) -> DailyBiometrics:
    base = dict(date=date(2026, 5, 20), source="whoop")
    base.update(overrides)
    return DailyBiometrics(**base)


def test_process_and_save_biometrics_minimal_payload_upserts_row():
    db = _BioDb(_default_responses())
    processing.process_and_save_biometrics(_payload(), "athlete-1", db, skip_pmc_recalc=True)

    assert "biometrics" in db.upserts
    payload = db.upserts["biometrics"][0]
    assert payload["athlete_id"] == "athlete-1"
    assert payload["date"] == "2026-05-20"
    assert "athletes" in db.updates  # profile baseline update always happens


def test_process_and_save_biometrics_with_sleep_session_upserts_sleep_period():
    # sleep_periods is queried twice in this flow: once for the session upsert
    # (return value unused) and once for the aggregation select -- the queue
    # needs an entry for each call, in order.
    period_row = {
        "in_bed_min": 480,
        "duration_min": 420,
        "awake_pct": 12.5,
        "deep_pct": 20.0,
        "rem_pct": 25.0,
        "light_pct": 42.5,
        "started_at": "2026-05-19T22:00:00Z",
        "ended_at": "2026-05-20T06:00:00Z",
    }
    db = _BioDb(
        _default_responses(
            sleep_periods=[
                SimpleNamespace(data=None),  # upsert() return value, unused
                SimpleNamespace(data=[period_row]),  # aggregation select
            ]
        )
    )
    payload = _payload(
        sleep_bedtime=datetime(2026, 5, 19, 22, 0, tzinfo=timezone.utc),
        sleep_wakeup=datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc),
        sleep_score=85,
        sleep_deep_pct=20.0,
        sleep_rem_pct=25.0,
        sleep_light_pct=42.5,
        sleep_awake_pct=12.5,
    )
    processing.process_and_save_biometrics(payload, "athlete-1", db, skip_pmc_recalc=True)

    assert "sleep_periods" in db.upserts
    session = db.upserts["sleep_periods"][0]
    assert session["in_bed_min"] > 0
    bio_payload = db.upserts["biometrics"][0]
    assert bio_payload["sleep_score"] is not None
    # The aggregation loop actually ran over the queried period row.
    assert bio_payload["sleep_deep_pct"] == 20.0
    assert bio_payload["sleep_duration_min"] > 0


def test_process_and_save_biometrics_duration_only_backup_path():
    """No sleep_periods rows and no bedtime/wakeup -> uses payload.sleep_duration_min fallback."""
    db = _BioDb(_default_responses())
    payload = _payload(sleep_duration_min=420, sleep_awake_pct=10.0)
    processing.process_and_save_biometrics(payload, "athlete-1", db, skip_pmc_recalc=True)

    bio_payload = db.upserts["biometrics"][0]
    assert bio_payload["sleep_duration_min"] is not None


def test_process_and_save_biometrics_computes_recovery_score_when_hrv_and_rhr_present():
    db = _BioDb(_default_responses())
    payload = _payload(hrv_rmssd=55.0, resting_hr=48)
    processing.process_and_save_biometrics(payload, "athlete-1", db, skip_pmc_recalc=True)

    bio_payload = db.upserts["biometrics"][0]
    assert bio_payload["recovery_score"] is not None
    assert bio_payload["hrv_rmssd"] == 55.0


def test_process_and_save_biometrics_falls_back_to_existing_recovery_score_without_hrv():
    db = _BioDb(
        _default_responses(
            biometrics=[
                SimpleNamespace(data=None),
                SimpleNamespace(data=[]),
                SimpleNamespace(data={"recovery_score": 72}),  # existing row has a recovery score
            ]
        )
    )
    payload = _payload()  # no hrv_rmssd / resting_hr
    processing.process_and_save_biometrics(payload, "athlete-1", db, skip_pmc_recalc=True)

    bio_payload = db.upserts["biometrics"][0]
    assert bio_payload["recovery_score"] == 72


def test_process_and_save_biometrics_estimates_threshold_hr_when_missing(monkeypatch):
    db = _BioDb(
        _default_responses(
            athletes=[SimpleNamespace(data={"max_hr": 190, "threshold_hr": None})],
        )
    )
    processing.process_and_save_biometrics(_payload(resting_hr=48), "athlete-1", db, skip_pmc_recalc=True)

    profile_update = db.updates["athletes"][0]
    assert profile_update.get("threshold_hr_source") == "estimated"


def test_process_and_save_biometrics_uses_history_baselines_when_present():
    db = _BioDb(
        _default_responses(
            biometrics=[
                SimpleNamespace(data={"sleep_debt_min": 30.0, "strain_score": 40}),  # prev day
                SimpleNamespace(
                    data=[{"resting_hr": 50, "hrv_rmssd": 60.0}, {"resting_hr": 48, "hrv_rmssd": 62.0}]
                ),
                SimpleNamespace(data=None),
            ]
        )
    )
    processing.process_and_save_biometrics(
        _payload(hrv_rmssd=58.0, resting_hr=49), "athlete-1", db, skip_pmc_recalc=True
    )

    assert "biometrics" in db.upserts  # completes without error using history-derived baselines


def test_process_and_save_biometrics_triggers_pmc_recalc_when_not_skipped():
    db = _BioDb(_default_responses())
    with patch.object(processing, "recalculate_tss_history", MagicMock()) as mock_recalc:
        processing.process_and_save_biometrics(_payload(), "athlete-1", db, skip_pmc_recalc=False)

    mock_recalc.assert_called_once_with("athlete-1", db)
