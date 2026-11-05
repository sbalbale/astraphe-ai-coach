"""Max HR estimated when an athlete hasn't set one (otherwise every HR-scored workout is TSS 0)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import hr_anchors


def test_age_estimate_is_tanaka():
    # Born 1972-06-12 -> 54 on 2026-11-05: 208 - 0.7 * 54 = 170.2
    assert hr_anchors.estimated_max_hr("1972-06-12", None, date(2026, 11, 5)) == 170


def test_a_higher_recorded_peak_wins_and_implausible_ones_are_ignored():
    assert hr_anchors.estimated_max_hr("1972-06-12", 184, date(2026, 11, 5)) == 184
    assert hr_anchors.estimated_max_hr("1972-06-12", 165, date(2026, 11, 5)) == 170
    assert hr_anchors.estimated_max_hr("1972-06-12", 250, date(2026, 11, 5)) == 170
    assert hr_anchors.estimated_max_hr(None, 184, date(2026, 11, 5)) == 184
    assert hr_anchors.estimated_max_hr(None, None, date(2026, 11, 5)) is None


class _Db:
    """athletes select -> `athlete`; workouts select -> `peak`; records athletes updates."""

    def __init__(self, athlete, peak=None):
        self.athlete, self.peak, self.updates = athlete, peak, []

    def table(self, name):
        db = self
        q = MagicMock()
        for m in ("select", "eq", "gte", "lte", "order", "limit", "maybe_single"):
            getattr(q, m).return_value = q
        if name == "athletes":
            q.execute.return_value = SimpleNamespace(data=self.athlete)

            def _update(payload):
                db.updates.append(payload)
                return q

            q.update.side_effect = _update
        else:
            q.execute.return_value = SimpleNamespace(data=[{"max_hr": self.peak}] if self.peak else [])
        return q


def test_missing_max_and_threshold_are_estimated_and_marked():
    """Production: an athlete with resting HR 46 and a 1972 birth date but no max / threshold HR
    had TSS 0 on 92 of 92 workouts."""
    db = _Db({"max_hr": None, "resting_hr": 46, "threshold_hr": None, "date_of_birth": "1972-06-12"}, peak=181)
    out = hr_anchors.ensure_hr_anchors(db, "a", today=date(2026, 11, 5))
    assert out["max_hr"] == 181 and out["max_hr_source"] == "estimated"
    assert out["threshold_hr"] == round((181 - 46) * 0.83 + 46) and out["threshold_hr_source"] == "estimated"
    assert db.updates == [out]


def test_an_estimate_rises_with_a_higher_recorded_peak_but_a_manual_max_never_changes():
    db = _Db({"max_hr": 175, "max_hr_source": "estimated", "resting_hr": 46, "threshold_hr": 158, "date_of_birth": "1972-06-12"}, peak=186)
    assert hr_anchors.ensure_hr_anchors(db, "a", today=date(2026, 11, 5)) == {"max_hr": 186, "max_hr_source": "estimated"}
    manual = _Db({"max_hr": 175, "max_hr_source": "manual", "resting_hr": 46, "threshold_hr": 158, "date_of_birth": "1972-06-12"}, peak=190)
    assert hr_anchors.ensure_hr_anchors(manual, "a", today=date(2026, 11, 5)) == {}
    assert manual.updates == []
