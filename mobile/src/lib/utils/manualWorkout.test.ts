import { describe, expect, it } from 'vitest';
import { isManualWorkout, workoutEffort, workoutNotes } from './manualWorkout';

describe('isManualWorkout', () => {
  it('is true for a hand-logged workout', () => {
    expect(isManualWorkout({ source: 'manual' })).toBe(true);
    expect(isManualWorkout({ source: 'manual', primary_source: 'manual' })).toBe(true);
  });
  it('is false once a device import has merged in or for synced workouts', () => {
    expect(isManualWorkout({ source: 'manual', primary_source: 'garmin' })).toBe(false);
    expect(isManualWorkout({ source: 'manual', garmin_activity_id: 123 })).toBe(false);
    expect(isManualWorkout({ source: 'strava', strava_activity_id: 1 })).toBe(false);
    expect(isManualWorkout(null)).toBe(false);
  });
});

describe('workoutEffort / workoutNotes', () => {
  it('reads an RPE in range and ignores junk', () => {
    expect(workoutEffort({ rpe: 7 })).toBe(7);
    expect(workoutEffort({ rpe: 0 })).toBeNull();
    expect(workoutEffort({ rpe: 42 })).toBeNull();
    expect(workoutEffort({})).toBeNull();
  });
  it('reads trimmed notes', () => {
    expect(workoutNotes({ notes: '  Squat 4x5 ' })).toBe('Squat 4x5');
    expect(workoutNotes({ notes: '   ' })).toBeNull();
  });
});
