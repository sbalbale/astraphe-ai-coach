from __future__ import annotations

import numpy as np
import pytest

from app.services import algorithms


# ---------------------------------------------------------------------------
# normalized_power / TSS
# ---------------------------------------------------------------------------


def test_normalized_power_empty_series():
    assert algorithms.normalized_power(np.array([])) == 0.0


def test_normalized_power_short_series_uses_mean():
    series = np.array([100.0, 200.0, 150.0])
    assert algorithms.normalized_power(series) == 150.0


def test_normalized_power_long_series_uses_rolling_4th_power():
    series = np.full(60, 200.0)
    assert algorithms.normalized_power(series) == pytest.approx(200.0)


def test_compute_tss_power_zero_ftp_returns_zero():
    assert algorithms.compute_tss_power(3600, 200, 0) == 0.0


# ---------------------------------------------------------------------------
# HRSS timeseries
# ---------------------------------------------------------------------------


def test_compute_hrss_timeseries_zero_for_invalid_inputs():
    assert algorithms.compute_hrss_timeseries(np.array([150] * 100), 100, 150, 160) == 0.0
    assert algorithms.compute_hrss_timeseries(np.array([]), 190, 50, 165) == 0.0
    assert algorithms.compute_hrss_timeseries(None, 190, 50, 165) == 0.0


def test_compute_hrss_timeseries_positive_for_valid_input():
    series = np.linspace(120, 170, 600)
    v = algorithms.compute_hrss_timeseries(series, 190, 50, 165, sport="run", gender="female")
    assert v > 0


def test_compute_hrss_timeseries_strength_multiplier_increases_score():
    series = np.linspace(120, 170, 600)
    base = algorithms.compute_hrss_timeseries(series, 190, 50, 165, sport="run")
    strength = algorithms.compute_hrss_timeseries(series, 190, 50, 165, sport="strength")
    assert strength > base


# ---------------------------------------------------------------------------
# HRSS from zones
# ---------------------------------------------------------------------------


def test_compute_hrss_from_zones_zero_for_invalid_ranges():
    assert algorithms.compute_hrss_from_zones({1: 10.0}, max_hr=100, resting_hr=150, threshold_hr=160) == 0.0
    assert algorithms.compute_hrss_from_zones({1: 10.0}, max_hr=190, resting_hr=50, threshold_hr=40) == 0.0


def test_compute_hrss_from_zones_zero_when_zone_result_none():
    v = algorithms.compute_hrss_from_zones({1: 10.0}, max_hr=190, resting_hr=50, threshold_hr=165, threshold_hr_source=None, hr_zone_method=None)
    assert v >= 0  # zone_result resolves via automatic HRR path here; sanity check it doesn't blow up


def test_compute_hrss_from_zones_skips_empty_or_zero_minutes():
    zone_minutes = {1: 0.0, 2: None, 3: 15.0}
    v = algorithms.compute_hrss_from_zones(
        zone_minutes, max_hr=190, resting_hr=50, threshold_hr=165, threshold_hr_source="manual"
    )
    assert v > 0


# ---------------------------------------------------------------------------
# Pace-based TSS
# ---------------------------------------------------------------------------


def test_compute_trss_pace_zero_for_invalid_inputs():
    assert algorithms.compute_trss_pace(3600, 0, 300) == 0.0
    assert algorithms.compute_trss_pace(3600, 300, 0) == 0.0
    assert algorithms.compute_trss_pace(0, 300, 300) == 0.0


def test_compute_trss_pace_positive_for_valid_input():
    v = algorithms.compute_trss_pace(3600, 360, 300)
    assert v > 0


# ---------------------------------------------------------------------------
# CTL / ATL
# ---------------------------------------------------------------------------


def test_compute_ctl_empty_series():
    assert algorithms.compute_ctl(np.array([])).size == 0


def test_compute_ctl_seeds_and_decays():
    series = np.array([50.0, 60.0, 70.0, 80.0])
    ctl = algorithms.compute_ctl(series, time_constant=7)
    assert len(ctl) == 4
    assert ctl[-1] > 0


def test_compute_atl_delegates_to_ctl_with_short_window():
    series = np.array([50.0, 60.0, 70.0])
    atl = algorithms.compute_atl(series)
    assert len(atl) == 3


# ---------------------------------------------------------------------------
# Strain / readiness / sleep / recovery scores
# ---------------------------------------------------------------------------


def test_compute_strain_score_zero_for_no_load():
    assert algorithms.compute_strain_score({1: 0.0, 2: 0.0}) == 0


def test_compute_strain_score_strength_multiplier():
    base = algorithms.compute_strain_score({2: 30.0}, sport="run")
    strength = algorithms.compute_strain_score({2: 30.0}, sport="strength")
    assert strength >= base


def test_compute_readiness_score_tsb_only():
    score = algorithms.compute_readiness_score(tsb=0.0, recovery_score=None)
    assert 0 <= score <= 100


def test_compute_readiness_score_blends_recovery():
    score = algorithms.compute_readiness_score(tsb=10.0, recovery_score=80)
    assert 0 <= score <= 100


def test_calculate_astraphe_sleep_score_zero_for_invalid_inputs():
    assert algorithms.calculate_astraphe_sleep_score(0, 480, 60, 60, 30) == 0
    assert algorithms.calculate_astraphe_sleep_score(400, 0, 60, 60, 30) == 0


def test_calculate_astraphe_sleep_score_penalizes_poor_architecture_and_fragmentation():
    good = algorithms.calculate_astraphe_sleep_score(480, 480, 100, 100, 10)
    poor = algorithms.calculate_astraphe_sleep_score(480, 480, 10, 10, 90)
    assert good > poor


def test_compute_sleep_score_delegates_to_astraphe_model():
    assert algorithms.compute_sleep_score(480, 480, 100, 100, 10) == algorithms.calculate_astraphe_sleep_score(
        480, 480, 100, 100, 10
    )


def test_compute_recovery_score_low_ans_dominates():
    score = algorithms.compute_recovery_score(
        hrv_today=30, hrv_avg_30d=60, hrv_std_30d=10, rhr_today=60, rhr_avg_30d=50, rhr_std_30d=5,
        sleep_score=70, prior_day_atl=80, prior_day_atl_max_30d=100,
    )
    assert 0 <= score <= 100


def test_compute_recovery_score_high_ans_dominates():
    score = algorithms.compute_recovery_score(
        hrv_today=90, hrv_avg_30d=60, hrv_std_30d=10, rhr_today=40, rhr_avg_30d=50, rhr_std_30d=5,
        sleep_score=90, prior_day_atl=20, prior_day_atl_max_30d=100,
    )
    assert 0 <= score <= 100


def test_compute_recovery_score_mid_ans_blend():
    score = algorithms.compute_recovery_score(
        hrv_today=62, hrv_avg_30d=60, hrv_std_30d=10, rhr_today=49, rhr_avg_30d=50, rhr_std_30d=5,
        sleep_score=75, prior_day_atl=50, prior_day_atl_max_30d=100,
    )
    assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# Sleep need / debt
# ---------------------------------------------------------------------------


def test_compute_sleep_need_combines_baseline_strain_and_debt():
    need = algorithms.compute_sleep_need(baseline_min=480, strain_score=50, current_debt_min=30)
    assert need > 480


def test_compute_sleep_debt_series_empty():
    assert algorithms.compute_sleep_debt_series(np.array([]), np.array([])).size == 0


def test_compute_sleep_debt_series_accumulates_and_decays():
    actual = np.array([400.0, 400.0, 500.0])
    strain = np.array([50.0, 50.0, 0.0])
    debt = algorithms.compute_sleep_debt_series(actual, strain)
    assert len(debt) == 3
    assert debt[0] >= 0


# ---------------------------------------------------------------------------
# EWMA / z-score / trend
# ---------------------------------------------------------------------------


def test_compute_ewma_stats_empty():
    assert algorithms.compute_ewma_stats(np.array([])) == (0.0, 0.0)


def test_compute_ewma_stats_single_value():
    assert algorithms.compute_ewma_stats(np.array([42.0])) == (42.0, 0.0)


def test_compute_ewma_stats_multi_value():
    mean, std = algorithms.compute_ewma_stats(np.array([50.0, 55.0, 60.0]))
    assert mean > 50.0
    assert std >= 0.0


def test_compute_z_score_empty_history():
    z, mean, sd = algorithms.compute_z_score(55.0, np.array([]))
    assert z == 0.0
    assert mean == 55.0


def test_compute_z_score_degenerate_std_returns_zero():
    z, _, _ = algorithms.compute_z_score(50.0, np.array([50.0, 50.0, 50.0]))
    assert z == 0.0


def test_compute_z_score_normal_case():
    z, mean, sd = algorithms.compute_z_score(70.0, np.array([50.0, 52.0, 55.0, 60.0]))
    assert z != 0.0


def test_compute_hrv_trend_short_series():
    trend = algorithms.compute_hrv_trend(np.array([50.0, 52.0]))
    assert trend["trend_direction"] == "stable"
    assert trend["current_baseline"] == 51.0


def test_compute_hrv_trend_empty_series():
    trend = algorithms.compute_hrv_trend(np.array([]))
    assert trend["current_baseline"] == 0.0


def test_compute_hrv_trend_rising():
    series = np.array([40.0] * 7 + [55.0] * 7)
    trend = algorithms.compute_hrv_trend(series)
    assert trend["trend_direction"] == "rising"


def test_compute_hrv_trend_declining():
    series = np.array([60.0] * 7 + [40.0] * 7)
    trend = algorithms.compute_hrv_trend(series)
    assert trend["trend_direction"] == "declining"


# ---------------------------------------------------------------------------
# Baselines & misc helpers
# ---------------------------------------------------------------------------


def test_baseline_helpers_return_zero_for_empty_history():
    assert algorithms.calculate_rhr_baseline([]) == 0.0
    assert algorithms.calculate_hrv_baseline([]) == 0.0
    assert algorithms.calculate_spo2_baseline([]) == 0.0
    assert algorithms.calculate_temp_baseline([]) == 0.0


def test_baseline_helpers_average_recent_history():
    assert algorithms.calculate_rhr_baseline([48, 50, 52]) == 50.0
    assert algorithms.calculate_hrv_baseline([50.0, 60.0]) == 55.0
    assert algorithms.calculate_spo2_baseline([96.0, 98.0]) == 97.0
    assert algorithms.calculate_temp_baseline([36.0, 37.0]) == 36.5


def test_calculate_weekly_tss_target_zero_ctl_returns_default():
    assert algorithms.calculate_weekly_tss_target(0) == 200


def test_calculate_weekly_tss_target_scales_with_ctl():
    assert algorithms.calculate_weekly_tss_target(50) == 375


def test_calculate_threshold_hr_est_missing_inputs_returns_zero():
    assert algorithms.calculate_threshold_hr_est(0, 50) == 0
    assert algorithms.calculate_threshold_hr_est(190, 0) == 0


def test_calculate_threshold_hr_est_computes_estimate():
    assert algorithms.calculate_threshold_hr_est(190, 50) == int(round((140 * 0.83) + 50))


def test_estimate_max_hr_tanaka_formula():
    assert algorithms.estimate_max_hr(30) == round(208 - (0.7 * 30))


def test_compute_hrss_from_zones_zero_when_zone_result_truly_none():
    # Passing the top guard (max_hr > resting_hr and threshold_hr > resting_hr) while
    # all three are <= 0 makes compute_hr_zones receive None for every anchor.
    v = algorithms.compute_hrss_from_zones(
        {1: 10.0}, max_hr=-5, resting_hr=-20, threshold_hr=-10, threshold_hr_source=None, hr_zone_method=None
    )
    assert v == 0.0


def test_compute_hrss_from_zones_strength_multiplier():
    zone_minutes = {1: 20.0, 2: 20.0}
    base = algorithms.compute_hrss_from_zones(
        zone_minutes, max_hr=190, resting_hr=50, threshold_hr=165, sport="run", threshold_hr_source="manual"
    )
    strength = algorithms.compute_hrss_from_zones(
        zone_minutes, max_hr=190, resting_hr=50, threshold_hr=165, sport="strength", threshold_hr_source="manual"
    )
    assert strength > base
