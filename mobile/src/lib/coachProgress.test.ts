import { describe, expect, it } from 'vitest';
import { buildCoachSteps, coachStatusText, coachToolLabel } from './coachProgress';

describe('coachToolLabel', () => {
  it('maps known tools and humanises unknown ones', () => {
    expect(coachToolLabel('list_workouts')).toBe('Looked through your workouts');
    expect(coachToolLabel('brand_new_tool')).toBe('Used brand new tool');
    expect(coachToolLabel(undefined)).toBe('Used a tool');
  });
});

describe('buildCoachSteps', () => {
  it('lists context and tools, skipping started/thinking/done', () => {
    const steps = buildCoachSteps(
      [
        { status: 'started' },
        { status: 'context_ready' },
        { status: 'thinking', hop: 0 },
        { status: 'tool', tool: 'get_workout_summary' },
        { status: 'thinking', hop: 1 },
        { status: 'done' }
      ],
      false
    );
    expect(steps.map((s) => s.label)).toEqual([
      'Loaded your recent training and recovery',
      'Read a workout in detail'
    ]);
    expect(steps.every((s) => s.done)).toBe(true);
  });

  it('collapses repeated tools with a count and moves them to the end', () => {
    const steps = buildCoachSteps(
      [
        { status: 'tool', tool: 'get_workout_summary' },
        { status: 'tool', tool: 'get_athlete_zones' },
        { status: 'tool', tool: 'get_workout_summary' }
      ],
      false
    );
    expect(steps.map((s) => [s.key, s.count])).toEqual([
      ['tool:get_athlete_zones', 1],
      ['tool:get_workout_summary', 2]
    ]);
  });

  it('marks the latest step as running while the reply is pending', () => {
    const steps = buildCoachSteps([{ status: 'context_ready' }, { status: 'tool', tool: 'list_workouts' }], true);
    expect(steps.map((s) => s.done)).toEqual([true, false]);
  });

  it('keeps every step done once the model is thinking again', () => {
    const steps = buildCoachSteps([{ status: 'tool', tool: 'list_workouts' }, { status: 'thinking', hop: 1 }], true);
    expect(steps.map((s) => s.done)).toEqual([true]);
  });

  it('returns nothing for no events', () => {
    expect(buildCoachSteps([], true)).toEqual([]);
  });
});

describe('coachStatusText', () => {
  it('describes the latest event', () => {
    expect(coachStatusText([])).toBe('Reviewing your data…');
    expect(coachStatusText([{ status: 'started' }])).toBe('Reviewing your data…');
    expect(coachStatusText([{ status: 'context_ready' }])).toBe('Reading your data…');
    expect(coachStatusText([{ status: 'thinking', hop: 0 }])).toBe('Thinking…');
    expect(coachStatusText([{ status: 'thinking', hop: 2 }])).toBe('Putting it together…');
    expect(coachStatusText([{ status: 'tool', tool: 'get_athlete_zones' }])).toBe('Looked up your zones…');
    expect(coachStatusText([{ status: 'done' }])).toBe('Writing the reply…');
    expect(coachStatusText([{ status: 'mystery' }])).toBe('Thinking…');
  });
});
