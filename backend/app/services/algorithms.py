import math
import numpy as np
from typing import Dict, Any, List, Optional

# ==========================================
# CONSTANTS
# ==========================================

# Standard TSS weighting for HR zones
ZONE_WEIGHT = {0: 0.0, 1: 0.2, 2: 0.5, 3: 0.8, 4: 1.0, 5: 1.3}

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

def tss_from_hr_zones(duration_sec: int, zone_minutes: Dict[int, float]) -> float:
    """
    Estimate TSS based on time spent in heart rate zones.
    """
    weighted_minutes = sum(
        minutes * ZONE_WEIGHT.get(zone, 0.0)
        for zone, minutes in zone_minutes.items()
    )
    return (weighted_minutes / 60) * 100

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

def compute_strain_score(zone_minutes: Dict[int, float]) -> int:
    """
    Compute Strain Score (0-100) using natural logarithmic scaling.
    100 is anchored to 24 hours of pure maximum HR output.
    """
    raw_strain = sum(
        minutes * ZONE_STRAIN_COEFFICIENTS.get(zone, 0.0)
        for zone, minutes in zone_minutes.items()
    )
    
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

def compute_sleep_score(
    actual_sleep_min: float, 
    sleep_need_min: float, 
    rem_pct: float, 
    deep_pct: float
) -> int:
    """
    Compute Sleep Score (0-100) using logarithmic need ratio and architecture penalties.
    """
    if sleep_need_min <= 0 or actual_sleep_min <= 0:
        return 0

    # Base quantity score (capped at 100 to prevent over-rewarding excessive sleep)
    quantity_score = 100 * (math.log(actual_sleep_min + 1) / math.log(sleep_need_min + 1))
    quantity_score = min(quantity_score, 100.0)
    
    # Quality modifier based on sleep architecture
    # Healthy adult target is ~20% REM and ~15% Deep (35% combined)
    combined_restorative_pct = (rem_pct or 0.0) + (deep_pct or 0.0)
    
    quality_multiplier = 1.0
    if combined_restorative_pct < 30.0:
        # Penalize poor architecture linearly down to a max 15% penalty
        deficit = 30.0 - combined_restorative_pct
        quality_multiplier = max(0.85, 1.0 - (deficit * 0.01))
        
    final_score = quantity_score * quality_multiplier
    return int(round(np.clip(final_score, 0, 100)))

def compute_recovery_score(
    hrv_today: float,
    hrv_baseline_30d: float,
    resting_hr: int,
    resting_hr_baseline_30d: float,
    sleep_score: int,
    prior_day_atl: float,
    prior_day_atl_max_30d: float,
    skin_temp_deviation: float,
    spo2_pct: float,
) -> int:
    """
    Compute the composite Recovery Score (0–100).
    Integrates logarithmic HRV handling alongside established metrics.
    """
    scores = {}
    
    # 1. HRV component (weight: 35%) - Logarithmic ratio
    if hrv_baseline_30d > 0 and hrv_today > 0:
        log_ratio = math.log(hrv_today) / math.log(hrv_baseline_30d)
        scores['hrv'] = np.clip(50 + (50 * log_ratio), 0, 100)
    else:
        scores['hrv'] = 50.0

    # 2. Resting HR component (weight: 20%) - Linear penalty for elevated RHR
    rhr_delta = resting_hr - resting_hr_baseline_30d
    scores['rhr'] = np.clip(100 - (rhr_delta * 5), 0, 100)
    
    # 3. Sleep score component (weight: 30%) - Direct passthrough of proprietary score
    scores['sleep'] = float(sleep_score)
    
    # 4. Prior load component (weight: 10%) - Freshness relative to peak ATL
    safe_max_atl = max(prior_day_atl_max_30d, 1.0)
    load_ratio = prior_day_atl / safe_max_atl
    scores['load'] = np.clip(100 - (load_ratio * 60), 0, 100)
    
    # 5. Illness/Vitals indicator (weight: 5%)
    illness_penalty = 0.0
    if skin_temp_deviation > 0.5:
        illness_penalty += min((skin_temp_deviation - 0.5) * 40, 50.0)
    if spo2_pct < 95.0:
        illness_penalty += (95.0 - spo2_pct) * 10
        
    scores['vitals'] = np.clip(100 - illness_penalty, 0, 100)
    
    # Weighted composite sum
    weights = {'hrv': 0.35, 'rhr': 0.20, 'sleep': 0.30, 'load': 0.10, 'vitals': 0.05}
    composite = sum(scores[k] * weights[k] for k in scores)
    
    return int(round(np.clip(composite, 0, 100)))

# ==========================================
# TRENDING & UTILITY (HELPER FUNCTIONS)
# ==========================================

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