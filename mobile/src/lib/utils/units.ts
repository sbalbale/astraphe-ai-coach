export type Units = 'metric' | 'imperial';

export function normalizeUnits(value: unknown): Units {
  if (typeof value !== 'string') return 'metric';
  return value.toLowerCase().includes('imperial') ? 'imperial' : 'metric';
}

const LB_PER_KG = 2.2046226218487757;
const CM_PER_IN = 2.54;

export function roundToStep(value: number, step: number): number {
  const v = Number(value);
  const s = Number(step);
  if (!Number.isFinite(v) || !Number.isFinite(s) || s <= 0) return 0;
  return Math.round(v / s) * s;
}

export function kgToLb(kg: number): number {
  const v = Number(kg);
  if (!Number.isFinite(v)) return 0;
  return v * LB_PER_KG;
}

export function kgToLbRoundedHalf(kg: number): number {
  return roundToStep(kgToLb(kg), 0.5);
}

export function lbToKg(lb: number): number {
  const v = Number(lb);
  if (!Number.isFinite(v)) return 0;
  return v / LB_PER_KG;
}

export const KM_PER_MILE = 1.609344;
export const METERS_PER_MILE = 1609.344;
const FEET_PER_METER = 3.280839895;

/** Lap / segment distance: rowing stays meters; run & bike use profile units. */
export function formatSegmentDistance(
  meters: number | null | undefined,
  units: Units,
  sport = ''
): string {
  if (meters == null || !Number.isFinite(meters)) return '—';
  const s = (sport || '').toLowerCase();
  if (s === 'row' || s === 'rowing') {
    return `${Math.round(meters)}m`;
  }
  return formatWorkoutDistance(meters, units, sport);
}

export function elevationUnitLabel(units: Units): string {
  return units === 'imperial' ? 'ft' : 'm';
}

/** Convert stored altitude (meters) for chart scale / display. */
export function elevationFromMeters(meters: number, units: Units): number {
  if (!Number.isFinite(meters)) return 0;
  return units === 'imperial' ? meters * FEET_PER_METER : meters;
}

export function formatElevationMeters(meters: number | null | undefined, units: Units): string {
  if (meters == null || !Number.isFinite(meters)) return '—';
  if (units === 'imperial') {
    return `${Math.round(meters * FEET_PER_METER)} ft`;
  }
  return `${Math.round(meters)} m`;
}

/** Total workout distance for run / bike (and other non-row sports). */
export function formatWorkoutDistance(
  meters: number | null | undefined,
  units: Units,
  sport = ''
): string {
  if (meters == null || !Number.isFinite(meters)) return '—';
  const s = (sport || '').toLowerCase();
  if (s === 'row' || s === 'rowing') {
    return `${Math.round(meters)}m`;
  }
  if (units === 'imperial') {
    return `${(meters / METERS_PER_MILE).toFixed(2)} mi`;
  }
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${Math.round(meters)} m`;
}

/** Value + unit label for split UI (e.g. strain page). */
export function workoutDistanceParts(
  meters: number | null | undefined,
  units: Units,
  sport = ''
): { value: string; unit: string } {
  if (meters == null || !Number.isFinite(meters)) return { value: '—', unit: '' };
  const s = (sport || '').toLowerCase();
  if (s === 'row' || s === 'rowing') {
    return { value: String(Math.round(meters)), unit: 'm' };
  }
  if (units === 'imperial') {
    return { value: (meters / METERS_PER_MILE).toFixed(2), unit: 'mi' };
  }
  if (meters >= 1000) {
    return { value: (meters / 1000).toFixed(2), unit: 'km' };
  }
  return { value: String(Math.round(meters)), unit: 'm' };
}

export function parsePaceToSeconds(pace: string): number | null {
  // Accepts m:ss or mm:ss (also supports leading/trailing spaces).
  const s = String(pace || '').trim();
  const m = /^(\d+):(\d{2})$/.exec(s);
  if (!m) return null;
  const mins = Number(m[1]);
  const secs = Number(m[2]);
  if (!Number.isFinite(mins) || !Number.isFinite(secs)) return null;
  if (secs < 0 || secs >= 60 || mins < 0) return null;
  return mins * 60 + secs;
}

export function formatSecondsToPace(totalSeconds: number): string {
  const s = Math.max(0, Math.round(Number(totalSeconds) || 0));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

export function convertPace(pace: string, from: Units, to: Units): string {
  if (from === to) return pace;
  const secs = parsePaceToSeconds(pace);
  if (secs == null) return pace;

  // pace is "time per unit distance":
  // min/km -> min/mile: multiply by km per mile
  // min/mile -> min/km: divide by km per mile
  const nextSecs = to === 'imperial' ? secs * KM_PER_MILE : secs / KM_PER_MILE;
  return formatSecondsToPace(nextSecs);
}

export function cmToIn(cm: number): number {
  const v = Number(cm);
  if (!Number.isFinite(v)) return 0;
  return v / CM_PER_IN;
}

export function inToCm(inches: number): number {
  const v = Number(inches);
  if (!Number.isFinite(v)) return 0;
  return v * CM_PER_IN;
}

export function cmToFtIn(cm: number): { ft: number; inch: number } {
  const totalIn = cmToIn(cm);
  const wholeIn = Math.round(totalIn); // biometric height rarely needs sub-inch precision
  const ft = Math.floor(wholeIn / 12);
  const inch = wholeIn % 12;
  return { ft, inch };
}

export function ftInToCm(ft: number, inch: number): number {
  const f = Math.max(0, Math.floor(Number(ft) || 0));
  const i = Math.max(0, Number(inch) || 0);
  return inToCm(f * 12 + i);
}

