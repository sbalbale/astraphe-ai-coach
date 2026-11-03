import { describe, expect, it } from 'vitest';
import { workoutDurationSecs } from './workoutDuration';

describe('workoutDurationSecs', () => {
  it('prefers duration_seconds, then duration_secs', () => {
    expect(workoutDurationSecs({ duration_seconds: 3600, duration_secs: 10 })).toBe(3600);
    expect(workoutDurationSecs({ duration_secs: '1800.7' })).toBe(1800);
  });

  it('falls back to the start/end span', () => {
    expect(
      workoutDurationSecs({ started_at: '2026-11-01T10:00:00Z', ended_at: '2026-11-01T10:45:00Z' })
    ).toBe(2700);
  });

  it('ignores zero or missing values and returns null when unknown', () => {
    expect(
      workoutDurationSecs({ duration_seconds: 0, started_at: '2026-11-01T10:00:00Z', ended_at: '2026-11-01T10:30:00Z' })
    ).toBe(1800);
    expect(workoutDurationSecs({ started_at: '2026-11-01T10:00:00Z' })).toBeNull();
    expect(workoutDurationSecs(null)).toBeNull();
  });
});
