import { describe, expect, it } from 'vitest';
import { sleepNeedParts, tonightSleepNeed } from './sleepNeed';

describe('sleepNeedParts', () => {
  it('splits the stored need into baseline, carried debt and strain', () => {
    // prev debt 60 → 48 carried; strain 50 → 60; 480 + 60 + 48 = 588
    expect(sleepNeedParts({ sleep_need_min: 588 }, { sleep_debt_min: 60, strain_score: 50 })).toEqual({
      total: 588, baseline: 480, strain: 60, debt: 48
    });
  });

  it('puts the remainder on strain so parts add up to the stored total', () => {
    const p = sleepNeedParts({ sleep_need_min: 530 }, null)!;
    expect(p.debt).toBe(0);
    expect(p.baseline + p.strain + p.debt).toBe(530);
  });

  it('never shows more debt than the need above baseline', () => {
    expect(sleepNeedParts({ sleep_need_min: 500 }, { sleep_debt_min: 120 })).toEqual({
      total: 500, baseline: 480, strain: 0, debt: 20
    });
  });

  it('is null without a stored need', () => {
    expect(sleepNeedParts({ sleep_need_min: null }, null)).toBeNull();
    expect(sleepNeedParts(undefined, null)).toBeNull();
  });
});

describe('tonightSleepNeed', () => {
  it('uses today strain and 80% of the remaining debt, capped at 2 h', () => {
    expect(tonightSleepNeed({ sleep_debt_min: 200, strain_score: 25 })).toEqual({
      total: 480 + 30 + 120, baseline: 480, strain: 30, debt: 120
    });
  });

  it('is null until last night sets the debt', () => {
    expect(tonightSleepNeed({ strain_score: 40 })).toBeNull();
  });
});
