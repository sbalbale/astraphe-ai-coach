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
        self._neq: dict = {}
        self._range: dict = {}
        self._single = False
        self._update_payload: dict | None = None
        self._insert_payload: dict | None = None
        self._delete = False

    def select(self, *_a, **_k):
        return self

    def delete(self):
        self._delete = True
        return self

    def lt(self, field, value):
        self._range[(field, "lt")] = value
        return self

    def gt(self, field, value):
        self._range[(field, "gt")] = value
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def neq(self, field, value):
        self._neq[field] = value
        return self

    def limit(self, _n):
        return self

    def gte(self, field, value):
        self._range[(field, "gte")] = value
        return self

    def lte(self, field, value):
        self._range[(field, "lte")] = value
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

    @staticmethod
    def _value(row, field):
        if "->>" in field:
            col, key = field.split("->>", 1)
            v = (row.get(col) or {}).get(key)
            return None if v is None else str(v)
        return row.get(field)

    def _matches(self, row):
        if any(self._value(row, f) != v for f, v in self._filters.items()):
            return False
        if any(self._value(row, f) == v for f, v in self._neq.items()):
            return False
        for (field, op), v in self._range.items():
            rv = row.get(field)
            if rv is None:
                continue  # rows in these tests often omit started_at
            if (op == "gte" and str(rv) < v) or (op == "lte" and str(rv) > v):
                return False
            if (op == "gt" and str(rv) <= v) or (op == "lt" and str(rv) >= v):
                return False
        return True

    def execute(self):
        from types import SimpleNamespace

        if self._delete:
            gone = [r for r in self.db.rows if self._matches(r)]
            self.db.rows[:] = [r for r in self.db.rows if not self._matches(r)]
            return SimpleNamespace(data=gone)

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

        matches = [r for r in self.db.rows if self._matches(r)]
        if self._single:
            return SimpleNamespace(data=matches[0] if matches else None)
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
    # SOURCE_PRIORITY (post-Garmin-integration) = [garmin, whoop, intervals_icu,
    # strava, healthkit, manual] -- whoop now outranks strava, so the existing
    # whoop-primary row is left as-is rather than being demoted to strava.
    assert row["primary_source"] == "whoop"


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


def test_exact_external_id_match_updates_edited_whoop_workout():
    """An edited WHOOP workout (new start, very different duration) finds its own row."""
    existing = {
        "id": "w1", "athlete_id": "athlete-1", "source": "whoop", "external_id": "abc",
        "sport": "run", "primary_source": "whoop", "duration_seconds": 3600, "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "whoop", "ride", _now(), 600, external_id="abc"
    )
    assert created is False
    assert row["id"] == "w1"


def test_external_id_merged_into_source_ids_is_found():
    existing = {
        "id": "w1", "athlete_id": "athlete-1", "source": "garmin", "sport": "run",
        "primary_source": "garmin", "duration_seconds": 3600,
        "source_ids": {"intervals_icu": "i42"},
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "intervals_icu", "run", _now(), 100, external_id="i42"
    )
    assert created is False
    assert row["id"] == "w1"


def test_same_source_different_external_id_is_not_merged():
    existing = {
        "id": "w1", "athlete_id": "athlete-1", "source": "whoop", "external_id": "first",
        "sport": "run", "primary_source": "whoop", "duration_seconds": 1800, "source_ids": {},
    }
    db = _CanonicalDb(rows=[existing])
    _row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "whoop", "run", _now(), 1800, external_id="second"
    )
    assert created is True


def test_cross_sport_match_from_other_source():
    """WHOOP calls it 'other', Garmin calls it 'run': same session, merge."""
    existing = {
        "id": "w1", "athlete_id": "athlete-1", "source": "garmin", "sport": "run",
        "primary_source": "garmin", "duration_seconds": 1800, "source_ids": {},
        "started_at": _now().isoformat(),
    }
    db = _CanonicalDb(rows=[existing])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "whoop", "other", _now(), 1850, external_id="wh1"
    )
    assert created is False
    assert row["id"] == "w1"
    assert row["source_ids"]["whoop"] == "wh1"
    assert row["primary_source"] == "garmin"


def test_cross_sport_match_picks_the_closest_row():
    """With two candidates the nearest start/duration wins, not query order (review F7)."""
    far = {
        "id": "w-far", "athlete_id": "athlete-1", "source": "garmin", "sport": "run",
        "primary_source": "garmin", "duration_seconds": 1900, "source_ids": {},
        "started_at": "2026-05-20T10:02:30+00:00",
    }
    near = {
        "id": "w-near", "athlete_id": "athlete-1", "source": "strava", "sport": "bike",
        "primary_source": "strava", "duration_seconds": 1840, "source_ids": {},
        "started_at": "2026-05-20T10:00:20+00:00",
    }
    db = _CanonicalDb(rows=[far, near])
    row, created = processing._find_or_create_canonical_workout_sync(
        db, "athlete-1", "whoop", "other", _now(), 1850, external_id="wh9"
    )
    assert created is False
    assert row["id"] == "w-near"


def test_recorded_workout_replaces_overlapping_hr_detection():
    detected = {
        "id": "det-1", "athlete_id": "a1", "source": "hr_detected", "primary_source": "hr_detected",
        "sport": "other", "external_id": "a1:1", "duration_seconds": 2400,
        "started_at": "2026-05-20T10:02:00+00:00", "ended_at": "2026-05-20T10:42:00+00:00",
    }
    earlier = {**detected, "id": "det-0", "started_at": "2026-05-20T07:00:00+00:00", "ended_at": "2026-05-20T07:30:00+00:00"}
    db = _CanonicalDb(rows=[dict(detected), dict(earlier)])

    row, created = processing._find_or_create_canonical_workout_sync(
        db, "a1", "garmin", "run", _now(), 2700, external_id="g-1"
    )

    assert created is True and row["source"] == "garmin"
    assert [r["id"] for r in db.rows] == ["det-0", "new-workout-1"]  # only the overlapping one went


def test_hr_detection_does_not_remove_other_detections():
    detected = {
        "id": "det-1", "athlete_id": "a1", "source": "hr_detected", "sport": "other", "external_id": "a1:9",
        "duration_seconds": 2400, "started_at": "2026-05-20T10:30:00+00:00", "ended_at": "2026-05-20T11:10:00+00:00",
    }
    db = _CanonicalDb(rows=[dict(detected)])
    processing._find_or_create_canonical_workout_sync(db, "a1", "hr_detected", "other", _now(), 2400, external_id="a1:1")
    assert any(r["id"] == "det-1" for r in db.rows)
