import pytest

from app.services.hr_zones import (
    compute_hr_zones,
    classify_hr,
    profile_hr_zones_payload,
)


def test_manual_lthr_tier():
    zr = compute_hr_zones(
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        threshold_hr_source="manual",
    )
    assert zr is not None
    assert zr.method == "lthr"
    assert len(zr.zones) == 5
    assert zr.zones[4].zone == 5
    assert zr.zones[4].max_bpm == 999


def test_estimated_threshold_uses_hrr_when_max_rhr():
    zr = compute_hr_zones(
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        threshold_hr_source="estimated",
    )
    assert zr is not None
    assert zr.method == "hrr"
    assert len(zr.zones) == 5


def test_max_only_tier():
    zr = compute_hr_zones(
        max_hr=190,
        resting_hr=None,
        threshold_hr=None,
        threshold_hr_source=None,
    )
    assert zr is not None
    assert zr.method == "max_hr"
    assert len(zr.zones) == 5


def test_insufficient_data():
    assert compute_hr_zones(None, None, None, None) is None
    assert compute_hr_zones(0, 50, None, None) is None


def test_classify_hr():
    zr = compute_hr_zones(180, 50, 160, "manual")
    assert zr is not None
    mid = (zr.zones[1].min_bpm + zr.zones[1].max_bpm) // 2
    assert classify_hr(mid, zr) == 2


def test_profile_payload_empty():
    p = profile_hr_zones_payload(None, None, None, None)
    assert p["method"] is None
    assert p["zones"] == []


def test_lthr_vo2max_plus_zone_unbounded_sentinel():
    """Open-ended LTHR Z5 (VO2max+) uses max_bpm sentinel 999 for chart/midpoint handling."""
    zr = compute_hr_zones(200, 48, 165, "manual")
    assert zr is not None
    assert zr.zones[-1].zone == 5
    assert zr.zones[-1].max_bpm >= 999


def test_hrr_z1_starts_at_zero():
    zr = compute_hr_zones(190, 50, None, None)
    assert zr is not None
    assert zr.method == "hrr"
    assert zr.zones[0].min_bpm == 0


def test_explicit_hrr_overrides_auto_lthr_tier():
    """When preference is HRR, use Karvonen even if manual LTHR exists."""
    zr = compute_hr_zones(
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        threshold_hr_source="manual",
        hr_zone_method="hrr",
    )
    assert zr is not None
    assert zr.method == "hrr"
    assert zr.zones[0].min_bpm == 0


def test_explicit_lthr_uses_coggan_even_when_estimated():
    zr = compute_hr_zones(
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        threshold_hr_source="estimated",
        hr_zone_method="lthr",
    )
    assert zr is not None
    assert zr.method == "lthr"
    assert zr.zones[0].max_bpm == int(165 * 0.81)


def test_unified_hi_zone_short_labels_all_methods():
    expected = ("Recovery", "Endurance", "Tempo", "Threshold", "VO2max+")
    z_hrr = compute_hr_zones(190, 50, None, None)
    assert z_hrr and tuple(z.name for z in z_hrr.zones) == expected
    z_max = compute_hr_zones(190, None, None, None)
    assert z_max and tuple(z.name for z in z_max.zones) == expected
    z_lthr = compute_hr_zones(185, None, 160, "manual")
    assert z_lthr is not None
    assert z_lthr.method == "lthr"
    assert tuple(z.name for z in z_lthr.zones) == expected
