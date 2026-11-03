import { format, isWithinInterval } from 'date-fns';
import { SvelteDate } from 'svelte/reactivity';
import type { Interval, Workout } from '../types/training';
import { api } from '../api';

function parseIsoLocal(yyyyMmDd: string): Date {
  // Create a local-time Date at noon to avoid timezone/DST edge shifting.
  // Expecting strict YYYY-MM-DD.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(yyyyMmDd);
  if (!m) return new Date(NaN);

  const year = Number(m[1]);
  const monthIndex = Number(m[2]) - 1;
  const day = Number(m[3]);
  return new Date(year, monthIndex, day, 12, 0, 0, 0);
}

function sortByDateThenTitle(a: Workout, b: Workout): number {
  // Dates are ISO YYYY-MM-DD so lexical order matches chronological order.
  if (a.date !== b.date) return a.date < b.date ? -1 : 1;
  if (a.title !== b.title) return a.title < b.title ? -1 : 1;
  // Deterministic final tie-breaker
  if (a.id !== b.id) return a.id < b.id ? -1 : 1;
  return 0;
}

function dedupeWorkoutsById(workouts: Workout[]): Workout[] {
  return Array.from(new Map(workouts.map((w) => [w.id, w])).values());
}

function withinInclusive(iso: string, startIso: string, endIso: string): boolean {
  const start = parseIsoLocal(startIso);
  const end = parseIsoLocal(endIso);
  const d = parseIsoLocal(iso);

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || Number.isNaN(d.getTime()))
    return false;

  const interval =
    start.getTime() <= end.getTime()
      ? { start, end }
      : { start: end, end: start };

  return isWithinInterval(d, interval);
}

export class TrainingState {
  workouts = $state.raw<Workout[]>([]);
  selectedDate = $state<string>(format(new SvelteDate(), 'yyyy-MM-dd'));
  isLoading = $state(false);
  /** Ignores stale HTTP completions when month/range changes quickly or effects overlap. */
  private fetchGeneration = 0;

  workoutsForSelectedDate = $derived.by(() =>
    this.workouts.filter((w) => w.date === this.selectedDate),
  );

  workoutsForCurrentMonth = $derived.by(() => {
    const monthPrefix = this.selectedDate.slice(0, 7); // YYYY-MM
    return this.workouts.filter((w) => w.date.slice(0, 7) === monthPrefix);
  });

  /** Forget the signed-in user's plan (sign-out / user switch). */
  reset() {
    this.fetchGeneration++; // drop any in-flight response
    this.workouts = [];
    this.isLoading = false;
    this.selectedDate = format(new SvelteDate(), 'yyyy-MM-dd');
  }

  async fetchWorkouts(startDate: string, endDate: string) {
    const generation = ++this.fetchGeneration;
    this.isLoading = true;
    const reqStart = startDate;
    const reqEnd = endDate;
    try {
      const realWorkouts = await api.getWorkouts(reqStart, reqEnd);
      if (generation !== this.fetchGeneration) return;
      const filtered = dedupeWorkoutsById(realWorkouts || [])
        .filter((w) => withinInclusive(w.date, reqStart, reqEnd))
        .slice()
        .sort(sortByDateThenTitle);
      this.workouts = filtered;
    } catch (error) {
      console.error('Failed to fetch workouts:', error);
    } finally {
      if (generation === this.fetchGeneration) {
        this.isLoading = false;
      }
    }
  }

  async injectAIWorkout(workout: Workout) {
    const idx = this.workouts.findIndex((w) => w.id === workout.id);
    const next = idx >= 0 ? this.workouts.toSpliced(idx, 1, workout) : [...this.workouts, workout];
    this.workouts = dedupeWorkoutsById(next).slice().sort(sortByDateThenTitle);

    const saved = await api.saveWorkout(workout);
    if (saved?.id && saved.id !== workout.id) {
      const j = this.workouts.findIndex((w) => w.id === workout.id);
      if (j >= 0) {
        this.workouts = dedupeWorkoutsById(
          this.workouts.toSpliced(j, 1, saved),
        )
          .slice()
          .sort(sortByDateThenTitle);
      }
    }
  }

  /**
   * Moves planned sessions to new dates (Move = one change, Swap = two that trade days),
   * saving each through the training-plans API, then refreshes the given range.
   * Returns false if any session is unknown or a save fails.
   */
  async rescheduleWorkouts(
    changes: { id: string; date: string }[],
    rangeStartIso: string,
    rangeEndIso: string
  ): Promise<boolean> {
    let ok = true;
    for (const change of changes) {
      const current = this.workouts.find((w) => w.id === change.id);
      if (!current) {
        ok = false;
        continue;
      }
      const saved = await api.saveWorkout({ ...current, date: change.date });
      if (!saved) ok = false;
    }
    await this.fetchWorkouts(rangeStartIso, rangeEndIso);
    return ok;
  }

  /** Marks a planned session done (or not done); refreshes the given date range view. */
  async setCompleted(id: string, completed: boolean, rangeStartIso: string, rangeEndIso: string): Promise<boolean> {
    const current = this.workouts.find((w) => w.id === id);
    if (!current) return false;
    // Optimistic, so the toggle answers at once; the refetch below settles it.
    this.workouts = this.workouts.map((w) => (w.id === id ? { ...w, completed } : w));
    const saved = await api.saveWorkout({ ...current, completed });
    await this.fetchWorkouts(rangeStartIso, rangeEndIso);
    return !!saved;
  }

  /** Removes a planned session from `training_plans`; refreshes the given date range view. */
  async deleteTrainingPlan(planId: string, rangeStartIso: string, rangeEndIso: string): Promise<boolean> {
    const ok = await api.deleteTrainingPlan(planId);
    if (ok) await this.fetchWorkouts(rangeStartIso, rangeEndIso);
    return ok;
  }
}

export const trainingStore = new TrainingState();
