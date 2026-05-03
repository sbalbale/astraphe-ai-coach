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

### Running TSS (Pace-Based tRSS / rTSS)

For running, ASTRAPE prefers **pace-based** stress when the athlete has a threshold pace anchor:

```
IF = threshold_pace_sec_km / avg_pace_sec_km
TSS = duration_hours × IF² × 100
```

Because pace is inversely proportional to speed, the IF ratio is inverted compared to power-based formulas.

### Heart Rate Stress Score (HRSS) — Banister TRIMP

When continuous HR is available, HRSS is computed using Banister’s exponential TRIMP and normalized so that
**1 hour at LTHR = 100**. When only aggregated time-in-zone is available, ASTRAPE approximates HRSS using
the mathematical midpoint HR of each zone.

Strength training (and other neuromuscular-dominant sports) applies a central nervous system multiplier.

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

| CTL Range | Fitness Level           |
| --------- | ----------------------- |
| < 30      | Beginner / detrained    |
| 30–50     | Recreational athlete    |
| 50–70     | Trained amateur         |
| 70–90     | Competitive age-grouper |
| 90–120    | Elite amateur           |
| > 120     | Professional            |

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

Note: TSB uses _yesterday's_ CTL and ATL, not today's. This represents the form the athlete starts the day with before today's workout.

**Practical interpretation:**

| TSB Range  | Race Readiness                                           |
| ---------- | -------------------------------------------------------- |
| > +25      | Peak form. Race window. Risk of detraining if sustained. |
| +10 to +25 | Optimal. Hard quality sessions here.                     |
| 0 to +10   | Moderate form. Good for hard training.                   |
| -10 to 0   | Slight fatigue. Sustainable.                             |
| -10 to -30 | Significant fatigue. Normal during training blocks.      |
| < -30      | Heavy fatigue. Risk of injury or illness. Reduce load.   |

---

## Recovery Score

The ASTRAPE Recovery Score (0–100) is designed to avoid “regression to the mean” by (1) using Z-scores relative to the athlete’s own baseline variability and (2) dynamically weighting the Autonomic Nervous System (ANS) as a trump card on bad days.

```python
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
    Lets the ANS dominate via dynamic weighting.
    """
    # Z-scores (RHR inverted: lower is better)
    z_hrv = (hrv_today - hrv_avg_30d) / max(hrv_std_30d, 1.0)
    z_rhr = (rhr_avg_30d - rhr_today) / max(rhr_std_30d, 1.0)

    ans_z = (z_hrv * 0.6) + (z_rhr * 0.4)
    ans_score = 100.0 / (1.0 + math.exp(-1.5 * (ans_z - 0.4)))

    load_ratio = prior_day_atl / max(prior_day_atl_max_30d, 1.0)
    load_score = np.clip(100 - (load_ratio * 60), 0, 100)

    if ans_score < 40:
        final = (ans_score * 0.80) + (sleep_score * 0.15) + (load_score * 0.05)
    elif ans_score > 70:
        final = (ans_score * 0.50) + (sleep_score * 0.35) + (load_score * 0.15)
    else:
        final = (ans_score * 0.65) + (sleep_score * 0.25) + (load_score * 0.10)

    return int(round(np.clip(final, 0, 100)))
```

**Recovery score interpretation:**

| Score  | Label     | Recommendation                     |
| ------ | --------- | ---------------------------------- |
| 75–100 | Recovered | Attack hard sessions               |
| 50–74  | Moderate  | Aerobic or moderate intensity work |
| 25–49  | Fatigued  | Easy Z1/Z2 only                    |
| 0–24   | Depleted  | Rest or active recovery only       |

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
