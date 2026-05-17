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

export function intervalsToSplits(intervals: RowingInterval[]): ActivitySplit[] {
  return intervals.map((iv) => ({
    split_number: iv.split_number,
    distance: iv.distance ?? 0,
    elapsed_time: iv.elapsed_time ?? 0,
    pace_seconds: iv.pace_per_500m,
    average_heartrate: iv.average_heartrate,
    average_watts: iv.average_watts,
    average_cadence: iv.average_cadence,
    average_speed: null,
  }));
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
