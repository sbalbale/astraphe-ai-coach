import { describe, expect, it } from 'vitest';
import { format } from 'date-fns';
import { localDay } from './localDay';

describe('localDay', () => {
  it('uses the local calendar day of a timestamp, not the UTC one', () => {
    const ts = '2026-11-03T01:30:00Z'; // evening of Nov 2 in the Americas
    expect(localDay(ts)).toBe(format(new Date(ts), 'yyyy-MM-dd'));
  });
  it('keeps plain dates and rejects junk', () => {
    expect(localDay('2026-11-02')).toBe('2026-11-02');
    expect(localDay('')).toBe('');
    expect(localDay(null)).toBe('');
    expect(localDay('nope')).toBe('');
  });
});
