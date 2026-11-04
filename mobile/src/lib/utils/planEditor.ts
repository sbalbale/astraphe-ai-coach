/**
 * Manual editing of a planned session: the form draft, block helpers, and turning the draft
 * back into a Workout to save. TSS is estimated here (the API stores what it is sent) with the
 * coach's numbers: hours × IF² × 100, IF per zone (or the block's %FTP).
 */
import type { Interval, Workout, WorkoutZone } from '$lib/types/training';

export type Sport = Workout['sport'];

export const SPORTS: { value: Sport; label: string }[] = [
  { value: 'bike', label: 'Bike' },
  { value: 'run', label: 'Run' },
  { value: 'row', label: 'Row' },
  { value: 'swim', label: 'Swim' },
  { value: 'strength', label: 'Strength' },
  { value: 'mobility', label: 'Mobility' },
  { value: 'other', label: 'Other' }
];

export const ZONES: { value: WorkoutZone; label: string; z: number }[] = [
  { value: 'Recovery', label: 'Recovery (Z1)', z: 1 },
  { value: 'Endurance', label: 'Endurance (Z2)', z: 2 },
  { value: 'Tempo', label: 'Tempo (Z3)', z: 3 },
  { value: 'Threshold', label: 'Threshold (Z4)', z: 4 },
  { value: 'VO2Max', label: 'VO2 max (Z5)', z: 5 }
];

/** Same intensity factors as the coach (backend coach_tools.ZONE_IF), by zone 1-5. */
const ZONE_IF = [0, 0.55, 0.7, 0.85, 0.97, 1.1];
const MAX_MINUTES = 600;

export type DraftBlock = {
  /** Stable key for the list (not saved). */
  key: string;
  name: string;
  /** Length in minutes (decimals for seconds: 1:30 = 1.5). */
  duration: number;
  zone: number;
  /** Optional %FTP target; '' when none. */
  ftp: number | '';
  /** Fields of the original block this editor doesn't show (description, sub_intervals…), kept on save. */
  rest: Record<string, unknown>;
};

export type Draft = {
  title: string;
  date: string;
  sport: Sport;
  zone: WorkoutZone;
  /** Session length when it has no blocks (strength, mobility, or a plain session). */
  hours: number;
  mins: number;
  notes: string;
  blocks: DraftBlock[];
};

let keySeq = 0;
const nextKey = () => `b${++keySeq}`;

export const hasBlocks = (sport: Sport) => sport !== 'strength' && sport !== 'mobility';

export function blockMinutes(b: Pick<DraftBlock, 'duration'>): number {
  return Math.max(0, Number(b.duration) || 0);
}

export function newBlock(name: string, minutes: number, zone: number, ftp: number | '' = ''): DraftBlock {
  return { key: nextKey(), name, duration: Math.round(Math.max(0, minutes) * 60) / 60, zone, ftp, rest: {} };
}

/**
 * "1:30" → 1.5, "90:00" → 90, "1:30:00" → 90 (h:mm:ss), "90" → 90, "1.5" → 1.5, "" → 0;
 * null when it can't be read.
 */
export function parseMinSec(text: string): number | null {
  const t = String(text ?? '').trim();
  if (!t) return 0;
  const hms = /^(\d{1,2}):(\d{1,2}):(\d{1,2})$/.exec(t);
  if (hms) {
    const min = Number(hms[2]);
    const sec = Number(hms[3]);
    return min < 60 && sec < 60 ? Number(hms[1]) * 60 + min + sec / 60 : null;
  }
  const m = /^(\d{1,3}):(\d{1,2})$/.exec(t);
  if (m) {
    const sec = Number(m[2]);
    return sec < 60 ? Number(m[1]) + sec / 60 : null;
  }
  return /^\d{1,3}(\.\d+)?$/.test(t) ? Number(t) : null;
}

/** 1.5 → "1:30", 90 → "90:00", 0 → "0:00". */
export function formatMinSec(minutes: number): string {
  const total = Math.round(Math.max(0, Number(minutes) || 0) * 60);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** A blank session to plan by hand on `date`. */
export function blankWorkout(date: string): Workout {
  return {
    id: '',
    date,
    title: '',
    sport: 'bike',
    primary_zone: 'Endurance',
    duration_minutes: 60,
    projected_tss: 0,
    description: '',
    structure: [],
    completed: false
  };
}

export function toDraft(w: Workout): Draft {
  const blocks = hasBlocks(w.sport)
    ? (w.structure ?? []).map((i) => {
        const { name, duration_minutes, target_hr_zone, target_power_percent_ftp, ...rest } = i as Interval & Record<string, unknown>;
        const b = newBlock(String(name || 'Step'), Number(duration_minutes) || 0, Number(target_hr_zone) || 0, target_power_percent_ftp ? Number(target_power_percent_ftp) : '');
        b.rest = rest;
        return b;
      })
    : [];
  const total = Math.max(0, Math.round(w.duration_minutes || 0));
  return {
    title: w.title ?? '',
    date: w.date,
    sport: w.sport,
    zone: (ZONES.some((z) => z.value === w.primary_zone) ? w.primary_zone : 'Endurance') as WorkoutZone,
    hours: Math.floor(total / 60),
    mins: total % 60,
    notes: w.description ?? '',
    blocks
  };
}

/** "8 × 1:30 hard / 1:00 easy" as visible Work / Recovery blocks (like the coach saves them). */
export function intervalSet(reps: number, workMin: number, workZone: number, restMin: number, restZone = 1): DraftBlock[] {
  const n = Math.max(1, Math.min(50, Math.round(reps) || 1));
  const out: DraftBlock[] = [];
  for (let r = 1; r <= n; r++) {
    out.push(newBlock(`Work ${r}/${n}`, workMin, workZone));
    if (restMin > 0 && r < n) out.push(newBlock(`Recovery ${r}/${n - 1}`, restMin, restZone));
  }
  return out;
}

export function moveBlock(blocks: DraftBlock[], from: number, to: number): DraftBlock[] {
  if (to < 0 || to >= blocks.length || from === to) return blocks;
  const next = [...blocks];
  const [b] = next.splice(from, 1);
  next.splice(to, 0, b);
  return next;
}

/** Total minutes: the blocks' sum when the session has blocks, else hours + minutes. */
export function draftMinutes(d: Draft): number {
  if (hasBlocks(d.sport) && d.blocks.length) return d.blocks.reduce((a, b) => a + blockMinutes(b), 0);
  return Math.max(0, Number(d.hours) || 0) * 60 + Math.max(0, Number(d.mins) || 0);
}

export function estimateTss(d: Draft): number {
  const fallback = ZONES.find((z) => z.value === d.zone)?.z ?? 2;
  if (hasBlocks(d.sport) && d.blocks.length) {
    const tss = d.blocks.reduce((a, b) => {
      const f = b.ftp === '' ? 0 : Number(b.ftp);
      const intensity = f > 0 ? f / 100 : ZONE_IF[b.zone >= 1 && b.zone <= 5 ? b.zone : fallback];
      return a + (blockMinutes(b) / 60) * intensity * intensity * 100;
    }, 0);
    return Math.round(tss);
  }
  const intensity = hasBlocks(d.sport) ? ZONE_IF[fallback] : ZONE_IF[1];
  return Math.round((draftMinutes(d) / 60) * intensity * intensity * 100);
}

/** Problems that stop a save, worded for the athlete. Empty when the draft is fine. */
export function draftErrors(d: Draft): string[] {
  const out: string[] = [];
  if (!d.title.trim()) out.push('Give the session a name.');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date)) out.push('Pick a date.');
  const total = draftMinutes(d);
  if (total <= 0) out.push('Set how long the session is.');
  if (total > MAX_MINUTES) out.push('A session can be at most 10 hours.');
  if (hasBlocks(d.sport)) {
    d.blocks.forEach((b, i) => {
      if (blockMinutes(b) <= 0) out.push(`Block ${i + 1} needs a length.`);
      if (b.ftp !== '' && (Number(b.ftp) <= 0 || Number(b.ftp) > 300)) out.push(`Block ${i + 1}: %FTP must be between 1 and 300.`);
    });
  }
  return out;
}

/** The draft as the Workout to save (TSS re-estimated; untouched block fields kept). */
export function fromDraft(d: Draft, original: Workout): Workout {
  const total = draftMinutes(d);
  let structure: Interval[];
  let zone = d.zone;
  if (!hasBlocks(d.sport)) {
    // Gym / mobility time isn't zone work: one easy block for the whole session (as the coach saves it).
    structure = [{ name: d.sport === 'strength' ? 'Strength' : 'Mobility', duration_minutes: Math.round(total), target_hr_zone: 1 }];
    zone = 'Recovery';
  } else {
    structure = d.blocks.map((b) => {
      const out: Interval & Record<string, unknown> = {
        ...b.rest,
        name: b.name.trim() || 'Step',
        duration_minutes: Math.round(blockMinutes(b) * 100) / 100
      };
      if (b.zone >= 1 && b.zone <= 5) out.target_hr_zone = b.zone;
      else delete out.target_hr_zone;
      if (b.ftp !== '' && Number(b.ftp) > 0) out.target_power_percent_ftp = Math.round(Number(b.ftp));
      else delete out.target_power_percent_ftp;
      return out;
    });
  }
  return {
    ...original,
    title: d.title.trim(),
    date: d.date,
    sport: d.sport,
    primary_zone: zone,
    duration_minutes: Math.round(total),
    projected_tss: Math.min(2000, estimateTss({ ...d, zone })),
    description: d.notes,
    structure
  };
}
