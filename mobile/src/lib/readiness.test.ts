import { describe, expect, it } from 'vitest';
import { baseline, formToScore, readinessBand, readinessBreakdown, sparkline } from './readiness';

describe('readinessBreakdown', () => {
  it('matches the backend blend: 0.7 × recovery + 0.3 × sigmoid(tsb)', () => {
    const b = readinessBreakdown(68, 6.2);
    expect(b.formScore).toBeCloseTo(100 / (1 + Math.exp(-0.055 * 6.2)), 6);
    expect(b.recoveryPart).toBeCloseTo(47.6, 6);
    expect(b.formPart).toBeCloseTo(b.formScore * 0.3, 6);
    expect(b.total).toBe(Math.round(47.6 + b.formScore * 0.3));
  });

  it('falls back to form only without a recovery score', () => {
    const b = readinessBreakdown(null, 0);
    expect(b.recovery).toBeNull();
    expect(b.recoveryPart).toBeNull();
    expect(b.total).toBe(50);
    expect(readinessBreakdown(0, 0).recovery).toBeNull();
  });

  it('treats a non-finite tsb as neutral form', () => {
    expect(readinessBreakdown(60, Number.NaN).formScore).toBe(50);
  });
});

describe('formToScore / readinessBand', () => {
  it('is 50 at zero TSB and monotonic', () => {
    expect(formToScore(0)).toBe(50);
    expect(formToScore(20)).toBeGreaterThan(formToScore(-20));
  });

  it('bands at 34 and 67', () => {
    expect(readinessBand(33)).toBe('low');
    expect(readinessBand(34)).toBe('mid');
    expect(readinessBand(66)).toBe('mid');
    expect(readinessBand(67)).toBe('high');
  });
});

describe('baseline', () => {
  it('ignores gaps and returns mean and sample sd', () => {
    const b = baseline([2, null, 4, undefined, 6]);
    expect(b?.mean).toBe(4);
    expect(b?.sd).toBe(2);
    expect(baseline([5])).toEqual({ mean: 5, sd: 0 });
    expect(baseline([null])).toBeNull();
  });
});

describe('sparkline', () => {
  it('maps values into the box with the baseline band', () => {
    const s = sparkline([10, 20, null, 30], { mean: 20, sd: 5 });
    expect(s?.points.split(' ')).toHaveLength(3);
    expect(s?.points.startsWith('2,')).toBe(true);
    expect(s?.bandH).toBeGreaterThan(2);
  });

  it('handles a flat series and missing baseline', () => {
    const s = sparkline([5, 5, 5], null);
    expect(s?.bandH).toBe(0);
    expect(s?.points.split(' ')).toHaveLength(3);
  });

  it('needs at least two points', () => {
    expect(sparkline([1, null], null)).toBeNull();
  });
});
