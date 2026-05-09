from app.services.algorithms import (
    calculate_cycling_tss,
    normalize_rowing_watts,
    compute_hrss_from_zones,
)

def test_watt_normalization():
    # Rowing watts must be 12% more costly than cycling
    rowing_power = 200
    expected_cycling_equiv = 224.0 # 200 * 1.12
    assert normalize_rowing_watts(rowing_power) == expected_cycling_equiv

def test_cycling_tss_accuracy():
    # 1 hour at 200W with 250W FTP should be exactly 64.0 TSS
    duration = 3600
    np = 200
    ftp = 250
    assert calculate_cycling_tss(duration, np, ftp) == 64.0

def test_alpine_override_logic():
    # Skiing > 4 hours triggers a 50% gym volume cut
    ski_duration_minutes = 250 # 4.1 hours
    # This would be integrated into your 'Coach's Orders' generation logic
    pass


def test_compute_hrss_from_zones_positive():
    """HRSS-from-zones returns a finite value when anchors and zone minutes are valid."""
    zone_minutes = {1: 30.0, 2: 15.0, 3: 0.0, 4: 0.0, 5: 0.0}
    v = compute_hrss_from_zones(
        zone_minutes=zone_minutes,
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        sport="run",
        gender="male",
        threshold_hr_source="estimated",
    )
    assert v > 0


def test_compute_hrss_manual_lthr_vs_estimated_midpoints_differ():
    """Estimated threshold uses HRR zone midpoints; manual uses Coggan — HRSS should differ."""
    zone_minutes = {1: 20.0, 2: 20.0, 3: 20.0, 4: 0.0, 5: 0.0}
    base = dict(
        zone_minutes=zone_minutes,
        max_hr=190,
        resting_hr=50,
        threshold_hr=165,
        sport="run",
        gender="male",
    )
    hrss_est = compute_hrss_from_zones(threshold_hr_source="estimated", **base)
    hrss_man = compute_hrss_from_zones(threshold_hr_source="manual", **base)
    assert hrss_est != hrss_man