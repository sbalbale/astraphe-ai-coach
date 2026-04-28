import numpy as np
import pandas as pd
from typing import List, Dict

def normalize_rowing_watts(rowing_watts: float) -> float:
    return round(rowing_watts * 1.12, 2)

def calculate_cycling_tss(duration_seconds: int, normalized_power: int, ftp: int) -> float:
    if ftp <= 0:
        return 0.0
    intensity_factor = normalized_power / ftp
    tss = (duration_seconds * normalized_power * intensity_factor) / (ftp * 3600) * 100
    return round(tss, 2)

def calculate_hr_tss(duration_seconds: int, zone_pcts: Dict[int, int]) -> float:
    """
    Calculate TSS based on time in heart rate zones using standard intensity weights.
    zone_pcts: mapping of zone number (1-5) to percentage of time.
    """
    # Standard hrTSS weighting factors
    weights = {1: 0.45, 2: 0.65, 3: 0.85, 4: 1.05, 5: 1.25}
    
    weighted_hours = 0
    for zone, pct in zone_pcts.items():
        if pct:
            weighted_hours += (duration_seconds / 3600) * (pct / 100) * weights.get(zone, 0)
    
    return round(weighted_hours * 100, 2)

def calculate_training_load(daily_tss_history: List[float]) -> Dict[str, float]:
    if not daily_tss_history:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
    tss_series = pd.Series(daily_tss_history)
    ctl_series = tss_series.ewm(span=42, adjust=False).mean()
    atl_series = tss_series.ewm(span=7, adjust=False).mean()
    current_ctl = ctl_series.iloc[-1]
    current_atl = atl_series.iloc[-1]
    current_tsb = current_ctl - current_atl
    return {"ctl": round(current_ctl, 1), "atl": round(current_atl, 1), "tsb": round(current_tsb, 1)}

def calculate_astrape_sleep_need(baseline_min: float, previous_strain: float, current_debt_min: float) -> int:
    # Astrape Need = Baseline + (Strain * 1.8) + Current Debt
    # We cap the strain impact to 2 hours (120 mins)
    strain_impact = min(120, (previous_strain or 0) * 1.8)
    return int(round(baseline_min + strain_impact + (current_debt_min or 0)))

def calculate_astrape_sleep_score(duration_min: float, rem_pct: float, deep_pct: float, sleep_need_min: float = 480) -> int:
    if not duration_min: return 0
    # Use sleep_need if available (includes baseline + debt), fallback to 8 hours
    goal = sleep_need_min if sleep_need_min and sleep_need_min > 0 else 480
    
    # Fulfillment score (70%)
    fulfillment_score = min(100, (duration_min / goal) * 100)
    
    # Quality: REM + Deep % (goal: 45%)
    qual_pct = (rem_pct or 0) + (deep_pct or 0)
    qual_score = min(100, (qual_pct / 45) * 100)
    
    return int(round(fulfillment_score * 0.7 + qual_score * 0.3))

def calculate_astrape_recovery_score(hrv: float, baseline_hrv: float, sleep_score: int, resting_hr: int, baseline_rhr: int) -> int:
    if not hrv or not resting_hr: return 0
    # HRV score (45%)
    hrv_ratio = hrv / (baseline_hrv or 50)
    hrv_score = min(100, max(0, hrv_ratio * 75))
    # RHR score (25%)
    rhr_diff = (baseline_rhr or 60) - resting_hr
    rhr_score = min(100, max(0, 50 + (rhr_diff * 5)))
    # Sleep contrib (30%)
    return int(np.clip(round(hrv_score * 0.45 + rhr_score * 0.25 + sleep_score * 0.3), 0, 100))