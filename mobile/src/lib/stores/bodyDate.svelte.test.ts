import { beforeEach, describe, expect, it } from 'vitest';
import { bodyDate, rememberBodyDate, resetBodyDate } from './bodyDate.svelte';

describe('bodyDate', () => {
  beforeEach(() => resetBodyDate());

  it('remembers a past day', () => {
    rememberBodyDate('2026-10-20', '2026-11-02');
    expect(bodyDate.value).toBe('2026-10-20');
  });

  it('stores today (or later) as null so it follows the calendar', () => {
    rememberBodyDate('2026-10-20', '2026-11-02');
    rememberBodyDate('2026-11-02', '2026-11-02');
    expect(bodyDate.value).toBeNull();
    rememberBodyDate('2026-11-05', '2026-11-02');
    expect(bodyDate.value).toBeNull();
  });

  it('ignores malformed values', () => {
    rememberBodyDate('2026-10-20', '2026-11-02');
    rememberBodyDate('Invalid Date', '2026-11-02');
    expect(bodyDate.value).toBe('2026-10-20');
  });
});
