from __future__ import annotations

from datetime import datetime, timezone

from app.services import processing


class _CanonicalQuery:
    """
    Chainable fake for db.table("workouts") supporting both query shapes used by
    _find_or_create_canonical_workout_sync: the exact strava_activity_id lookup
    (select/eq/eq/maybe_single) and the fuzzy time-window lookup (select/eq/eq/gte/lte).
    """

    def __init__(self, db: "_CanonicalDb"):
        self.db = db
        self._filters: dict = {}
        self._single = False
        self._update_payload: dict | None = None
        self._insert_payload: dict | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def gte(self, field, value):
        self._filters[f"{field}__gte"] = value
        return self

    def lte(self, field, value):
        self._filters[f"{field}__lte"] = value
        return self

    def maybe_single(self):
        self._single = True
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def execute(self):
        from types import SimpleNamespace

        if self._insert_payload is not None:
            row = {**self._insert_payload, "id": "new-workout-1"}
            self.db.rows.append(row)
            return SimpleNamespace(data=[row])

        if self._update_payload is not None:
            workout_id = self._filters.get("id")
            for row in self.db.rows:
                if row["id"] == workout_id:
                    row.update(self._update_payload)
                    return SimpleNamespace(data=[dict(row)])
            return SimpleNamespace(data=[])

        # Exact lookup: athlete_id + strava_activity_id, single row.
        if "strava_activity_id" in self._filters:
            matches = [
                r
                for r in self.db.rows
                if r.get("athlete_id") == self._filters.get("athlete_id")
                and r.get("strava_activity_id") == self._filters.get("strava_activity_id")
            ]
            data = matches[0] if matches else None
            return SimpleNamespace(data=data)

        # Fuzzy lookup: athlete_id + sport within a time window (window filtering
        # ignored here -- the caller's own duration-ratio matching does the real work).
        matches = [
            r
            for r in self.db.rows
            if r.get("athlete_id") == self._filters.get("athlete_id")
            and r.get("sport") == self._filters.get("sport")
        ]
        return SimpleNamespace(data=matches)


class _CanonicalDb:
    def __init__(self, rows=None):
        self.rows = rows or []

    def table(self, name):
        assert name == "workouts"
        return _CanonicalQuery(self)


def _now():
    return datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)


def test_creates_new_row_when_no_candidates():
    db = _CanonicalDb(rows=[])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "strava", "run", _now(), 1800, strava_activity_id=111
    )
    assert created is True
    assert row["sport"] == "run"
    assert row["source_ids"]["strava"] == ["111"]


def test_exact_strava_id_match_merges_and_elevates_primary_source():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "strava_activity_id": 111,
        "sport": "run",
        "source": "manual",
        "primary_source": "manual",
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "strava", "run", _now(), 1800, strava_activity_id=111
    )
    assert created is False
    assert row["primary_source"] == "strava"  # strava outranks manual
    assert row["source_ids"]["strava"] == ["111"]


def test_exact_match_preserves_whoop_source_id_from_original_row():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "strava_activity_id": 111,
        "sport": "run",
        "source": "whoop",
        "external_id": "whoop-ext-1",
        "primary_source": "whoop",
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "strava", "run", _now(), 1800, strava_activity_id=111
    )
    assert created is False
    assert row["source_ids"]["whoop"] == "whoop-ext-1"
    assert row["primary_source"] == "strava"  # strava outranks whoop


def test_fuzzy_match_within_duration_tolerance_merges():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "manual",
        "primary_source": "manual",
        "duration_seconds": 1800,
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "intervals_icu", "run", _now(), 1850, external_id="ext-1"
    )
    assert created is False
    assert row["id"] == "w1"
    assert row["source_ids"]["intervals_icu"] == "ext-1"


def test_fuzzy_match_outside_duration_tolerance_creates_new_row():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "manual",
        "duration_seconds": 1800,
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", _now(), 3600  # 2x duration, way outside 20% tolerance
    )
    assert created is True
    assert row["id"] != "w1"


def test_fuzzy_match_uses_wider_tolerance_for_whoop_vs_strava():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "whoop",
        "primary_source": "whoop",
        "duration_seconds": 1800,
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    # 30% off -- outside the normal 20% tolerance but inside WHOOP<->Strava's 35%.
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "strava", "run", _now(), 2340, strava_activity_id=222
    )
    assert created is False
    assert row["id"] == "w1"


def test_fuzzy_match_when_either_duration_is_zero():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "manual",
        "duration_seconds": 0,
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", _now(), 1800
    )
    assert created is False
    assert row["id"] == "w1"


def test_naive_started_at_is_treated_as_utc():
    db = _CanonicalDb(rows=[])
    naive_start = datetime(2026, 5, 20, 10, 0)  # no tzinfo
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", naive_start, 1800
    )
    assert created is True
    assert row["started_at"].endswith("+00:00")


def test_new_strava_activity_id_added_to_existing_matched_row_without_one():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "manual",
        "duration_seconds": 1800,
        "source_ids": {},
        "strava_activity_id": None,
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "strava", "run", _now(), 1800, strava_activity_id=333
    )
    assert created is False
    assert row["strava_activity_id"] == 333


def test_exact_match_does_not_downgrade_primary_source():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "strava_activity_id": 111,
        "sport": "run",
        "source": "whoop",
        "primary_source": "whoop",
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", _now(), 1800, strava_activity_id=111
    )
    assert created is False
    assert row["primary_source"] == "whoop"  # manual is lower priority; no downgrade


def test_fuzzy_match_does_not_downgrade_primary_source():
    existing = {
        "id": "w1",
        "athlete_id": "athlete-1",
        "sport": "run",
        "source": "strava",
        "primary_source": "strava",
        "duration_seconds": 1800,
        "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", _now(), 1800
    )
    assert created is False
    assert row["primary_source"] == "strava"  # manual doesn't outrank strava


def test_insert_new_row_without_external_id_or_strava_id():
    db = _CanonicalDb(rows=[])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "manual", "run", _now(), 1800
    )
    assert created is True
    assert "external_id" not in row
    assert "strava_activity_id" not in row
    assert row["source_ids"] == {}
