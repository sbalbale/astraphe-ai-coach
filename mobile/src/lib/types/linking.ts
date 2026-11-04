/**
 * Planned session ↔ recorded workout links (backend: app/services/plan_matching.py).
 *
 * A planned session (`Workout` from /v1/training-plans) is:
 *  - done + linked       `completed` and `completed_workout_id` (`link_source` 'auto' | 'manual')
 *  - done, no workout    `completed` and no `completed_workout_id` (marked by hand)
 *  - not done            `!completed` (missed when its date is before today)
 */
import type { Workout } from './training';

export type LinkSource = 'auto' | 'manual';

/** Short summary of the recorded workout a session is linked to. */
export interface LinkedWorkout {
  id: string;
  title: string;
  sport: string;
  started_at: string;
  duration_seconds: number;
  tss: number | null;
}

/** How well a recorded workout fits a planned session. */
export interface LinkFit {
  /** Workout's local day minus the session's day (0 = same day, 1 = a day late). */
  day_offset: number;
  sport_ok: boolean;
  /** Actual / planned duration (null when the session has no duration). */
  duration_ratio: number | null;
  duration_ok: boolean;
  /** Would be matched automatically (same day, same sport, 50–150% of planned). */
  auto_ok: boolean;
  /** Lower is better. */
  score: number;
  /** "same day · similar duration", "1 day late · shorter than planned", "different sport". */
  reason: string;
}

/** A recorded workout near a planned session (GET /v1/training-plans/{id}/candidates). */
export interface WorkoutCandidate extends LinkedWorkout {
  fit: LinkFit;
  /** The athlete said "Not this one" (or unlinked it) for this session. */
  dismissed: boolean;
  linked_here: boolean;
  /** Another session this workout already completes (linking here needs `move`). */
  linked_to: { id: string; title: string; date: string } | null;
}

export interface PlanSummary {
  id: string;
  date: string;
  title: string;
  sport: string;
  duration_minutes: number;
  projected_tss: number;
  status: string;
  completed: boolean;
  link_source: LinkSource | null;
}

export interface PlanCandidates {
  plan: PlanSummary;
  /** Workouts within two days, same sport first, best fit first. */
  candidates: WorkoutCandidate[];
  /** "Looks like a match": one-tap link for a session that isn't done yet. */
  suggestion: WorkoutCandidate | null;
}

/** A planned session near a recorded workout (GET /v1/workouts/{id}/plan-link). */
export interface PlanCandidate extends PlanSummary {
  fit: LinkFit;
  linked_here: boolean;
  /** The session is already completed by a different workout. */
  has_other_workout: boolean;
  dismissed: boolean;
}

export interface WorkoutPlanLink {
  workout: LinkedWorkout;
  /** The session this workout completes, or null. */
  linked: PlanSummary | null;
  candidates: PlanCandidate[];
  suggestion: PlanCandidate | null;
}

export type LinkResult =
  | { ok: true; plan: Workout }
  | { ok: false; conflict: PlanSummary }
  | { ok: false; error: string };
