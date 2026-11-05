import { describe, expect, it } from 'vitest';
import { powerBand } from './powerBand';
import { targetWindow } from './planVsActual';

describe('powerBand', () => {
  it('is ±5% FTP rounded to 5 W', () => {
    expect(powerBand(280, 65)).toEqual([170, 195]);
    expect(powerBand(280, 55)).toEqual([140, 170]);
  });

  it('is the same window planned vs actual judges against', () => {
    const w = targetWindow({ name: 'Main', duration_minutes: 45, target_power_percent_ftp: 65 }, 'power', 280, []);
    expect([w?.lo, w?.hi]).toEqual(powerBand(280, 65));
  });
});
