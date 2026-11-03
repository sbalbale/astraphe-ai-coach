import { describe, expect, it } from 'vitest';
import { passwordStrength } from './passwordStrength';

describe('passwordStrength', () => {
  it('is empty for no input', () => {
    expect(passwordStrength('', 8)).toEqual({ score: 0, label: '', tone: 'none' });
  });

  it('flags passwords under the minimum', () => {
    expect(passwordStrength('abc12', 8)).toMatchObject({ score: 0, label: 'Too short', tone: 'red' });
  });

  it('respects the minimum it is given', () => {
    expect(passwordStrength('abc123', 6).score).toBeGreaterThan(0);
    expect(passwordStrength('abc123', 8).score).toBe(0);
  });

  it('rates a short single-class password weak', () => {
    expect(passwordStrength('abcdefgh', 8)).toMatchObject({ score: 1, label: 'Weak' });
  });

  it('does not rate a long single-class password above fair', () => {
    expect(passwordStrength('aaaaaaaaaaaaaaaaaaaa', 8).score).toBe(2);
  });

  it('rates length plus variety strong', () => {
    expect(passwordStrength('Tempo-Run-2026', 8)).toMatchObject({ score: 4, label: 'Very strong', tone: 'green' });
    expect(passwordStrength('Tempo2026', 8)).toMatchObject({ score: 2, label: 'Fair', tone: 'amber' });
    expect(passwordStrength('TempoRun2026', 8)).toMatchObject({ score: 3, label: 'Strong' });
  });
});
