import { describe, expect, it } from 'vitest';
import {
  boundedScoreCssColor,
  boundedScoreTone,
  cssVarFor,
  formCssColor,
  formTone,
  getBoundedScoreColor,
  getFormColor,
  getSleepDebtColor,
  getWeeklyLoadDeltaColor,
  getZScoreColor,
  NEUTRAL_CSS_COLOR,
  NEUTRAL_TEXT_CLASS,
  sleepDebtCssColor,
  sleepDebtTone,
  strainCssColor,
  strainTextClass,
  strainTone,
  textClassFor,
  tssToneFromStrain,
  weeklyLoadDeltaTone,
  workoutOutputTextClass,
  zScoreCssColor,
  zScoreTone
} from './scoreColors';

describe('bounded score tone (0-100 rule of thirds)', () => {
  it('non-numeric returns muted', () => {
    expect(boundedScoreTone('n/a')).toBe('muted');
    // Number(null) === 0, which is a valid (finite) score, so it is NOT "non-numeric"
    // for toNumber()'s purposes -- only undefined/NaN-producing input hits the null branch.
    expect(boundedScoreTone(undefined)).toBe('muted');
  });
  it('normal orientation: high=teal, mid=amber, low=red', () => {
    expect(boundedScoreTone(80)).toBe('teal');
    expect(boundedScoreTone(50)).toBe('amber');
    expect(boundedScoreTone(20)).toBe('red');
  });
  it('inverted orientation flips bands', () => {
    expect(boundedScoreTone(80, true)).toBe('red');
    expect(boundedScoreTone(50, true)).toBe('amber');
    expect(boundedScoreTone(20, true)).toBe('teal');
  });
  it('accepts numeric strings', () => {
    expect(boundedScoreTone('80')).toBe('teal');
  });
  it('getBoundedScoreColor / boundedScoreCssColor map to classes/vars', () => {
    expect(getBoundedScoreColor(80)).toBe('text-astraphe-teal');
    expect(boundedScoreCssColor(80)).toBe('var(--teal)');
  });
});

describe('cssVarFor / textClassFor', () => {
  it('maps each tone', () => {
    expect(cssVarFor('red')).toBe('var(--red)');
    expect(textClassFor('blue')).toBe('text-astraphe-blue');
  });
});

describe('formTone (TSB)', () => {
  it('non-numeric returns muted', () => {
    expect(formTone(undefined)).toBe('muted');
  });
  it('bands', () => {
    expect(formTone(30)).toBe('blue');
    expect(formTone(0)).toBe('teal');
    expect(formTone(-20)).toBe('amber');
    expect(formTone(-40)).toBe('red');
  });
  it('getFormColor / formCssColor', () => {
    expect(getFormColor(30)).toBe('text-astraphe-blue');
    expect(formCssColor(30)).toBe('var(--blue)');
  });
});

describe('sleepDebtTone', () => {
  it('non-numeric returns muted', () => {
    expect(sleepDebtTone('x')).toBe('muted');
  });
  it('bands', () => {
    expect(sleepDebtTone(30)).toBe('teal');
    expect(sleepDebtTone(60)).toBe('amber');
    expect(sleepDebtTone(120)).toBe('red');
  });
  it('getSleepDebtColor / sleepDebtCssColor', () => {
    expect(getSleepDebtColor(30)).toBe('text-astraphe-teal');
    expect(sleepDebtCssColor(30)).toBe('var(--teal)');
  });
});

describe('zScoreTone', () => {
  it('non-numeric returns muted', () => {
    expect(zScoreTone(undefined)).toBe('muted');
  });
  it('normal orientation bands', () => {
    expect(zScoreTone(0)).toBe('teal');
    expect(zScoreTone(-1)).toBe('amber');
    expect(zScoreTone(-2)).toBe('red');
  });
  it('inverted orientation negates before banding', () => {
    expect(zScoreTone(0.2, true)).toBe('teal');
    expect(zScoreTone(1, true)).toBe('amber');
    expect(zScoreTone(2, true)).toBe('red');
  });
  it('getZScoreColor / zScoreCssColor', () => {
    expect(getZScoreColor(0)).toBe('text-astraphe-teal');
    expect(zScoreCssColor(0)).toBe('var(--teal)');
  });
});

describe('weeklyLoadDeltaTone', () => {
  it('non-numeric returns muted', () => {
    expect(weeklyLoadDeltaTone('x')).toBe('muted');
  });
  it('bands', () => {
    expect(weeklyLoadDeltaTone(0.4)).toBe('red');
    expect(weeklyLoadDeltaTone(0.2)).toBe('amber');
    expect(weeklyLoadDeltaTone(-0.2)).toBe('teal');
    expect(weeklyLoadDeltaTone(0)).toBe('muted');
  });
  it('getWeeklyLoadDeltaColor', () => {
    expect(getWeeklyLoadDeltaColor(0.4)).toBe('text-astraphe-red');
  });
});

describe('backwards-compat aliases', () => {
  it('strainTone/strainTextClass/strainCssColor mirror bounded score fns', () => {
    expect(strainTone(80)).toBe(boundedScoreTone(80));
    expect(strainTextClass(80)).toBe(getBoundedScoreColor(80));
    expect(strainCssColor(80)).toBe(boundedScoreCssColor(80));
  });
  it('tssToneFromStrain uses inverted banding', () => {
    expect(tssToneFromStrain(80)).toBe('red');
  });
  it('workoutOutputTextClass uses inverted banding', () => {
    expect(workoutOutputTextClass(80)).toBe('text-astraphe-red');
  });
});

describe('neutral constants', () => {
  it('are stable', () => {
    expect(NEUTRAL_TEXT_CLASS).toBe('text-text0');
    expect(NEUTRAL_CSS_COLOR).toBe('var(--text0)');
  });
});
