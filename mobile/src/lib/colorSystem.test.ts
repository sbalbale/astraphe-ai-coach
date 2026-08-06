import { describe, expect, it } from 'vitest';
import { boundedScoreCssColor, getBoundedScoreColor } from './colorSystem';

describe('colorSystem re-exports', () => {
  it('re-exports getBoundedScoreColor from scoreColors', () => {
    expect(getBoundedScoreColor(80)).toBe('text-astraphe-teal');
  });
  it('re-exports boundedScoreCssColor from scoreColors', () => {
    expect(boundedScoreCssColor(80)).toBe('var(--teal)');
  });
});
