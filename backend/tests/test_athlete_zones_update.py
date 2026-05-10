"""Unit tests for PUT /v1/athlete/zones payload → DB column mapping."""

from app.routers.athlete import _build_athlete_zones_update


def test_lthr_maps_to_threshold_hr_never_lthr_key():
    u = _build_athlete_zones_update({"lthr": 165})
    assert "lthr" not in u
    assert u["threshold_hr"] == 165
    assert u["threshold_hr_source"] == "manual"


def test_threshold_hr_alias_same_as_lthr():
    u = _build_athlete_zones_update({"threshold_hr": 160})
    assert "lthr" not in u
    assert u["threshold_hr"] == 160
    assert u["threshold_hr_source"] == "manual"


def test_method_maps_to_hr_zone_method():
    u = _build_athlete_zones_update({"method": "hrr"})
    assert u["hr_zone_method"] == "hrr"


def test_hr_zone_method_wins_over_method():
    u = _build_athlete_zones_update({"method": "hrr", "hr_zone_method": "lthr"})
    assert u["hr_zone_method"] == "lthr"


def test_max_hr_resting_hr_pass_through():
    u = _build_athlete_zones_update({"max_hr": 190, "resting_hr": 48})
    assert u["max_hr"] == 190
    assert u["resting_hr"] == 48


def test_empty_when_no_valid_fields():
    assert _build_athlete_zones_update({}) == {}
    assert _build_athlete_zones_update({"lthr": None, "method": None}) == {}


def test_lthr_zero_sets_threshold_no_manual_source():
    u = _build_athlete_zones_update({"lthr": 0})
    assert u["threshold_hr"] == 0
    assert "threshold_hr_source" not in u
