import numpy as np
import pandas as pd
from typing import List, Dict, Optional

# ==========================================
# CONSTANTS & COEFFICIENTS
# ==========================================

# Weightings for HR-based Training Stress Score (hrTSS)
HR_ZONE_TSS_WEIGHTS = {1: 0.45, 2: 0.65, 3: 0.85, 4: 1.05, 5: 1.25}

# Exponential coefficients for cardiovascular strain (0-21 scale)
ZONE_STRAIN_COEFFICIENTS = {1: 0.5, 2: 1.0, 3: 2.5, 4: 5.0, 5: 8.0}

# ==========================================
# POWER & WORKLOAD METRICS (TSS)
# ==========================================

def calculate_normalized_power(power_series: np.ndarray) -> float:
    """
    Calculate Normalized Power from a 1-second power array using a 30s rolling average.
    """
    if len(power_series) < 30:
        return float(np.mean(power_series)) if len(power_series) > 0 else 0.0
        
    rolling_30s = np.convolve(power_series, np.ones(30)/30, mode='valid')
    fourth_power = rolling_30s ** 4
    mean_fourth = np.mean(fourth_power)
    return float(mean_fourth ** 0.25)

def normalize_rowing_watts(rowing_watts: float) -> float:
    """Applies standard scalar to convert average rowing watts to normalized equivalent."""
    return round(rowing_watts * 1.12, 2)

def calculate_cycling_tss(duration_seconds: int, normalized_power: float, ftp: int) -> float:
    """Calculates Power-based Training Stress Score (pTSS)."""
    if ftp <= 0 or not duration_seconds:
        return 0.0
    intensity_factor = normalized_power / ftp
    tss = (duration_seconds * normalized_power * intensity_factor) / (ftp * 3600) * 100
    return round(tss, 2)

def calculate_hr_tss(duration_seconds: int, zone_pcts: Dict[int, float]) -> float:
    """
    Calculate TSS based on time in heart rate zones using standard intensity weights.
    zone_pcts: mapping of zone number (1-5) to percentage of time (0-100).
    """
    if not duration_seconds or not zone_pcts:
        return 0.0
        
    weighted_hours = 0.0
    for zone, pct in zone_pcts.items():
        if pct:
            weighted_hours += (duration_seconds / 3600) * (pct / 100.0) * HR_ZONE_TSS_WEIGHTS.get(zone, 0)
    
    return round(weighted_hours * 100, 2)

# ==========================================
# TRAINING LOAD MODELS (CTL, ATL, TSB)
# ==========================================

def calculate_training_load(daily_tss_history: List[float]) -> Dict[str, float]:
    """
    Calculates today's Chronic Training Load (CTL), Acute Training Load (ATL), 
    and Training Stress Balance (TSB).
    """
    if not daily_tss_history:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        
    # SEEDING STRATEGY: Handle the "Cold Start" problem for histories under 42 days
    # By padding the history with the athlete's average, the EWMA has a stable baseline to start from.
    history_length = len(daily_tss_history)
    if history_length < 42:
        historical_average = sum(daily_tss_history) / history_length
        missing_days = 42 - history_length
        # Pad the array with the average so the EWMA math can fully saturate
        padded_history = [historical_average] * missing_days + daily_tss_history
        tss_series = pd.Series(padded_history)
    else:
        tss_series = pd.Series(daily_tss_history)
    
    # Calculate EWMAs
    ctl_series = tss_series.ewm(span=42, adjust=False).mean()
    atl_series = tss_series.ewm(span=7, adjust=False).mean()
    
    current_ctl = ctl_series.iloc[-1]
    current_atl = atl_series.iloc[-1]
    
    # TSB (Form) = Fitness (CTL) - Fatigue (ATL)
    current_tsb = current_ctl - current_atl
    
    return {
        "ctl": round(current_ctl, 1), 
        "atl": round(current_atl, 1), 
        "tsb": round(current_tsb, 1)
    }

# ==========================================
# CARDIOVASCULAR STRAIN
# ==========================================

def calculate_raw_strain_score(zone_minutes: Dict[int, float]) -> float:
    """
    Compute raw cardiovascular strain on a 0–21 scale based on escalating physiological cost.
    """
    raw_strain = sum(
        minutes * ZONE_STRAIN_COEFFICIENTS.get(zone, 0)
        for zone, minutes in zone_minutes.items()
    )
    # Normalize: ~420 raw points ≈ 21 (equivalent to a 2h threshold session + warmup)
    normalized = (raw_strain / 420.0) * 21.0
    return float(min(round(normalized, 1), 21.0))

def calculate_astrape_strain_score(raw_strain: float) -> int:
    """Normalizes Raw strain (0-21 scale) to Astrape score (0-100 scale)."""
    if not raw_strain: 
        return 0
    return int(np.clip(round((raw_strain / 21.0) * 100), 0, 100))

# ==========================================
# SLEEP ARCHITECTURE
# ==========================================

def calculate_astrape_sleep_need(baseline_min: float, previous_strain: float, current_debt_min: float) -> int:
    """
    Dynamic sleep need based on accumulated strain and prior sleep debt.
    Caps the strain penalty at 2 hours (120 mins).
    """
    strain_impact = min(120, (previous_strain or 0) * 1.8)
    return int(round(baseline_min + strain_impact + (current_debt_min or 0)))

def calculate_astrape_sleep_score(duration_min: float, rem_pct: float, deep_pct: float, sleep_need_min: float = 480) -> int:
    """
    Scores sleep out of 100 based on fulfillment of dynamic need (70%) and clinical architecture (30%).
    """
    if not duration_min: 
        return 0
        
    goal = sleep_need_min if sleep_need_min and sleep_need_min > 0 else 480.0
    
    # Fulfillment score (70% weight)
    fulfillment_score = min(100, (duration_min / goal) * 100)
    
    # Quality: REM + Deep % (Target optimal is 45% of total sleep time)
    qual_pct = (rem_pct or 0) + (deep_pct or 0)
    qual_score = min(100, (qual_pct / 45.0) * 100)
    
    return int(round((fulfillment_score * 0.7) + (qual_score * 0.3)))

# ==========================================
# RECOVERY & READINESS
# ==========================================

def calculate_astrape_recovery_score(
    hrv_rmssd: float, hrv_baseline_30d: float, 
    resting_hr: int, resting_hr_baseline_30d: float, 
    sleep_score: int
) -> int:
    """
    Pure Recovery Score (0-100) focusing strictly on autonomic nervous system repair and sleep.
    """
    if not hrv_rmssd or not resting_hr: 
        return 0
        
    # 1. HRV component (50% Weight)
    hrv_delta_pct = (hrv_rmssd - hrv_baseline_30d) / max(hrv_baseline_30d, 1)
    hrv_score = np.clip(50 + (hrv_delta_pct * 100), 0, 100)
    
    # 2. RHR component (20% Weight)
    rhr_delta = resting_hr - resting_hr_baseline_30d
    rhr_score = np.clip(100 - (rhr_delta * 5), 0, 100)
    
    # 3. Sleep component (30% Weight)
    raw_recovery = (hrv_score * 0.50) + (rhr_score * 0.20) + (sleep_score * 0.30)
    
    return int(round(np.clip(raw_recovery, 0, 100)))


def calculate_astrape_readiness_score(
    recovery_score: int, 
    prior_day_atl: float, prior_day_atl_max_30d: float,
    skin_temp_deviation: float, spo2_pct: float
) -> int:
    """
    Overall Readiness Score (0-100) assessing actual capacity to train. 
    Factors in biological recovery, acute training fatigue (ATL), and illness indicators.
    """
    # Base capacity is dictated by physiological recovery (70% weight)
    base_readiness = recovery_score * 0.70
    
    # Acute Fatigue component (30% weight)
    # The closer ATL is to the recent 30-day max, the lower the form score
    load_ratio = prior_day_atl / max(prior_day_atl_max_30d, 1)
    load_score = np.clip(100 - (load_ratio * 80), 0, 100) 
    
    raw_readiness = base_readiness + (load_score * 0.30)
    
    # Vitals / Illness Penalty (Absolute point deductions)
    illness_penalty = 0
    if skin_temp_deviation > 0.5:
        illness_penalty += min((skin_temp_deviation - 0.5) * 40, 50)
    if spo2_pct < 95:
        illness_penalty += (95 - spo2_pct) * 10
        
    final_readiness = max(0, raw_readiness - illness_penalty)
    return int(round(final_readiness))

# ==========================================
# TREND ANALYSIS
# ==========================================

def calculate_hrv_trend(hrv_series: np.ndarray) -> dict:
    """
    Analyze HRV trend over a rolling window. Dynamically scales based on available data 
    (from 1 day to infinity) to prevent crashing on new accounts.
    """
    if len(hrv_series) == 0:
        return {"status": "insufficient_data"}
        
    n = len(hrv_series)
    
    # Dynamic window sizing
    recent_window = min(7, n)
    past_window = min(7, max(0, n - recent_window))
    
    recent_data = hrv_series[-recent_window:]
    mean_recent = np.mean(recent_data)
    
    # Fallbacks for short histories
    if past_window > 0:
        past_data = hrv_series[-recent_window - past_window : -recent_window]
        mean_past = np.mean(past_data)
    elif n > 1:
        # If we have < 7 days total, compare latest day to the average of previous days
        mean_past = np.mean(hrv_series[:-1])
    else:
        # Day 1: Delta is 0
        mean_past = mean_recent
        
    delta = mean_recent - mean_past
    cv = (np.std(recent_data) / mean_recent) * 100 if mean_recent > 0 else 0
    
    if delta > 3:
        direction = "rising"
    elif delta < -3:
        direction = "declining"
    else:
        direction = "stable"
    
    return {
        "delta_7d": round(delta, 1),
        "coefficient_of_variation": round(cv, 1),
        "trend_direction": direction,
        "current_baseline_7d": round(mean_recent, 1),
    }

def calculate_rhr_baseline(rhr_history: List[int]) -> float:
    """
    Calculates the 42-day rolling baseline for Resting Heart Rate.
    If less than 42 days, returns the average of available data.
    """
    if not rhr_history:
        return 0.0
    
    # Use 42 days for cardiovascular baseline alignment
    window = min(len(rhr_history), 42)
    recent_rhr = rhr_history[-window:]
    
    return float(np.mean(recent_rhr))

def calculate_hrv_baseline(hrv_history: List[float]) -> float:
    """
    Calculates the 42-day rolling baseline for HRV (RMSSD).
    If less than 42 days, returns the average of available data.
    """
    if not hrv_history:
        return 0.0
    
    # Use 42 days for cardiovascular baseline alignment
    window = min(len(hrv_history), 42)
    recent_hrv = hrv_history[-window:]
    
    return float(np.mean(recent_hrv))

def calculate_weekly_tss_target(current_ctl: float) -> int:
    """
    Estimates a sustainable weekly TSS target based on current fitness (CTL).
    Progression Factor: 7.5x CTL (Targeting ~5% weekly load progression).
    """
    if not current_ctl:
        return 200 # Minimum baseline target for beginners
        
    return int(round(current_ctl * 7.5))

def calculate_threshold_hr_est(max_hr: int, resting_hr: int) -> int:
    """
    Estimates Threshold HR using the Heart Rate Reserve (%HRR) method.
    Standard Anaerobic Threshold estimate: 83% of HRR + Resting HR.
    """
    if not max_hr or not resting_hr:
        return 0
        
    hrr = max_hr - resting_hr
    return int(round((hrr * 0.83) + resting_hr))