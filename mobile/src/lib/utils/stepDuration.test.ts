import { describe, expect, it } from 'vitest';
import { formatStepClock, formatStepDuration } from './stepDuration';

describe('formatStepDuration', () => {
  it('shows minutes and seconds, never rounding to whole minutes', () => {
    expect(formatStepDuration(1.5)).toBe('1′30″');
    expect(formatStepDuration(0.75)).toBe('0′45″');
    expect(formatStepDuration(1)).toBe('1′');
    expect(formatStepDuration(15)).toBe('15′');
    expect(formatStepDuration(90)).toBe('1h30');
    expect(formatStepDuration(120)).toBe('2h');
  });
});

describe('formatStepClock', () => {
  it('keeps the seconds', () => {
    expect(formatStepClock(1.5)).toBe('01:30');
    expect(formatStepClock(16.5)).toBe('16:30');
    expect(formatStepClock(0)).toBe('00:00');
  });
});
