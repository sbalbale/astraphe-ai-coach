import { describe, expect, it } from 'vitest';
import {
  connectedSourcesLabel,
  conversationWhen,
  filterConversations,
  sessionMeta,
  weekLoad,
  weekRange
} from './coachContext';

const NOW = new Date(2026, 10, 2, 9, 0); // Mon 2 Nov 2026

describe('conversationWhen', () => {
  it('labels recent days relative to now', () => {
    expect(conversationWhen(new Date(2026, 10, 2, 7).toISOString(), NOW)).toBe('Today');
    expect(conversationWhen(new Date(2026, 10, 1, 7).toISOString(), NOW)).toBe('Yesterday');
    expect(conversationWhen(new Date(2026, 9, 29, 7).toISOString(), NOW)).toBe('Thu');
    expect(conversationWhen(new Date(2026, 9, 20, 7).toISOString(), NOW)).toBe('20 Oct');
    expect(conversationWhen(new Date(2025, 9, 20, 7).toISOString(), NOW)).toBe('20 Oct 2025');
  });
  it('is empty for missing or bad dates', () => {
    expect(conversationWhen(undefined, NOW)).toBe('');
    expect(conversationWhen('nope', NOW)).toBe('');
  });
});

describe('filterConversations', () => {
  const rows = [{ title: 'Heavy legs' }, { title: null }, { title: 'Fuelling for Saturday' }];
  it('matches titles case-insensitively, untitled as "New chat"', () => {
    expect(filterConversations(rows, 'LEGS')).toEqual([{ title: 'Heavy legs' }]);
    expect(filterConversations(rows, 'new')).toEqual([{ title: null }]);
    expect(filterConversations(rows, '  ')).toBe(rows);
  });
});

describe('weekLoad', () => {
  const range = weekRange(NOW);
  it('uses a Sunday-first week', () => {
    expect(range).toEqual({ start: '2026-11-01', end: '2026-11-07' });
  });
  it('sums done and planned TSS inside the week only', () => {
    const done = [
      { started_at: new Date(2026, 10, 2, 7).toISOString(), tss: 92.4 },
      { started_at: new Date(2026, 9, 31, 7).toISOString(), tss: 168 }
    ];
    const planned = [
      { date: '2026-11-02', projected_tss: 92 },
      { date: '2026-11-05', projected_tss: 88 },
      { date: '2026-11-09', projected_tss: 60 }
    ];
    expect(weekLoad(done, planned, range)).toEqual({ done: 92, planned: 180, pct: 51 });
  });
  it('is null with no load at all', () => {
    expect(weekLoad([], [], range)).toBeNull();
  });
});

describe('connectedSourcesLabel', () => {
  it('lists connected providers in a fixed order', () => {
    expect(connectedSourcesLabel({ whoop: { connected: true }, garmin: { connected: true }, strava: { connected: false } })).toBe('Garmin · WHOOP');
    expect(connectedSourcesLabel(null)).toBe('');
  });
});

describe('sessionMeta', () => {
  it('joins duration, sport and TSS', () => {
    expect(sessionMeta({ duration_minutes: 85, sport: 'bike', projected_tss: 92 })).toBe('85′ · BIKE · 92 TSS');
    expect(sessionMeta({ duration_minutes: 0, sport: 'strength', projected_tss: 0 })).toBe('STRENGTH');
  });
});
