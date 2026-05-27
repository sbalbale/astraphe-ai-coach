import { describe, expect, it } from 'vitest';
import {
  getTimeOfDayGreeting,
  getTimeOfDayPeriod,
  normalizeLeadingTimeOfDayGreeting,
  stripLeadingTimeOfDayGreeting
} from './greeting';

describe('time-of-day greetings', () => {
  it('buckets local hours into morning, afternoon, and evening', () => {
    expect(getTimeOfDayPeriod(new Date(2026, 4, 26, 8))).toBe('morning');
    expect(getTimeOfDayPeriod(new Date(2026, 4, 26, 15))).toBe('afternoon');
    expect(getTimeOfDayPeriod(new Date(2026, 4, 26, 21))).toBe('evening');
  });

  it('formats the greeting from the local period', () => {
    expect(getTimeOfDayGreeting(new Date(2026, 4, 26, 15))).toBe('Good afternoon');
  });

  it('normalizes stale leading greetings without changing the rest of the text', () => {
    expect(normalizeLeadingTimeOfDayGreeting('Good morning, Sean. Ready?', new Date(2026, 4, 26, 15))).toBe(
      'Good afternoon, Sean. Ready?'
    );
  });

  it('strips leading greetings from summary text', () => {
    expect(stripLeadingTimeOfDayGreeting('Good morning, your recovery is 82%.')).toBe('Your recovery is 82%.');
  });
});
