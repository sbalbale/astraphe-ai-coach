import numpy as np
import pandas as pd
from typing import List, Dict

def normalize_rowing_watts(rowing_watts: float) -> float:
    """
    Normalizes rowing power to its cycling metabolic equivalent.
    Rowing is roughly 12% more costly at the same watt output.
    """
    return round(rowing_watts * 1.12, 2)

def calculate_cycling_tss(duration_seconds: int, normalized_power: int, ftp: int) -> float:
    """
    Calculate Training Stress Score (TSS) for a cycling workout.
    Formula: 
    $$TSS = \frac{t \times NP \times IF}{FTP \times 3600} \times 100$$
    Where $t$ is duration in seconds, $NP$ is Normalized Power, and $IF$ is Intensity Factor ($NP/FTP$).
    """
    if ftp <= 0:
        return 0.0
    
    intensity_factor = normalized_power / ftp
    tss = (duration_seconds * normalized_power * intensity_factor) / (ftp * 3600) * 100
    
    return round(tss, 2)

def calculate_training_load(daily_tss_history: List[float]) -> Dict[str, float]:
    """
    Calculate CTL (Fitness), ATL (Fatigue), and TSB (Form) using 
    Exponentially Weighted Moving Averages (EWMA).
    """
    if not daily_tss_history:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}

    tss_series = pd.Series(daily_tss_history)
    
    # CTL: Chronic Training Load (42-day span)
    ctl_series = tss_series.ewm(span=42, adjust=False).mean()
    # ATL: Acute Training Load (7-day span)
    atl_series = tss_series.ewm(span=7, adjust=False).mean()
    
    current_ctl = ctl_series.iloc[-1]
    current_atl = atl_series.iloc[-1]
    
    # TSB (Training Stress Balance) = Fitness - Fatigue
    current_tsb = current_ctl - current_atl
    
    return {
        "ctl": round(current_ctl, 1),
        "atl": round(current_atl, 1),
        "tsb": round(current_tsb, 1)
    }

def calculate_recovery_score(hrv: float, baseline_hrv: float, sleep_score: int, resting_hr: int, baseline_rhr: int) -> int:
    """
    Calculate a normalized 0-100 daily recovery readiness score (RRS).
    Weights: HRV trend (35%), Sleep Score (35%), RHR trend (30%).
    """
    # 1. HRV Component: Ratio of today vs 7-day baseline
    hrv_ratio = hrv / baseline_hrv if baseline_hrv > 0 else 1.0
    hrv_norm = np.clip(hrv_ratio, 0.5, 1.2) 
    hrv_score = ((hrv_norm - 0.5) / 0.7) * 100 
    
    # 2. Sleep Component
    sleep_score_norm = np.clip(sleep_score, 0, 100)
    
    # 3. RHR Component: Inverse ratio (lower is better)
    rhr_ratio = baseline_rhr / resting_hr if resting_hr > 0 else 1.0
    rhr_norm = np.clip(rhr_ratio, 0.8, 1.2)
    rhr_score = ((rhr_norm - 0.8) / 0.4) * 100

    composite = (hrv_score * 0.35) + (sleep_score_norm * 0.35) + (rhr_score * 0.30)
    
    return int(np.clip(composite, 0, 100))