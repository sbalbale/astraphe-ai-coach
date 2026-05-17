import type { ActivityLap, RowingInterval } from '$lib/services/activityService';
import {
  coercePaceSport,
  paceSecondsFromVelocity,
  type Units,
} from '$lib/utils/paceChart';

export type ActivitySplit = {
  split_number: number;
  distance: number;
  elapsed_time: number;
  pace_seconds: number | null;
  average_heartrate: number | null;
  average_watts: number | null;
  average_cadence: number | null;
  average_speed: number | null;
};

const METERS_PER_MILE = 1609.344;

export function paceFromDistanceTime(
  distM: number,
  elapsedSec: number,
  sport: string,
  units: Units = 'metric'
): number | null {
  if (distM <= 0 || elapsedSec <= 0) return null;
  const kind = coercePaceSport(sport);
  if (kind === 'row') return (elapsedSec / distM) * 500;
  if (kind === 'run') {
    const segM = units === 'imperial' ? METERS_PER_MILE : 1000;
    return (elapsedSec / distM) * segM;
  }
  return null;
}

/** Lap/split speed in m/s from Strava field, distance/time, or rowing pace. */
export function splitAverageSpeedMps(split: ActivitySplit): number | null {
  if (split.average_speed != null && split.average_speed > 0) {
    return split.average_speed;
  }
  if (split.distance > 0 && split.elapsed_time > 0) {
    return split.distance / split.elapsed_time;
  }
  if (split.pace_seconds != null && split.pace_seconds > 0) {
    return 500 / split.pace_seconds;
  }
  return null;
}

export function averageSpeedFromSplits(splits: ActivitySplit[]): number | null {
  const speeds = splits
    .map(splitAverageSpeedMps)
    .filter((v): v is number => v != null && Number.isFinite(v) && v > 0);
  if (speeds.length > 0) {
    return speeds.reduce((a, b) => a + b, 0) / speeds.length;
  }
  const totalDist = splits.reduce((s, i) => s + (i.distance ?? 0), 0);
  const totalTime = splits.reduce((s, i) => s + (i.elapsed_time ?? 0), 0);
  if (totalDist > 0 && totalTime > 0) return totalDist / totalTime;
  return null;
}

export function intervalsToSplits(intervals: RowingInterval[]): ActivitySplit[] {
  return intervals.map((iv) => {
    const pace = iv.pace_per_500m;
    const speed =
      pace != null && pace > 0
        ? 500 / pace
        : iv.distance && iv.elapsed_time
          ? iv.distance / iv.elapsed_time
          : null;
    return {
      split_number: iv.split_number,
      distance: iv.distance ?? 0,
      elapsed_time: iv.elapsed_time ?? 0,
      pace_seconds: pace,
      average_heartrate: iv.average_heartrate,
      average_watts: iv.average_watts,
      average_cadence: iv.average_cadence,
      average_speed: speed,
    };
  });
}

export function lapsToSplits(
  laps: ActivityLap[],
  sport: string,
  units: Units = 'metric'
): ActivitySplit[] {
  return laps.map((lap, i) => {
    const speed = lap.average_speed;
    let pace: number | null = null;
    if (speed != null && speed > 0) {
      pace = paceSecondsFromVelocity(speed, sport, units);
    }
    if (pace == null && lap.distance > 0 && lap.elapsed_time > 0) {
      pace = paceFromDistanceTime(lap.distance, lap.elapsed_time, sport, units);
    }
    return {
      split_number: lap.lap_index ?? i + 1,
      distance: lap.distance ?? 0,
      elapsed_time: lap.elapsed_time ?? 0,
      pace_seconds: pace,
      average_heartrate: lap.average_heartrate,
      average_watts: lap.average_watts,
      average_cadence: lap.average_cadence,
      average_speed: speed,
    };
  });
}

export function averagePaceFromSplits(
  splits: ActivitySplit[],
  sport: string,
  units: Units = 'metric'
): number | null {
  const totalDist = splits.reduce((s, i) => s + (i.distance ?? 0), 0);
  const totalTime = splits.reduce((s, i) => s + (i.elapsed_time ?? 0), 0);
  return paceFromDistanceTime(totalDist, totalTime, sport, units);
}

export function splitsTableTitle(sport: string): string {
  const kind = coercePaceSport(sport);
  if (kind === 'row') return '500m Intervals';
  return 'Laps';
}

export function splitsLabel(sport: string): string {
  const kind = coercePaceSport(sport);
  return kind === 'row' ? 'Split' : 'Lap';
}
