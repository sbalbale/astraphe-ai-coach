import math
import numpy as np
from typing import Dict, Any, List, Optional

# ==========================================
# CONSTANTS
# ==========================================

# Proprietary Strain weighting for HR zones
ZONE_STRAIN_COEFFICIENTS = {
    0: 0.0,    # Z0 Resting
    1: 0.5,    # Z1 Recovery
    2: 1.0,    # Z2 Aerobic
    3: 2.5,    # Z3 Tempo
    4: 5.0,    # Z4 Threshold
    5: 8.0,    # Z5 VO2max
}

# The absolute maximum theoretical strain (24 hours at pure Zone 5)
MAX_RAW_STRAIN_24H = 1440 * 8.0  # 11,520

# Multiplier to account for central nervous system fatigue in non-aerobic sports
NEUROMUSCULAR_MULTIPLIER = 1.7

# Sleep Debt model constants
DEFAULT_BASELINE_SLEEP_MIN = 480.0  # 8 hours
MAX_SLEEP_DEBT_MIN = 120.0          # 2 hours max physiological debt
MAX_STRAIN_SLEEP_TAX_MIN = 120.0    # 100 Strain = 2 extra hours of sleep need
SLEEP_DEBT_DECAY_RATE = 0.8         # Unpaid debt decays by 20% each day

# ==========================================
# CORE LOAD & TSS CALCULATIONS
# ==========================================


def normalized_power(power_series: np.ndarray) -> float:
    """
    Calculate Normalized Power from a 1-second power array.
    """
    if len(power_series) < 30:
        return float(np.mean(power_series)) if len(power_series) > 0 else 0.0

    # 30-second rolling average
    rolling_30s = np.convolve(power_series, np.ones(30)/30, mode='valid')
    # Raise to the 4th power, average, and take the 4th root
    return float(np.mean(rolling_30s ** 4) ** 0.25)

def compute_tss_power(duration_sec: int, np_watts: float, ftp: int) -> float:
    """
    Calculate Training Stress Score (TSS) for power-based activities.
    """
    if ftp <= 0:
        return 0.0
    intensity_factor = np_watts / ftp
    return (duration_sec * np_watts * intensity_factor) / (ftp * 3600) * 100

# ==========================================
# CONTINUOUS HEART RATE STRESS (HRSS)
# ==========================================

def compute_hrss_timeseries(
    hr_series: np.ndarray,
    max_hr: int,
    resting_hr: int,
    threshold_hr: int,
    sport: str = "other",
    gender: str = "male",
) -> float:
    """
    Calculates Heart Rate Stress Score (HRSS) continuously from a 1-second heart rate array.
    Uses Banister's TRIMP to exponentially weight stress against Lactate Threshold Heart Rate.
    """
    if max_hr <= resting_hr or threshold_hr <= resting_hr or hr_series is None or len(hr_series) == 0:
        return 0.0

    # Banister's constant (k) for the exponential lactate accumulation curve
    k = 1.92 if str(gender).lower() == "male" else 1.67

    # 1. Calculate Heart Rate Reserve (HRR) for every second
    hr_series_clipped = np.clip(hr_series, resting_hr, max_hr)
    hrr_series = (hr_series_clipped - resting_hr) / (max_hr - resting_hr)

    # 2. Calculate exponential TRIMP for the entire workout (dt = 1/60 minutes per second)
    dt = 1.0 / 60.0
    trimp_per_sec = dt * hrr_series * 0.64 * np.exp(k * hrr_series)
    total_trimp = float(np.sum(trimp_per_sec))

    # 3. Calculate the baseline: 1-hour TRIMP strictly at LTHR
    lthr_hrr = (threshold_hr - resting_hr) / (max_hr - resting_hr)
    lthr_trimp_1hr = 60.0 * lthr_hrr * 0.64 * math.exp(k * lthr_hrr)

    if lthr_trimp_1hr <= 0:
        return 0.0

    # 4. Normalize into the 100-point TSS scale
    hrss = (total_trimp / lthr_trimp_1hr) * 100.0

    if sport == "strength":
        hrss *= NEUROMUSCULAR_MULTIPLIER

    return round(float(hrss), 2)


def compute_hrss_from_zones(
    zone_minutes: Dict[int, float],
    max_hr: int,
    resting_hr: int,
    threshold_hr: int,
    sport: str = "other",
    gender: str = "male",
) -> float:
    """
    Estimates HRSS for historical workouts where only aggregated time-in-zone is available.
    Calculates Banister TRIMP using the mathematical midpoint of each zone.
    """
    if max_hr <= resting_hr or threshold_hr <= resting_hr:
        return 0.0

    k = 1.92 if str(gender).lower() == "male" else 1.67

    # Baseline: 1-hour TRIMP at LTHR
    lthr_hrr = (threshold_hr - resting_hr) / (max_hr - resting_hr)
    lthr_trimp_1hr = 60.0 * lthr_hrr * 0.64 * math.exp(k * lthr_hrr)
    if lthr_trimp_1hr <= 0:
        return 0.0

    # Mathematical midpoints for standard 5-zone models based on max HR percentages
    zone_midpoint_hr = {
        0: resting_hr,
        1: resting_hr + 0.60 * (max_hr - resting_hr),
        2: resting_hr + 0.70 * (max_hr - resting_hr),
        3: resting_hr + 0.80 * (max_hr - resting_hr),
        4: resting_hr + 0.90 * (max_hr - resting_hr),
        5: resting_hr + 0.95 * (max_hr - resting_hr),
    }

    total_trimp = 0.0
    for zone, minutes in (zone_minutes or {}).items():
        if not minutes or minutes <= 0:
            continue

        mid_hr = zone_midpoint_hr.get(int(zone), resting_hr)
        hrr = (mid_hr - resting_hr) / (max_hr - resting_hr)

        # Exponential TRIMP for this block of time
        zone_trimp = float(minutes) * float(hrr) * 0.64 * math.exp(k * float(hrr))
        total_trimp += zone_trimp

    hrss = (total_trimp / lthr_trimp_1hr) * 100.0

    if sport == "strength":
        hrss *= NEUROMUSCULAR_MULTIPLIER

    return round(float(hrss), 2)


# ==========================================
# PACE-BASED STRESS (tRSS / rTSS)
# ==========================================

def compute_trss_pace(
    duration_sec: int,
    avg_pace_sec_km: float,
    threshold_pace_sec_km: float,
) -> float:
    """
    Calculates Training Stress Score based on running pace (tRSS/rTSS).
    Unlike power or heart rate, pace is inversely proportional to speed,
    so the Intensity Factor (IF) ratio is inverted.
    """
    if threshold_pace_sec_km <= 0 or avg_pace_sec_km <= 0 or duration_sec <= 0:
        return 0.0

    # Intensity Factor (IF) = Threshold Pace / Actual Pace
    # e.g., Threshold is 300s/km (5:00/km), Actual is 360s/km (6:00/km) -> IF = 0.833
    intensity_factor = threshold_pace_sec_km / avg_pace_sec_km

    # TSS = Duration in hours * IF^2 * 100
    duration_hours = duration_sec / 3600.0
    trss = duration_hours * (intensity_factor ** 2) * 100.0

    return round(float(trss), 2)

def compute_ctl(tss_series: np.ndarray, time_constant: int = 42) -> np.ndarray:
    """
    Compute Chronic Training Load (CTL) fitness over a TSS history array.
    Includes average-seeding to solve the "Cold Start" problem.
    Ordered oldest-first.
    """
    if len(tss_series) == 0:
        return np.array([])
        
    alpha = 1 - np.exp(-1 / time_constant)
    ctl = np.zeros(len(tss_series))
    
    # SEEDING STRATEGY: Calculate the average daily TSS of the available 
    # history (up to the time constant) to establish a steady-state baseline.
    initial_window = tss_series[:time_constant]
    historical_average = np.mean(initial_window) if len(initial_window) > 0 else 0.0
    
    # Day 1: Assume they entered today with their historical average, 
    # then apply today's actual TSS impact.
    ctl[0] = (historical_average * (1 - alpha)) + (tss_series[0] * alpha)
    
    # Day 2+ normal EWMA decay and growth
    for i in range(1, len(tss_series)):
        ctl[i] = ctl[i-1] * (1 - alpha) + tss_series[i] * alpha
    
    return np.round(ctl, 2)

def compute_atl(tss_series: np.ndarray, time_constant: int = 7) -> np.ndarray:
    """
    Compute Acute Training Load (ATL) fatigue over a TSS history array.
    """
    # ATL uses the exact same average-seeding logic, just with a 7-day window.
    return compute_ctl(tss_series, time_constant=time_constant)

# ==========================================
# PROPRIETARY ASTRAPE SCORES (0-100)
# ==========================================

def compute_strain_score(zone_minutes: Dict[int, float], sport: str = "other") -> int:
    """
    Compute Strain Score (0-100) using natural logarithmic scaling.
    100 is anchored to 24 hours of pure maximum HR output.
    """
    raw_strain = sum(
        minutes * ZONE_STRAIN_COEFFICIENTS.get(zone, 0.0)
        for zone, minutes in zone_minutes.items()
    )
    
    if sport == 'strength':
        raw_strain *= NEUROMUSCULAR_MULTIPLIER
        
    if raw_strain <= 0:
        return 0
        
    score = 100 * (math.log(raw_strain + 1) / math.log(MAX_RAW_STRAIN_24H + 1))
    return int(round(np.clip(score, 0, 100)))

def compute_readiness_score(tsb: float) -> int:
    """
    Compute Race Readiness / Form (0-100) using a logistic (sigmoid) function.
    Maps TSB (-inf to +inf) to a bounded 0-100 scale where TSB 0 = 50.
    """
    k = 0.088  # Growth rate: sets TSB +25 to roughly 90/100
    score = 100 / (1 + math.exp(-k * tsb))
    return int(round(np.clip(score, 0, 100)))

def calculate_astrape_sleep_score(
    actual_sleep_min: float,
    sleep_need_min: float,
    rem_min: float,
    deep_min: float,
    awake_min: float,
) -> int:
    """
    Computes a strict, volatile Sleep Score (0-100).
    Removes the safety net by uncapping architecture penalties and punishing fragmentation.
    Inputs are raw minutes (e.g. Garmin JSON), not precomputed percentages.
    """
    if sleep_need_min <= 0 or actual_sleep_min <= 0:
        return 0

    # 1. Base Quantity Score (Linear, max 100)
    quantity_score = 100.0 * (actual_sleep_min / sleep_need_min)
    quantity_score = min(quantity_score, 100.0)

    # Calculate Restorative Percentage based on raw minutes
    restorative_pct = ((rem_min + deep_min) / actual_sleep_min) * 100.0

    # 2. Uncapped Architecture Penalty (Quality)
    # The body requires ~30% restorative sleep.
    # This applies a steep 2.5% multiplier penalty for every 1% missed below the threshold.
    quality_multiplier = 1.0
    if restorative_pct < 30.0:
        deficit = 30.0 - restorative_pct
        quality_multiplier = max(0.0, 1.0 - (deficit * 0.025))

    # 3. Efficiency Penalty (Fragmentation)
    # Deducts flat points for time spent awake after falling asleep.
    # 0.3 points per minute = an 18-point drop for an hour of tossing and turning.
    efficiency_penalty = awake_min * 0.3

    # 4. Final Calculation
    final_score = (quantity_score * quality_multiplier) - efficiency_penalty

    return int(round(np.clip(final_score, 0, 100)))


def compute_sleep_score(
    actual_sleep_min: float,
    sleep_need_min: float,
    rem_min: float,
    deep_min: float,
    awake_min: float,
) -> int:
    """Astrape sleep score (0-100); delegates to the strict athlete sleep model."""
    return calculate_astrape_sleep_score(
        actual_sleep_min,
        sleep_need_min,
        rem_min,
        deep_min,
        awake_min,
    )

def compute_recovery_score(
    hrv_today: float,
    hrv_avg_30d: float,
    hrv_std_30d: float,
    rhr_today: int,
    rhr_avg_30d: float,
    rhr_std_30d: float,
    sleep_score: int,
    prior_day_atl: float,
    prior_day_atl_max_30d: float,
) -> int:
    """
    Computes a highly volatile Recovery Score (0-100) using Z-scores and a Sigmoid curve.
    Mirrors professional algorithms by letting the Autonomic Nervous System dominate.
    """

    # Prevent division by zero for incredibly stable athletes
    hrv_std = max(float(hrv_std_30d or 0.0), 1.0)
    rhr_std = max(float(rhr_std_30d or 0.0), 1.0)

    # 1. Calculate Standard Deviations (Z-Scores)
    z_hrv = (float(hrv_today) - float(hrv_avg_30d)) / hrv_std
    # Inverted because lower RHR is better (positive means RHR dropped vs baseline)
    z_rhr = (float(rhr_avg_30d) - float(rhr_today)) / rhr_std

    # Combine into a primary Autonomic Nervous System (ANS) index
    # HRV usually dictates slightly more physiological truth than RHR
    ans_z = (z_hrv * 0.6) + (z_rhr * 0.4)

    # 2. Corrected Sigmoid Mapping
    # Anchors Z=0 (average day) to 66/100. 
    # Z=+1 hits ~88. Z=-1 hits ~33. Z=-1.5 drops to 20.
    ans_score = 100.0 / (1.0 + math.exp(-1.36 * (ans_z + 0.485)))

    # 3. Calculate Load Penalty (Freshness)
    safe_max_atl = max(prior_day_atl_max_30d, 1.0)
    load_ratio = prior_day_atl / safe_max_atl
    load_score = np.clip(100 - (load_ratio * 60), 0, 100)

    # 4. Dynamic Blending (ANS trump card)
    if ans_score < 40:
        final_score = (ans_score * 0.80) + (float(sleep_score) * 0.15) + (float(load_score) * 0.05)
    elif ans_score > 70:
        final_score = (ans_score * 0.50) + (float(sleep_score) * 0.35) + (float(load_score) * 0.15)
    else:
        final_score = (ans_score * 0.65) + (float(sleep_score) * 0.25) + (float(load_score) * 0.10)

    return int(round(np.clip(final_score, 0, 100)))

# ==========================================
# SLEEP NEED & DEBT CALCULATIONS
# ==========================================
def compute_sleep_need(
    baseline_min: float,
    strain_score: int,
    current_debt_min: float,
) -> int:
    """
    Calculate tonight's exact sleep need in minutes.
    Combines baseline, today's strain tax, and carried-over debt.
    """
    safe_strain = float(np.clip(float(strain_score or 0), 0.0, 100.0))
    safe_debt = float(np.clip(float(current_debt_min or 0.0), 0.0, MAX_SLEEP_DEBT_MIN))
    strain_tax = (safe_strain / 100.0) * MAX_STRAIN_SLEEP_TAX_MIN
    total_need = float(baseline_min) + float(strain_tax) + safe_debt
    return int(round(total_need))

def compute_sleep_debt_series(
    actual_sleep_series: np.ndarray,
    strain_series: np.ndarray,
    baseline_min: float = DEFAULT_BASELINE_SLEEP_MIN,
) -> np.ndarray:
    """
    Compute rolling Sleep Debt over history arrays (ordered oldest-first).
    Applies daily decay and a strict physiological cap.

    Notes:
    - `strain_series[i]` is the strain incurred on the same day as `actual_sleep_series[i]`
      (i.e., it is used to compute the sleep need for that night's sleep).
    """
    if actual_sleep_series is None or len(actual_sleep_series) == 0:
        return np.array([])

    debt = np.zeros(len(actual_sleep_series), dtype=float)

    for i in range(len(actual_sleep_series)):
        carried_debt_raw = 0.0 if i == 0 else float(debt[i - 1]) * SLEEP_DEBT_DECAY_RATE
        carried_debt = float(np.clip(carried_debt_raw, 0.0, MAX_SLEEP_DEBT_MIN))

        strain_i_raw = float(np.nan_to_num(strain_series[i], nan=0.0)) if strain_series is not None else 0.0
        strain_i = float(np.clip(strain_i_raw, 0.0, 100.0))
        strain_tax = (strain_i / 100.0) * MAX_STRAIN_SLEEP_TAX_MIN
        need_last_night = float(baseline_min) + float(strain_tax) + float(carried_debt)

        actual_i = float(np.nan_to_num(actual_sleep_series[i], nan=0.0))
        debt[i] = np.clip(need_last_night - actual_i, 0.0, MAX_SLEEP_DEBT_MIN)

    return np.round(debt, 1)


# ==========================================
# TRENDING & UTILITY (HELPER FUNCTIONS)
# ==========================================

def compute_ewma_stats(series: np.ndarray, span: int = 30) -> tuple[float, float]:
    """
    Computes the Exponentially Weighted Moving Average (EWMA) and Standard Deviation (EWMSD)
    for a 1D NumPy array.

    Uses alpha = 2 / (span + 1), matching common EWMA conventions.
    Returns (final_mean, final_std) for the last element of the EWMA curve.
    """
    if series is None or len(series) == 0:
        return 0.0, 0.0
    if len(series) == 1:
        return float(series[0]), 0.0

    alpha = 2.0 / (float(span) + 1.0)

    ewma = np.zeros_like(series, dtype=float)
    ewmvar = np.zeros_like(series, dtype=float)

    ewma[0] = float(series[0])
    ewmvar[0] = 0.0

    for i in range(1, len(series)):
        diff = float(series[i]) - float(ewma[i - 1])
        ewma[i] = float(ewma[i - 1]) + alpha * diff
        ewmvar[i] = (1.0 - alpha) * (float(ewmvar[i - 1]) + alpha * (diff ** 2))

    final_mean = float(ewma[-1])
    final_std = float(np.sqrt(ewmvar[-1]))
    return final_mean, final_std

def compute_z_score(latest: float, history: np.ndarray, span: int = 7) -> tuple[float, float, float]:
    """
    Returns (z_score, ewma_mean, ewma_std) for `latest` vs the EWMA baseline of `history`.

    `history` should be the rolling history *up to and including* the latest reading
    (or just prior, callers can choose). When the EWMA std is degenerate (<= 1e-9)
    the z-score is reported as 0.0 to avoid divide-by-near-zero blowups.
    """
    if history is None or len(history) == 0:
        return 0.0, float(latest) if latest is not None else 0.0, 0.0
    mean, sd = compute_ewma_stats(history, span=span)
    if sd <= 1e-9 or latest is None:
        return 0.0, float(mean), float(sd)
    z = (float(latest) - float(mean)) / float(sd)
    return float(z), float(mean), float(sd)


def compute_hrv_trend(hrv_series: np.ndarray) -> Dict[str, Any]:
    """
    Analyze HRV trend over a rolling window.
    """
    if len(hrv_series) < 7:
        return {
            "delta_7d": 0.0,
            "coefficient_of_variation": 0.0,
            "trend_direction": "stable",
            "current_baseline": float(np.mean(hrv_series)) if len(hrv_series) > 0 else 0.0
        }

    mean_7d = np.mean(hrv_series[-7:])
    mean_14d = np.mean(hrv_series[-14:-7]) if len(hrv_series) >= 14 else mean_7d
    
    delta = mean_7d - mean_14d
    cv = (np.std(hrv_series[-7:]) / mean_7d) * 100 if mean_7d > 0 else 0.0
    
    if delta > 3.0:
        direction = "rising"
    elif delta < -3.0:
        direction = "declining"
    else:
        direction = "stable"
    
    return {
        "delta_7d": round(float(delta), 1),
        "coefficient_of_variation": round(float(cv), 1),
        "trend_direction": direction,
        "current_baseline": round(float(mean_7d), 1),
    }

def calculate_rhr_baseline(rhr_history: List[int]) -> float:
    """Calculates 42-day rolling baseline for RHR."""
    if not rhr_history: return 0.0
    return float(np.mean(rhr_history[-42:]))

def calculate_hrv_baseline(hrv_history: List[float]) -> float:
    """Calculates 42-day rolling baseline for HRV."""
    if not hrv_history: return 0.0
    return float(np.mean(hrv_history[-42:]))

def calculate_spo2_baseline(spo2_history: List[float]) -> float:
    """Calculates 42-day rolling baseline for SpO2."""
    if not spo2_history: return 0.0
    return float(np.mean(spo2_history[-42:]))

def calculate_temp_baseline(temp_history: List[float]) -> float:
    """Calculates 42-day rolling baseline for Skin Temp."""
    if not temp_history: return 0.0
    return float(np.mean(temp_history[-42:]))

def calculate_weekly_tss_target(current_ctl: float) -> int:
    """Estimates sustainable weekly TSS target (7.5x CTL)."""
    if not current_ctl: return 200
    return int(round(current_ctl * 7.5))

def calculate_threshold_hr_est(max_hr: int, resting_hr: int) -> int:
    """Estimates Threshold HR (83% of HRR + RHR)."""
    if not max_hr or not resting_hr: return 0
    hrr = max_hr - resting_hr
    return int(round((hrr * 0.83) + resting_hr))

def normalize_rowing_watts(rowing_watts: float) -> float:
    """Converts average rowing watts to normalized equivalent."""
    return round(rowing_watts * 1.12, 2)