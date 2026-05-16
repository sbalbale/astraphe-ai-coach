import type { ZoneDef } from '$lib/services/activityService';

/**
 * Canonical HR zone colors (Z1–Z5) for charts, maps, and time-in-zone bars.
 * Z1 (`#579BFA`) is a lighter blue distinct from brand accent (`--blue` / `#4621FF`).
 */
export const HR_ZONE_HEX: Record<number, string> = {
  1: '#579BFA',
  2: '#00C8A8',
  3: '#FFCB88',
  4: '#FF8C42',
  5: '#F07178',
};

/** Short names aligned with athlete profile HR zones API (used for UI + backend). */
export const HR_ZONE_LABELS: Record<number, string> = {
  1: 'Recovery',
  2: 'Endurance',
  3: 'Tempo',
  4: 'Threshold',
  5: 'VO2max+',
};

/** e.g. `Z3 · Tempo` */
export function formatHrZoneTitle(zoneNum: number): string {
  const name = HR_ZONE_LABELS[zoneNum];
  return name ? `Z${zoneNum} · ${name}` : '';
}

export function canonicalHrZoneShortName(zoneNum: number): string {
  return HR_ZONE_LABELS[zoneNum] ?? '';
}

/** Laps / summaries with no usable HR */
export const HR_ZONE_MISSING_HEX = '#374151';

/** Stream or map: HR present but outside defined zones, or no zone defs */
export const HR_ZONE_NEUTRAL_HEX = '#AAB3BF';

export const HR_ZONE_COLOR_BY_INDEX: Record<number, string> = {
  0: HR_ZONE_NEUTRAL_HEX,
  ...HR_ZONE_HEX,
};

export type ProfileHrZone = { zone: number; name: string; min: number; max: number };

export function profileZonesToActivityZones(zones: ProfileHrZone[] | null | undefined): ZoneDef[] {
  if (!zones?.length) return [];
  return zones
    .map((z) => ({
      zone: z.zone,
      name: z.name,
      min_bpm: z.min,
      max_bpm: z.max,
    }))
    .sort((a, b) => a.zone - b.zone);
}

export function sortZoneDefs(zones: ZoneDef[]): ZoneDef[] {
  return [...zones].sort((a, b) => a.zone - b.zone);
}

/** Same classification as backend `compute_zone_distribution` / activity zones API. */
export function bpmToHrZone(zones: ZoneDef[], bpm: number | null | undefined): number {
  if (bpm == null || !Number.isFinite(bpm) || bpm <= 0) return 0;
  const sorted = sortZoneDefs(zones);
  if (!sorted.length) return 0;
  for (const z of sorted) {
    if (bpm >= z.min_bpm && bpm < z.max_bpm) return z.zone;
  }
  const last = sorted[sorted.length - 1];
  if (last && bpm >= last.min_bpm) return last.zone;
  return 0;
}

export function hrZoneColorForBpm(zones: ZoneDef[], bpm: number | null | undefined): string {
  const z = bpmToHrZone(zones, bpm);
  if (z === 0) return zones.length ? HR_ZONE_NEUTRAL_HEX : HR_ZONE_MISSING_HEX;
  return HR_ZONE_HEX[z] ?? HR_ZONE_MISSING_HEX;
}

/**
 * Prefer zone definitions returned with the activity (streams-derived distribution).
 * Fall back to profile `hr_zones` so LapStrip and charts match the athlete model immediately.
 */
export function mergeWorkoutZoneDefs(
  activityZones: ZoneDef[] | null | undefined,
  profileZones: ProfileHrZone[] | null | undefined
): ZoneDef[] {
  if (activityZones?.length) return sortZoneDefs(activityZones);
  return profileZonesToActivityZones(profileZones);
}

/** Human-readable BPM span for UI labels; open-ended Z5 uses max_bpm sentinel from API (999). */
export function formatZoneBpmRange(z: ZoneDef | null | undefined): string {
  if (!z) return '—';
  const lo = z.min_bpm;
  const hi = z.max_bpm;
  if (hi >= 999) return `${lo}+ bpm`;
  return `${lo}–${hi} bpm`;
}
