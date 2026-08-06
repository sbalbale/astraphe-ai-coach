import { describe, expect, it } from 'vitest';
import { formatDist, formatHR, formatPace } from './formatters';

describe('formatPace', () => {
  it('formats seconds as m:ss', () => {
    expect(formatPace(90)).toBe('1:30');
    expect(formatPace(65.6)).toBe('1:06');
  });

  it('returns em dash for null', () => {
    expect(formatPace(null)).toBe('—');
  });
});

describe('formatDist', () => {
  it('rounds meters', () => {
    expect(formatDist(1000.4)).toBe('1000m');
  });

  it('returns em dash for null', () => {
    expect(formatDist(null)).toBe('—');
  });
});

describe('formatHR', () => {
  it('rounds bpm', () => {
    expect(formatHR(150.6)).toBe('151');
  });

  it('returns em dash for null', () => {
    expect(formatHR(null)).toBe('—');
  });
});
