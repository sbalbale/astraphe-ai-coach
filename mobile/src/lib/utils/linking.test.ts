import { describe, expect, it } from 'vitest';
import type { LinkFit, WorkoutCandidate } from '$lib/types/linking';
import {
  candidateTag,
  dayMark,
  dayNote,
  groupCandidates,
  hm,
  pendingConfirm,
  pickerSports,
  sessionLinkState,
  sportBadge,
  suggestionWhy,
  tssVsPlan,
  unlinkText
} from './linking';

const fit = (o: Partial<LinkFit> = {}): LinkFit => ({
  day_offset: 0,
  sport_ok: true,
  duration_ratio: 1,
  duration_ok: true,
  auto_ok: true,
  score: 0,
  reason: 'same day · similar duration',
  ...o
});

const cand = (o: Partial<WorkoutCandidate> = {}): WorkoutCandidate => ({
  id: 'w1',
  title: 'Morning ride',
  sport: 'bike',
  started_at: '2026-11-03T12:00:00Z',
  duration_seconds: 5400,
  tss: 90,
  fit: fit(),
  dismissed: false,
  linked_here: false,
  linked_to: null,
  ...o
});

describe('sessionLinkState', () => {
  const today = '2026-11-03';
  it('covers every state', () => {
    expect(sessionLinkState({ completed: true, completed_workout_id: 'w', date: '2026-11-01' }, today)).toBe('linked');
    expect(sessionLinkState({ completed: true, completed_workout_id: null, date: '2026-11-01' }, today)).toBe('mark');
    expect(sessionLinkState({ completed: false, date: '2026-11-02' }, today)).toBe('missed');
    expect(sessionLinkState({ completed: false, date: today }, today)).toBe('today');
    expect(sessionLinkState({ completed: false, date: '2026-11-04' }, today)).toBe('future');
  });
  it('maps to calendar marks', () => {
    expect(dayMark('linked')).toBe('linked');
    expect(dayMark('today')).toBeNull();
    expect(dayMark(null)).toBeNull();
  });
});

describe('formatting', () => {
  it('formats durations, badges and TSS vs plan', () => {
    expect(hm(45)).toBe('45m');
    expect(hm(60)).toBe('1h');
    expect(hm(85)).toBe('1h 25');
    expect(sportBadge('strength')).toBe('GYM');
    expect(sportBadge('kayak')).toBe('WKT');
    expect(tssVsPlan(92, 92)).toEqual({ label: '100% of planned', width: 100, onTarget: true });
    expect(tssVsPlan(130, 100)).toEqual({ label: '130% of planned', width: 100, onTarget: false });
    expect(tssVsPlan(50, 0).label).toBe('50 TSS');
  });
  it('explains why a suggestion was not auto-linked', () => {
    expect(suggestionWhy(fit())).toBe('It synced after auto-matching ran.');
    expect(suggestionWhy(fit({ auto_ok: false, day_offset: 1 }))).toBe('It was done 1 day late, so it wasn’t matched automatically.');
    expect(suggestionWhy(fit({ auto_ok: false, reason: 'same day · shorter than planned' }))).toBe(
      'Same day · shorter than planned, so it wasn’t matched automatically.'
    );
  });
  it('words the unlink note by source', () => {
    expect(unlinkText('manual')).toBe('The session goes back to not done.');
    expect(unlinkText('auto')).toContain('won’t be matched again');
  });
  it('notes the day a workout was done', () => {
    expect(dayNote('2026-11-03T12:00:00', '2026-11-03')).toBe('Same day as planned');
    expect(dayNote('2026-11-04T12:00:00', '2026-11-03')).toBe('Done 1 day late');
    expect(dayNote('2026-11-01T12:00:00', '2026-11-03')).toBe('Done 2 days early');
  });
});

describe('picker', () => {
  const rows = [
    cand({ id: 'a', title: 'Morning ride' }),
    cand({ id: 'b', title: 'Easy run', sport: 'run', fit: fit({ sport_ok: false, day_offset: 0 }) }),
    cand({ id: 'c', title: 'Long ride', fit: fit({ day_offset: 1 }) })
  ];
  it('groups same day and nearby, filters by sport and search', () => {
    expect(groupCandidates(rows, '', 'all').map((g) => [g.name, g.rows.map((r) => r.id)])).toEqual([
      ['SAME DAY', ['a', 'b']],
      ['WITHIN 2 DAYS', ['c']]
    ]);
    expect(groupCandidates(rows, '', 'run')[0].rows.map((r) => r.id)).toEqual(['b']);
    expect(groupCandidates(rows, 'long', 'all')[0].name).toBe('WITHIN 2 DAYS');
    expect(groupCandidates(rows, 'nothing', 'all')).toEqual([]);
    expect(pickerSports(rows).map((s) => s.id)).toEqual(['all', 'bike', 'run']);
  });
  it('tags rows and asks to confirm moves and other sports', () => {
    expect(candidateTag(cand({ linked_here: true }))).toBe('LINKED HERE');
    expect(candidateTag(cand({ linked_to: { id: 'p', title: 'Tempo', date: '2026-11-02' } }))).toBe('ON MON 2 NOV');
    expect(pendingConfirm(cand(), 'bike')).toBeNull();
    const move = pendingConfirm(cand({ linked_to: { id: 'p', title: 'Tempo', date: '2026-11-02' } }), 'bike');
    expect(move).toMatchObject({ kicker: 'MOVE LINK', cta: 'Move link here', move: true });
    const other = pendingConfirm(cand({ sport: 'run', fit: fit({ sport_ok: false }) }), 'bike');
    expect(other).toMatchObject({ kicker: 'DIFFERENT SPORT', cta: 'Link anyway', move: false });
    expect(other?.text).toBe('Planned ride, recorded run. Its TSS still counts toward the week.');
  });
});
