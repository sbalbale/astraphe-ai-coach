/** GET /v1/biometrics/heart-rate (backend: heart_rate_series.build_heart_rate_day). */
export type HeartRateDayWorkout = {
  id: string;
  source: string;
  sport: string;
  title: string | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  strain_score: number | null;
  tss: number | null;
  /** Found in the all-day series rather than recorded (source "hr_detected"). */
  detected: boolean;
};

export type HeartRateDay = {
  date: string;
  /** UTC bounds of the athlete's local day. */
  day_start: string;
  day_end: string;
  source: string | null;
  /** Typical spacing between samples (Garmin: 120 s averages). */
  interval_sec: number | null;
  resting_hr: number | null;
  min_hr: number | null;
  max_hr: number | null;
  avg_hr: number | null;
  samples: { t: string; bpm: number }[];
  workouts: HeartRateDayWorkout[];
  sleep: { started_at: string; ended_at: string; is_nap: boolean }[];
  resting_hr_history: { date: string; resting_hr: number }[];
};
