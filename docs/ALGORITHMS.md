# Algorithms

The metric layer is implemented in `backend/app/services/algorithms.py` and related helpers (`hr_zones.py`, `hr_anchors.py`, `day_strain.py`, `hr_activity_detection.py`, `heart_rate_series.py`). The formulas are pure Python/NumPy functions; database reads/writes happen in routers or `processing.py`.

## Training Stress Score

A workout's TSS is picked in this order (`processing.py`):

1. Power TSS: bike with normalized power and an FTP (the workout's own FTP, else the athlete's FTP on that date).
2. Pace rTSS: run with average pace and a threshold pace.
3. HRSS from time in zone: any workout with stored zone percentages.
4. Rowing: average rowing watts normalized to cycling watts, then power TSS.
5. Otherwise the provider's own TSS, if it sent one.

### Power-Based TSS

Used for cycling-style efforts when normalized power and FTP are available.

```text
IF = NP / FTP
TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
```

`normalized_power(power_series)` uses a 30-second rolling average, fourth-power weighting, mean, and fourth root. If fewer than 30 samples exist, it falls back to mean power.

### Pace-Based rTSS/tRSS

Used for running-style efforts with a threshold pace anchor.

```text
IF = threshold_pace_sec_km / avg_pace_sec_km
TSS = duration_hours * IF^2 * 100
```

The pace ratio is inverted because lower pace seconds/km is faster.

### Heart Rate Stress Score

Continuous HRSS uses Banister TRIMP normalized so one hour at lactate threshold HR is 100.

Inputs:

- 1-second HR array
- max HR
- resting HR
- threshold HR
- sport
- gender

TRIMP per minute is `HRR * 0.64 * exp(k * HRR)` with `k = 1.92` (male) or `1.67` (female), normalized by one hour at threshold HR.

Workouts are scored with `compute_hrss_from_zones()`, which estimates TRIMP from the stored time-in-zone percentages using zone midpoints from the current HR zone model (Z1's midpoint is never below resting HR; the open-ended Z5 uses `1.08 * threshold HR`). `compute_hrss_timeseries()` does the same from a 1-second HR array.

Strength sessions receive the neuromuscular multiplier (1.7).

## CTL, ATL, And TSB

### CTL

CTL is a 42-day EWMA of daily TSS:

```text
alpha = 1 - exp(-1 / 42)
CTL[i] = CTL[i-1] * (1 - alpha) + TSS[i] * alpha
```

The implementation average-seeds the first value from available history instead of cold-starting from zero.

### ATL

ATL uses the same EWMA implementation with a 7-day time constant.

### TSB

TSB is interpreted as fitness minus fatigue:

```text
TSB = CTL - ATL
```

CTL/ATL are stored per day in `tss_history` (`recalculate_tss_history`). Readiness uses today's CTL minus the prior day's ATL.

## Strain Score

ASTRAPHE strain is a 0-100 cardiovascular strain score, not the old 0-21 scale.

Zone coefficients:

| Zone | Coefficient |
|---:|---:|
| 0 | 0.0 |
| 1 | 0.5 |
| 2 | 1.0 |
| 3 | 2.5 |
| 4 | 5.0 |
| 5 | 8.0 |

Formula:

```text
raw = sum(zone_minutes[zone] * coefficient[zone])
raw *= 1.7 for strength
score = 100 * (1 - exp(-raw / 150))
```

The final score is rounded to an integer and clipped to 0-100.

### Day strain

A day's strain (`biometrics.strain_score`, source `astraphe`) runs the same formula over
the day's combined zone minutes (`backend/app/services/day_strain.py`):

```text
zone_minutes = workouts' zone minutes (from each workout's hr_zone_N_pct; strength x 1.7)
             + all-day heart rate minutes (heart_rate_series) outside every workout window,
               at or above 50% of max HR, classified by the athlete's zones
```

The 50%-of-max-HR floor keeps ordinary resting and everyday heart rate out: every zone
model starts Z1 at 0 bpm, so without it ~1,400 resting Z1 minutes would score as a
hard day. It's the same "counts as rest" line as the Heart rate screen's time in zone.
Days without an all-day series (no Garmin heart rate) get the workout-only value, as
before. Calibrated on 40 real days: +3 to +10 on typical training days, 0-3 on rest
days, +24 on a day with 200 active minutes outside workouts.

`day_strain()` also returns the workouts-only strain and the all-day minutes, so the UI can show the two parts. All-day samples pass through `drop_flatlines()` first (see Workout Detection).

Recomputed when a workout is saved or changed, when a day's biometrics are processed,
and on each Garmin sync pass (today's series grows through the day).
`POST /v1/sync/refresh-strain` recomputes every day with a workout or a series.

## Readiness Score

Readiness blends training form with recovery:

```text
tsb_component = 100 / (1 + exp(-0.055 * tsb))
readiness = 0.70 * recovery_score + 0.30 * tsb_component
```

If recovery score is unavailable, readiness falls back to the TSB-only sigmoid.

## Sleep Score

`calculate_astraphe_sleep_score()` is a strict 0-100 score based on:

- actual sleep minutes
- sleep need minutes
- REM minutes
- deep minutes
- awake minutes

It rewards meeting sleep need, penalizes restorative sleep below roughly 30%, and applies a fragmentation penalty for awake time.

## Sleep Need And Debt

Sleep need combines baseline sleep need, a strain tax, and carried sleep debt:

```text
strain_tax = (strain_score / 100) * 120 minutes
sleep_need = baseline_min + strain_tax + current_debt_min
```

Debt left after a night is the shortfall against that night's need, capped at 150 minutes, then paid down by that day's naps. 80% of it carries into the next night's need (20% decays per day), so at most 120 minutes are carried.

## Recovery Score

Recovery is a 0-100 score driven by autonomic signals, sleep, and recent load:

1. HRV and resting HR are converted into z-scores against an EWMA (span 30) of the last 30 readings (standard deviation floored at 1).
2. `ans_z = 0.6 * z_hrv + 0.4 * z_rhr` (RHR inverted: lower is better).
3. `ans = 100 / (1 + exp(-1.36 * (ans_z + 0.485)))`, so an average day scores about 66.
4. `load = clip(100 - 60 * prior_day_ATL / max_ATL_30d, 0, 100)`.
5. Dynamic weighting lets poor autonomic state dominate bad days.

Recovery is only recomputed when the day has both HRV and resting HR; otherwise the stored value is kept.

Weights:

- ANS below 40: 80% ANS, 15% sleep, 5% load.
- ANS above 70: 50% ANS, 35% sleep, 15% load.
- Middle: 65% ANS, 25% sleep, 10% load.

With no sleep recorded, the ANS and load weights are renormalized instead of scoring sleep as 0.

## Trend Helpers

`compute_ewma_stats()` calculates EWMA mean and EWMA standard deviation. `compute_z_score()` compares a latest value to a rolling EWMA baseline and safely returns zero z-score for degenerate variance.

`compute_hrv_trend()` compares the latest 7-day average to the previous 7-day average:

- `rising` when delta > 3 ms.
- `declining` when delta < -3 ms.
- `stable` otherwise.

## HR Zones

`hr_zones.compute_hr_zones()` builds five zones (Recovery, Endurance, Tempo, Threshold, VO2max+), each `[min, max)`:

| Method | Z1 / Z2 / Z3 / Z4 / Z5 lower bounds |
|---|---|
| `lthr` (Coggan) | 0 / 81% / 89% / 93% / 105% of threshold HR |
| `hrr` (Karvonen) | 0 / 60% / 70% / 80% / 90% of HR reserve, plus resting HR |
| `max_hr` | 0 / 60% / 70% / 80% / 90% of max HR |

The athlete's `hr_zone_method` is used when its inputs exist. Otherwise: LTHR if threshold HR was entered manually, then HRR if max and resting HR exist, then % of max HR.

## HR Anchors

- Max HR (`hr_anchors.ensure_hr_anchors`): when missing or previously estimated, the higher of the Tanaka age estimate and the highest workout max HR in the last year (120-230 bpm), saved with `max_hr_source = 'estimated'`. An entered value is never changed.
- Threshold HR: when missing, 83% of HRR plus RHR, saved as `estimated`.
- Resting HR: unless the athlete entered one (`resting_hr_source = 'manual'`), the profile's resting HR follows the mean of the last 42 days of daily readings once there are at least 3, saved as `measured`. Switching back to measured recomputes it immediately (`refresh_measured_resting_hr`).

## Workout Detection

`hr_activity_detection.py` finds unrecorded workouts in the all-day heart-rate series (Garmin 2-minute averages):

- A session is consecutive samples at or above 40% of HRR, totalling at least 10 minutes active and 10 minutes long.
- Cool spells of up to 6 minutes inside a session don't split it; a hole longer than 5 minutes (watch off) does. One warm-up sample at or above 30% HRR just before is included.
- No detection if max minus resting HR is under 30 bpm.
- A window overlapping a recorded workout (±5 minutes) is never saved; a recorded workout arriving later replaces overlapping detections.
- Detections are saved as workouts with source `hr_detected` (title "Detected activity"). One the athlete deletes is remembered in `hr_detection_dismissals` and not detected again.
- Before detection, `heart_rate_series.drop_flatlines()` removes runs of 10+ readings within ±1 bpm of the run's first reading (Garmin repeating its last value when the sensor loses contact). The chart still shows them.

## Other Helpers

- `estimate_max_hr(age_years)`: Tanaka formula, `208 - 0.7 * age`.
- `calculate_threshold_hr_est(max_hr, resting_hr)`: `83%` of HRR plus RHR.
- `calculate_weekly_tss_target(current_ctl)`: `7 * CTL` (the weekly TSS that holds CTL steady); 200 with no CTL.
- `calculate_rhr_baseline` / `calculate_hrv_baseline`: mean of the last 42 values.
- `normalize_rowing_watts(rowing_watts)`: rowing watts to cycling-equivalent watts with a 12% uplift.
