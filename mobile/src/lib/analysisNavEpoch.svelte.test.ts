import { describe, expect, it } from 'vitest';
import { analysisNavEpoch } from './analysisNavEpoch.svelte';

describe('analysisNavEpoch', () => {
  it('starts at 0 and increments on bump', () => {
    const start = analysisNavEpoch.epoch;
    analysisNavEpoch.bump();
    expect(analysisNavEpoch.epoch).toBe(start + 1);
    analysisNavEpoch.bump();
    expect(analysisNavEpoch.epoch).toBe(start + 2);
  });
});
