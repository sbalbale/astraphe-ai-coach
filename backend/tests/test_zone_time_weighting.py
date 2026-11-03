from app.services.hr_zones import HRZone, compute_zone_distribution


def _zones():
    return [HRZone(zone=1, min_bpm=0, max_bpm=120, name="Z1"), HRZone(zone=2, min_bpm=120, max_bpm=999, name="Z2")]


def test_samples_count_one_second_each_without_time_stream():
    dist = compute_zone_distribution([100, 100, 130, 130], _zones())
    assert dist == {"Z1": 50.0, "Z2": 50.0}


def test_irregular_samples_are_weighted_by_time():
    # Two Z1 samples 1 s apart, then one Z2 sample held for 8 s (smart recording).
    dist = compute_zone_distribution([100, 100, 130, 130], _zones(), time_stream=[0, 1, 2, 10])
    assert dist["Z2"] > 80


def test_pauses_are_capped():
    # A 10 minute auto-pause after the Z1 sample doesn't count as 10 minutes in Z1.
    dist = compute_zone_distribution([100, 130, 130], _zones(), time_stream=[0, 600, 601])
    assert dist["Z1"] < 95


def test_mismatched_time_stream_falls_back_to_counts():
    dist = compute_zone_distribution([100, 130], _zones(), time_stream=[0])
    assert dist == {"Z1": 50.0, "Z2": 50.0}


def test_zone1_midpoint_never_below_resting_hr():
    from app.services.algorithms import compute_hrss_from_zones

    hrss = compute_hrss_from_zones({1: 60.0}, max_hr=190, resting_hr=65, threshold_hr=170, hr_zone_method="max_hr")
    assert hrss >= 0
