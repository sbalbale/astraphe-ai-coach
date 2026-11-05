/**
 * Minutes per sleep stage for a night.
 *
 * Light / deep / REM percentages are shares of time *asleep* (Garmin's and WHOOP's add up to
 * ~100% without awake), so they split the minutes asleep; awake is the rest of the time in bed.
 * (Multiplying every percentage by time in bed overstated each stage: 522 min of stages for a
 * 495-min night.)
 */
export function stageMinutes(
  inBedMin: number,
  asleepMin: number,
  pct: { deep: number; rem: number; light: number; awake: number }
): { awake: number; light: number; deep: number; rem: number } {
  const inBed = Math.max(0, Number(inBedMin) || 0);
  const awakePct = Math.max(0, Number(pct.awake) || 0);
  const asleep = Number(asleepMin) > 0 ? Math.min(Number(asleepMin), inBed || Number(asleepMin)) : inBed * (1 - awakePct / 100);
  const parts = { deep: Math.max(0, Number(pct.deep) || 0), rem: Math.max(0, Number(pct.rem) || 0), light: Math.max(0, Number(pct.light) || 0) };
  const sum = parts.deep + parts.rem + parts.light;
  const share = (p: number) => (sum > 0 ? Math.round((asleep * p) / sum) : 0);
  return {
    awake: Math.round(inBed > 0 ? Math.max(0, inBed - asleep) : 0),
    light: share(parts.light),
    deep: share(parts.deep),
    rem: share(parts.rem)
  };
}
