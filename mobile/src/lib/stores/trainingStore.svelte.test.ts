import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getWorkoutsMock = vi.fn();
const saveWorkoutMock = vi.fn();
const deleteTrainingPlanMock = vi.fn();
vi.mock('../api', () => ({
  api: {
    getWorkouts: (...args: unknown[]) => getWorkoutsMock(...args),
    saveWorkout: (...args: unknown[]) => saveWorkoutMock(...args),
    deleteTrainingPlan: (...args: unknown[]) => deleteTrainingPlanMock(...args)
  }
}));

import { trainingStore } from './trainingStore.svelte';
import type { Workout } from '$lib/types/training';

function workout(overrides: Partial<Workout> = {}): Workout {
  return {
    id: 'w1',
    date: '2026-05-20',
    title: 'Tempo Run',
    sport: 'run',
    primary_zone: 'Tempo',
    duration_minutes: 45,
    projected_tss: 60,
    description: '',
    structure: [],
    completed: false,
    ...overrides
  };
}

beforeEach(() => {
  getWorkoutsMock.mockReset();
  saveWorkoutMock.mockReset();
  deleteTrainingPlanMock.mockReset();
  trainingStore.workouts = [];
  trainingStore.isLoading = false;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('fetchWorkouts', () => {
  it('dedupes, filters to the requested range, and sorts by date/title/id', async () => {
    getWorkoutsMock.mockResolvedValue([
      workout({ id: 'a', date: '2026-05-22', title: 'B' }),
      workout({ id: 'b', date: '2026-05-21', title: 'A' }),
      workout({ id: 'a', date: '2026-05-22', title: 'B' }), // duplicate id -> deduped
      workout({ id: 'c', date: '2026-01-01', title: 'Out of range' }) // filtered out
    ]);
    await trainingStore.fetchWorkouts('2026-05-20', '2026-05-25');
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['b', 'a']);
    expect(trainingStore.isLoading).toBe(false);
  });

  it('handles a reversed date range (start after end)', async () => {
    getWorkoutsMock.mockResolvedValue([workout({ id: 'a', date: '2026-05-21' })]);
    await trainingStore.fetchWorkouts('2026-05-25', '2026-05-20');
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['a']);
  });

  it('treats a null/undefined API response as an empty list', async () => {
    getWorkoutsMock.mockResolvedValue(null);
    await trainingStore.fetchWorkouts('2026-05-20', '2026-05-25');
    expect(trainingStore.workouts).toEqual([]);
  });

  it('sets isLoading false and logs on failure', async () => {
    getWorkoutsMock.mockRejectedValue(new Error('network down'));
    await trainingStore.fetchWorkouts('2026-05-20', '2026-05-25');
    expect(trainingStore.isLoading).toBe(false);
  });

  it('ignores a stale completion when a newer fetch has started', async () => {
    let resolveFirst: (v: unknown) => void;
    getWorkoutsMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        })
    );
    const first = trainingStore.fetchWorkouts('2026-05-01', '2026-05-31');

    getWorkoutsMock.mockResolvedValueOnce([workout({ id: 'second', date: '2026-06-10' })]);
    const second = trainingStore.fetchWorkouts('2026-06-01', '2026-06-30');
    await second;

    resolveFirst!([workout({ id: 'first', date: '2026-05-10' })]);
    await first;

    // The stale (first) fetch's completion must not clobber the newer result.
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['second']);
  });
});

describe('workoutsForSelectedDate / workoutsForCurrentMonth', () => {
  it('filters workouts by the selected date', async () => {
    getWorkoutsMock.mockResolvedValue([
      workout({ id: 'a', date: '2026-05-20' }),
      workout({ id: 'b', date: '2026-05-21' })
    ]);
    await trainingStore.fetchWorkouts('2026-05-01', '2026-05-31');
    trainingStore.selectedDate = '2026-05-20';
    expect(trainingStore.workoutsForSelectedDate.map((w) => w.id)).toEqual(['a']);
  });

  it('filters workouts by the selected month', async () => {
    getWorkoutsMock.mockResolvedValue([
      workout({ id: 'a', date: '2026-05-20' }),
      workout({ id: 'b', date: '2026-06-01' })
    ]);
    await trainingStore.fetchWorkouts('2026-01-01', '2026-12-31');
    trainingStore.selectedDate = '2026-05-15';
    expect(trainingStore.workoutsForCurrentMonth.map((w) => w.id)).toEqual(['a']);
  });
});

describe('injectAIWorkout', () => {
  it('adds a new workout and persists it', async () => {
    trainingStore.workouts = [];
    saveWorkoutMock.mockResolvedValue({ id: 'w1' });
    await trainingStore.injectAIWorkout(workout({ id: 'w1' }));
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['w1']);
    expect(saveWorkoutMock).toHaveBeenCalled();
  });

  it('replaces an existing workout with the same id', async () => {
    trainingStore.workouts = [workout({ id: 'w1', title: 'Old' })];
    saveWorkoutMock.mockResolvedValue({ id: 'w1' });
    await trainingStore.injectAIWorkout(workout({ id: 'w1', title: 'New' }));
    expect(trainingStore.workouts).toHaveLength(1);
    expect(trainingStore.workouts[0].title).toBe('New');
  });

  it('reconciles a server-assigned id once the save resolves', async () => {
    trainingStore.workouts = [];
    saveWorkoutMock.mockResolvedValue({ id: 'server-id' });
    await trainingStore.injectAIWorkout(workout({ id: 'temp-id' }));
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['server-id']);
  });

  it('leaves the optimistic entry when save returns the same id', async () => {
    trainingStore.workouts = [];
    saveWorkoutMock.mockResolvedValue({ id: 'w1' });
    await trainingStore.injectAIWorkout(workout({ id: 'w1' }));
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['w1']);
  });

  it('leaves the optimistic entry when save returns null', async () => {
    trainingStore.workouts = [];
    saveWorkoutMock.mockResolvedValue(null);
    await trainingStore.injectAIWorkout(workout({ id: 'temp-id' }));
    expect(trainingStore.workouts.map((w) => w.id)).toEqual(['temp-id']);
  });
});

describe('deleteTrainingPlan', () => {
  it('refreshes the view on successful delete', async () => {
    deleteTrainingPlanMock.mockResolvedValue(true);
    getWorkoutsMock.mockResolvedValue([]);
    const result = await trainingStore.deleteTrainingPlan('plan-1', '2026-05-01', '2026-05-31');
    expect(result).toBe(true);
    expect(getWorkoutsMock).toHaveBeenCalledWith('2026-05-01', '2026-05-31');
  });

  it('does not refresh when delete fails', async () => {
    deleteTrainingPlanMock.mockResolvedValue(false);
    const result = await trainingStore.deleteTrainingPlan('plan-1', '2026-05-01', '2026-05-31');
    expect(result).toBe(false);
    expect(getWorkoutsMock).not.toHaveBeenCalled();
  });
});
