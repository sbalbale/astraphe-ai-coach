import pytest

from app.services.hr_zones import (
    athlete_dict_with_hr_zones,
    canonical_hr_zone_method,
    classify_hr,
    compute_hr_zones,
    compute_zone_distribution,
    get_athlete_zones,
    optional_canonical_hr_zone_method,
    profile_hr_zones_payload,
)


def test_canonical_hr_zone_method_rejects_blank():
    with pytest.raises(ValueError):
        canonical_hr_zone_method("  ")


def test_optional_canonical_hr_zone_method_none_and_blank():
    assert optional_canonical_hr_zone_method(None) is None
    assert optional_canonical_hr_zone_method("  ") is None
    assert optional_canonical_hr_zone_method("hrr") == "hrr"


def test_lthr_preference_falls_back_to_auto_when_threshold_missing():
    zr = compute_hr_zones(max_hr=190, resting_hr=50, threshold_hr=None, hr_zone_method="lthr")
    assert zr is not None
    assert zr.method == "hrr"  # falls through to automatic priority chain


def test_hrr_preference_falls_back_to_auto_when_missing_inputs():
    zr = compute_hr_zones(max_hr=190, resting_hr=None, threshold_hr=165, threshold_hr_source="manual", hr_zone_method="hrr")
    assert zr is not None
    assert zr.method == "lthr"


def test_max_hr_preference_falls_back_to_auto_when_zero():
    zr = compute_hr_zones(max_hr=0, resting_hr=50, threshold_hr=165, threshold_hr_source="manual", hr_zone_method="max_hr")
    assert zr is not None
    assert zr.method == "lthr"


def test_invalid_hr_zone_method_string_is_ignored():
    zr = compute_hr_zones(max_hr=190, resting_hr=50, threshold_hr=None, hr_zone_method="not-a-method")
    assert zr is not None
    assert zr.method == "hrr"


def test_classify_hr_returns_none_when_out_of_range():
    zr = compute_hr_zones(190, 50, 165, "manual")
    assert classify_hr(-5, zr) is None


def test_profile_hr_zones_payload_present():
    payload = profile_hr_zones_payload(190, 50, 165, "manual")
    assert payload["method"] == "lthr"
    assert len(payload["zones"]) == 5


def test_athlete_dict_with_hr_zones_attaches_computed_block():
    row = {"id": "athlete-1", "max_hr": 190, "resting_hr": 50, "threshold_hr": 165, "threshold_hr_source": "manual"}
    out = athlete_dict_with_hr_zones(row)
    assert out["id"] == "athlete-1"
    assert out["hr_zones"]["method"] == "lthr"


def test_get_athlete_zones_defaults_to_lthr_170_when_no_data():
    zones = get_athlete_zones({})
    assert len(zones) == 5
    assert zones[0].zone == 1


def test_compute_zone_distribution_empty_stream():
    zones = get_athlete_zones({"max_hr": 190})
    dist = compute_zone_distribution([], zones)
    assert all(v == 0.0 for v in dist.values())


def test_compute_zone_distribution_bucket_percentages():
    zones = get_athlete_zones({"max_hr": 190, "resting_hr": 50})
    stream = [zones[0].min_bpm] * 5 + [zones[0].max_bpm] * 5  # half in z1, half in z2
    dist = compute_zone_distribution(stream, zones)
    assert dist["Z1"] == 50.0
    assert dist["Z2"] == 50.0
