import { describe, expect, it } from 'vitest';
import {
  buildChatContextSuggestions,
  buildCoachPromptSuggestions,
  buildMemorySuggestions,
  buildMergedCoachPromptSuggestions,
  type CoachChatTurn
} from './coachPromptSuggestions';

describe('buildCoachPromptSuggestions', () => {
  it('low TSB suggests active recovery', () => {
    const out = buildCoachPromptSuggestions({ ctl: 50, tsb: -25, sleepScore: 80, hrvZScore: 0 });
    expect(out.some((s) => s.includes('Form is down'))).toBe(true);
  });

  it('high TSB suggests a breakthrough workout', () => {
    const out = buildCoachPromptSuggestions({ ctl: 50, tsb: 20, sleepScore: 80, hrvZScore: 0 });
    expect(out.some((s) => s.includes('TSB is +20'))).toBe(true);
  });

  it('very low HRV z-score flags overtraining risk', () => {
    const out = buildCoachPromptSuggestions({ ctl: 50, tsb: 0, sleepScore: 80, hrvZScore: -2 });
    expect(out.some((s) => s.includes('deeply suppressed'))).toBe(true);
  });

  it('high HRV z-score suggests taking advantage', () => {
    const out = buildCoachPromptSuggestions({ ctl: 50, tsb: 0, sleepScore: 80, hrvZScore: 1.5 });
    expect(out.some((s) => s.includes('HRV is up today'))).toBe(true);
  });

  it('low CTL suggests ramping volume', () => {
    const out = buildCoachPromptSuggestions({ ctl: 20, tsb: 0, sleepScore: 80, hrvZScore: null });
    expect(out.some((s) => s.includes('ramp up volume'))).toBe(true);
  });

  it('high CTL suggests maintaining fitness', () => {
    const out = buildCoachPromptSuggestions({ ctl: 90, tsb: 0, sleepScore: 80, hrvZScore: null });
    expect(out.some((s) => s.includes('fitness is high'))).toBe(true);
  });

  it('mid CTL suggests a generic weekly focus question', () => {
    const out = buildCoachPromptSuggestions({ ctl: 60, tsb: 0, sleepScore: 80, hrvZScore: null });
    expect(out.some((s) => s.includes('best focus for my training'))).toBe(true);
  });

  it('low sleep score flags a rough night', () => {
    const out = buildCoachPromptSuggestions({ ctl: 60, tsb: 0, sleepScore: 45, hrvZScore: null });
    expect(out.some((s) => s.includes('rough night'))).toBe(true);
  });

  it('zero CTL with room left suggests a beginner foundation question', () => {
    const out = buildCoachPromptSuggestions({ ctl: 0, tsb: 0, sleepScore: 80, hrvZScore: null });
    expect(out.some((s) => s.includes('sustainable aerobic foundation'))).toBe(true);
  });

  it('caps output at 3 suggestions', () => {
    const out = buildCoachPromptSuggestions({ ctl: 20, tsb: -25, sleepScore: 40, hrvZScore: -2 });
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it('always includes a fallback when nothing else matched', () => {
    const out = buildCoachPromptSuggestions({ ctl: 60, tsb: 0, sleepScore: 80, hrvZScore: null });
    expect(out.length).toBeGreaterThan(0);
  });
});

describe('buildChatContextSuggestions', () => {
  it('fewer than 2 non-empty turns returns empty', () => {
    expect(buildChatContextSuggestions([{ role: 'user', text: 'hi' }])).toEqual([]);
    expect(buildChatContextSuggestions([])).toEqual([]);
  });

  it('substantive AI reply with a detected race + date produces a race-specific follow-up', () => {
    const turns: CoachChatTurn[] = [
      { role: 'user', text: 'I have a sprint triathlon on June 22nd, how should I prepare?' },
      {
        role: 'ai',
        text: 'Given your race on June 22nd, we should build aerobic volume progressively before adding intensity work like intervals near threshold.'
      }
    ];
    const out = buildChatContextSuggestions(turns);
    expect(out.some((s) => s.includes('sprint triathlon'))).toBe(true);
  });

  it('user just spoke about a race with a date produces a follow-up', () => {
    const turns: CoachChatTurn[] = [
      { role: 'ai', text: 'How can I help today?' },
      { role: 'user', text: 'My marathon is on May 3rd and I am nervous about pacing.' }
    ];
    const out = buildChatContextSuggestions(turns);
    expect(out.some((s) => s.includes('marathon'))).toBe(true);
  });

  it('user mentions fatigue keywords produces a recovery-signal follow-up', () => {
    const turns: CoachChatTurn[] = [
      { role: 'ai', text: 'How can I help today?' },
      { role: 'user', text: 'I feel really tired and sore after yesterday, not sure if I should train.' }
    ];
    const out = buildChatContextSuggestions(turns);
    expect(out.some((s) => s.includes('objective signals'))).toBe(true);
  });

  it('short/unremarkable turns yield no suggestions', () => {
    const turns: CoachChatTurn[] = [
      { role: 'ai', text: 'Hi there!' },
      { role: 'user', text: 'ok thanks' }
    ];
    expect(buildChatContextSuggestions(turns)).toEqual([]);
  });

  it('dedupes and caps at 8 suggestions', () => {
    const turns: CoachChatTurn[] = [
      { role: 'user', text: 'My Ironman triathlon is on June 22nd and I am also backpacking this weekend.' },
      {
        role: 'ai',
        text:
          'Given your Ironman on June 22nd, we should build aerobic volume progressively before adding race-specific intensity intervals near threshold. ' +
          'If your recovery slips during this build, we will need to adjust.'
      }
    ];
    const out = buildChatContextSuggestions(turns);
    expect(out.length).toBeLessThanOrEqual(8);
    expect(new Set(out.map((s) => s.toLowerCase())).size).toBe(out.length);
  });
});

describe('buildMemorySuggestions', () => {
  it('empty input returns empty output', () => {
    expect(buildMemorySuggestions([])).toEqual([]);
  });

  it('triathlon memory produces a distance-aware suggestion', () => {
    const out = buildMemorySuggestions(['Athlete is training for a sprint triathlon']);
    expect(out.some((s) => s.includes('sprint triathlon'))).toBe(true);
  });

  it('goal/target memory produces a race-name suggestion', () => {
    const out = buildMemorySuggestions(['goal is Boston Marathon on April 20']);
    expect(out.some((s) => s.toLowerCase().includes('boston marathon'))).toBe(true);
  });

  it('injury memory produces an injury-aware suggestion', () => {
    const out = buildMemorySuggestions(['Athlete mentioned knee pain last week']);
    expect(out.some((s) => s.includes('injury context'))).toBe(true);
  });

  it('trip memory produces a trip-aware suggestion', () => {
    const out = buildMemorySuggestions(['Planning a backpacking trip in August']);
    expect(out.some((s) => s.includes('upcoming trip'))).toBe(true);
  });

  it('unrelated memory yields no suggestion', () => {
    expect(buildMemorySuggestions(['Prefers morning workouts'])).toEqual([]);
  });
});

describe('buildMergedCoachPromptSuggestions', () => {
  it('brand new chat (no user participation) prioritizes memory suggestions', () => {
    const out = buildMergedCoachPromptSuggestions({
      ctl: 50,
      tsb: 0,
      sleepScore: 80,
      hrvZScore: 0,
      memories: ['goal is a spring marathon'],
      recentMessages: [{ role: 'ai', text: 'Welcome back!' }]
    });
    expect(out.length).toBeGreaterThan(0);
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it('user participated but chat produced no context suggestions falls back to athlete+memory', () => {
    const out = buildMergedCoachPromptSuggestions({
      ctl: 50,
      tsb: 0,
      sleepScore: 80,
      hrvZScore: 0,
      recentMessages: [
        { role: 'ai', text: 'Hi!' },
        { role: 'user', text: 'ok' }
      ]
    });
    expect(out.length).toBeGreaterThan(0);
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it('rich thread prefers chat-context suggestions', () => {
    const recentMessages: CoachChatTurn[] = [
      { role: 'user', text: 'turn 1' },
      { role: 'ai', text: 'turn 2' },
      { role: 'user', text: 'turn 3' },
      { role: 'ai', text: 'turn 4' },
      {
        role: 'user',
        text: 'My Ironman triathlon is on June 22nd, I am nervous about the bike leg pacing strategy.'
      }
    ];
    const out = buildMergedCoachPromptSuggestions({
      ctl: 50,
      tsb: 0,
      sleepScore: 80,
      hrvZScore: 0,
      recentMessages
    });
    expect(out.length).toBeGreaterThan(0);
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it('filters an athlete CTL suggestion already discussed in the thread', () => {
    const out = buildMergedCoachPromptSuggestions({
      ctl: 20,
      tsb: 0,
      sleepScore: 80,
      hrvZScore: null,
      recentMessages: [
        { role: 'ai', text: 'Your CTL is 20 right now, still building your base.' },
        { role: 'user', text: 'Got it, thanks for confirming my CTL is 20.' }
      ]
    });
    expect(out.every((s) => !s.toLowerCase().startsWith('my ctl is'))).toBe(true);
  });
});
