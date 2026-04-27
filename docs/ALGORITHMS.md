# Algorithms

ASTRAPE's metric computation layer is implemented in Python using NumPy vectorized operations. All formulas are based on established sports science literature, primarily the training load model developed by Bannister (1975) and commercialized by TrainingPeaks.

---

## Training Stress Score (TSS)

TSS quantifies the physiological cost of a single workout as a dimensionless number. A one-hour ride at exactly FTP produces a TSS of 100.

### Cycling TSS (Power-Based)

```
TSS = (duration_sec × NP × IF) / (FTP × 3600) × 100
```

Where:
- `duration_sec` — total workout duration in seconds
- `NP` — Normalized Power (see below)
- `IF` — Intensity Factor = NP / FTP
- `FTP` — Functional Threshold Power (watts)

**Normalized Power (NP):**

NP captures the physiological cost of variable-intensity efforts more accurately than average power. It weights hard efforts disproportionately because the body's oxygen and metabolic response to intensity is non-linear.

```python
def normalized_power(power_series: np.ndarray) -> float:
    """
    Calculate Normalized Power from a 1-second power array.
    
    Args:
        power_series: Array of power values at 1-second resolution (watts)
    Returns:
        Normalized Power in watts
    """
    # Step 1: 30-second rolling average
    rolling_30s = np.convolve(power_series, np.ones(30)/30, mode='valid')
    
    # Step 2: Raise to the 4th power
    fourth_power = rolling_30s ** 4
    
    # Step 3: Average of the 4th-power values
    mean_fourth = np.mean(fourth_power)
    
    # Step 4: Take the 4th root
    return mean_fourth ** 0.25
```

### Running TSS (Pace + HR Hybrid)

For running, power meters are less common. ASTRAPE uses a HR-based approach when power is unavailable:

```
TSS = duration_hours × (avg_hr / threshold_hr)² × 100
```

When running power is available (e.g., Stryd pod):
```
TSS = (duration_sec × run_watts × IF) / (rFTPw × 3600) × 100
```

### Strength / Other Sports TSS

For activities without power or pace data, TSS is estimated from HR zone time distribution:

```python
ZONE_WEIGHT = {1: 0.2, 2: 0.5, 3: 0.8, 4: 1.0, 5: 1.3}

def tss_from_hr_zones(zone_minutes: dict, threshold_hr: int) -> float:
    weighted_minutes = sum(
        minutes * ZONE_WEIGHT[zone]
        for zone, minutes in zone_minutes.items()
    )
    return (weighted_minutes / 60) * 100
```

---

## Chronic Training Load (CTL) — Fitness

CTL is the 42-day exponentially weighted moving average of daily TSS. It represents long-term fitness adaptation — the body's capacity to absorb and benefit from training stress.

```
CTL_today = CTL_yesterday × e^(-1/42) + TSS_today × (1 - e^(-1/42))
```

**Python implementation (vectorized):**

```python
import numpy as np

def compute_ctl(tss_series: np.ndarray, time_constant: int = 42) -> np.ndarray:
    """
    Compute Chronic Training Load (CTL) over a TSS history array.
    
    Args:
        tss_series: Array of daily TSS values, ordered oldest-first
        time_constant: Decay constant in days (default: 42)
    Returns:
        Array of CTL values, same length as input
    """
    alpha = 1 - np.exp(-1 / time_constant)
    ctl = np.zeros(len(tss_series))
    ctl[0] = tss_series[0] * alpha
    
    for i in range(1, len(tss_series)):
        ctl[i] = ctl[i-1] * (1 - alpha) + tss_series[i] * alpha
    
    return ctl
```

**Practical interpretation:**

| CTL Range | Fitness Level |
|---|---|
| < 30 | Beginner / detrained |
| 30–50 | Recreational athlete |
| 50–70 | Trained amateur |
| 70–90 | Competitive age-grouper |
| 90–120 | Elite amateur |
| > 120 | Professional |

---

## Acute Training Load (ATL) — Fatigue

ATL is the 7-day exponentially weighted moving average of daily TSS. It rises and falls quickly, representing short-term accumulated fatigue.

```
ATL_today = ATL_yesterday × e^(-1/7) + TSS_today × (1 - e^(-1/7))
```

**Python implementation:**

```python
def compute_atl(tss_series: np.ndarray, time_constant: int = 7) -> np.ndarray:
    """
    Compute Acute Training Load (ATL) over a TSS history array.
    Uses identical logic to compute_ctl with a 7-day time constant.
    """
    return compute_ctl(tss_series, time_constant=7)
```

---

## Training Stress Balance (TSB) — Form

TSB is the simplest of the trio: fitness minus fatigue. A positive TSB means the athlete is "in form" — carrying fitness without excessive fatigue. A negative TSB means they are fatigued relative to their fitness.

```
TSB_today = CTL_yesterday − ATL_yesterday
```

Note: TSB uses *yesterday's* CTL and ATL, not today's. This represents the form the athlete starts the day with before today's workout.

**Practical interpretation:**

| TSB Range | Race Readiness |
|---|---|
| > +25 | Peak form. Race window. Risk of detraining if sustained. |
| +10 to +25 | Optimal. Hard quality sessions here. |
| 0 to +10 | Moderate form. Good for hard training. |
| -10 to 0 | Slight fatigue. Sustainable. |
| -10 to -30 | Significant fatigue. Normal during training blocks. |
| < -30 | Heavy fatigue. Risk of injury or illness. Reduce load. |

---

## Recovery Score

The ASTRAPE Recovery Score (0–100) is a weighted composite of multiple physiological signals. Unlike WHOOP's proprietary recovery model, ASTRAPE's formula is transparent and auditable.

```python
def compute_recovery_score(
    hrv_rmssd: float,
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
    Compute the ASTRAPE Recovery Score (0–100).
    
    Higher scores indicate greater readiness for high-intensity training.
    """
    scores = {}
    
    # HRV component (weight: 35%)
    # Deviation from 30-day baseline, normalized to ±30% range
    hrv_delta_pct = (hrv_rmssd - hrv_baseline_30d) / hrv_baseline_30d
    scores['hrv'] = np.clip(50 + hrv_delta_pct * 100, 0, 100)
    
    # Resting HR component (weight: 20%)
    # Elevated RHR = fatigue signal
    rhr_delta = resting_hr - resting_hr_baseline_30d
    scores['rhr'] = np.clip(100 - rhr_delta * 5, 0, 100)
    
    # Sleep score component (weight: 30%)
    # Direct passthrough of sleep quality score
    scores['sleep'] = float(sleep_score)
    
    # Prior load component (weight: 10%)
    # How fresh is the athlete relative to their recent peak?
    load_ratio = prior_day_atl / max(prior_day_atl_max_30d, 1)
    scores['load'] = np.clip(100 - load_ratio * 60, 0, 100)
    
    # Illness indicator (weight: 5%)
    # Elevated skin temp or low SpO2 tanks recovery
    illness_penalty = 0
    if skin_temp_deviation > 0.5:
        illness_penalty += min((skin_temp_deviation - 0.5) * 40, 50)
    if spo2_pct < 95:
        illness_penalty += (95 - spo2_pct) * 10
    scores['vitals'] = max(0, 100 - illness_penalty)
    
    # Weighted sum
    weights = {'hrv': 0.35, 'rhr': 0.20, 'sleep': 0.30, 'load': 0.10, 'vitals': 0.05}
    composite = sum(scores[k] * weights[k] for k in scores)
    
    return int(round(np.clip(composite, 0, 100)))
```

**Recovery score interpretation:**

| Score | Label | Recommendation |
|---|---|---|
| 75–100 | Recovered | Attack hard sessions |
| 50–74 | Moderate | Aerobic or moderate intensity work |
| 25–49 | Fatigued | Easy Z1/Z2 only |
| 0–24 | Depleted | Rest or active recovery only |

---

## Strain Score

The ASTRAPE Strain Score (0–21) measures cardiovascular load for a given period. The scale matches WHOOP's strain scale for familiarity.

```python
ZONE_STRAIN_COEFFICIENTS = {
    1: 0.5,    # Z1 Recovery
    2: 1.0,    # Z2 Aerobic
    3: 2.5,    # Z3 Tempo
    4: 5.0,    # Z4 Threshold
    5: 8.0,    # Z5 VO2max
}

def compute_strain_score(zone_minutes: dict[int, float]) -> float:
    """
    Compute cardiovascular strain on 0–21 scale.
    
    Args:
        zone_minutes: Dict mapping HR zone number (1-5) to minutes in zone
    Returns:
        Strain score (0–21)
    """
    raw_strain = sum(
        minutes * ZONE_STRAIN_COEFFICIENTS[zone]
        for zone, minutes in zone_minutes.items()
    )
    # Normalize: ~420 raw points ≈ 21 (a 2h threshold session + warmup)
    normalized = (raw_strain / 420) * 21
    return min(round(normalized, 1), 21.0)
```

---

## HRV Trend Analysis

ASTRAPE computes a 7-day HRV trend to distinguish signal from noise in daily readings.

```python
def hrv_trend(hrv_series: np.ndarray) -> dict:
    """
    Analyze HRV trend over a rolling window.
    
    Returns:
        dict with:
            delta_7d: Change vs 7-day rolling mean
            coefficient_of_variation: Day-to-day variability %
            trend_direction: "rising" | "stable" | "declining"
    """
    mean_7d = np.mean(hrv_series[-7:])
    mean_14d = np.mean(hrv_series[-14:-7]) if len(hrv_series) >= 14 else mean_7d
    
    delta = mean_7d - mean_14d
    cv = (np.std(hrv_series[-7:]) / mean_7d) * 100
    
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
        "current_baseline": round(mean_7d, 1),
    }
```


