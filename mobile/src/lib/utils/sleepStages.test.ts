import { describe, expect, it } from 'vitest';
import { stageMinutes } from './sleepStages';

describe('stageMinutes', () => {
  it('splits time asleep by stage and adds up to the night', () => {
    // 2026-11-04: 495 min in bed, 468 asleep, Garmin deep 13.9 / REM 20.7 / light 65.5 / awake 5.5
    const m = stageMinutes(495, 468, { deep: 13.9, rem: 20.7, light: 65.5, awake: 5.5 });
    expect(m).toEqual({ awake: 27, light: 306, deep: 65, rem: 97 });
    expect(m.awake + m.light + m.deep + m.rem).toBe(495);
  });

  it('works out time asleep from the awake share when it is missing', () => {
    const m = stageMinutes(480, 0, { deep: 20, rem: 25, light: 55, awake: 10 });
    expect(m.awake).toBe(48);
    expect(m.light + m.deep + m.rem).toBe(432);
  });

  it('has no stage minutes without stage data', () => {
    expect(stageMinutes(480, 450, { deep: 0, rem: 0, light: 0, awake: 0 })).toEqual({ awake: 30, light: 0, deep: 0, rem: 0 });
  });
});
