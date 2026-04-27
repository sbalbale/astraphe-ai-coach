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

def calculate_recovery_score(hrv: float, baseline_hrv: float, sleep_score: int, resting_hr: int, baseline_rhr: int) -> int:
    hrv_ratio = hrv / baseline_hrv if baseline_hrv > 0 else 1.0
    hrv_norm = np.clip(hrv_ratio, 0.5, 1.2) 
    hrv_score = ((hrv_norm - 0.5) / 0.7) * 100 
    sleep_score_norm = np.clip(sleep_score, 0, 100)
    rhr_ratio = baseline_rhr / resting_hr if resting_hr > 0 else 1.0
    rhr_norm = np.clip(rhr_ratio, 0.8, 1.2)
    rhr_score = ((rhr_norm - 0.8) / 0.4) * 100
    composite = (hrv_score * 0.35) + (sleep_score_norm * 0.35) + (rhr_score * 0.30)
    return int(np.clip(composite, 0, 100))