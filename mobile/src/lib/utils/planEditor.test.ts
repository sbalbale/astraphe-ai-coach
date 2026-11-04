import { describe, expect, it } from 'vitest';
import type { Workout } from '$lib/types/training';
import { draftErrors, draftMinutes, estimateTss, fromDraft, intervalSet, moveBlock, newBlock, toDraft } from './planEditor';

const speed: Workout = {
  id: '11111111-1111-1111-1111-111111111111',
  date: '2026-11-07',
  title: 'Speed 8 x 1:30',
  sport: 'row',
  primary_zone: 'VO2Max',
  duration_minutes: 50,
  projected_tss: 101,
  description: 'Race pace.',
  structure: [
    { name: 'Warmup', duration_minutes: 15, target_hr_zone: 2 },
    { name: 'Work 1/8', duration_minutes: 1.5, target_hr_zone: 5, description: 'r32-34' } as Workout['structure'][number],
    { name: 'Cooldown', duration_minutes: 10, target_hr_zone: 1 }
  ],
  completed: false
};

describe('planEditor', () => {
  it('round-trips a session: 1:30 blocks stay 1.5 min, unknown fields are kept', () => {
    const d = toDraft(speed);
    expect(d.blocks[1]).toMatchObject({ name: 'Work 1/8', minutes: 1, seconds: 30, zone: 5 });
    const saved = fromDraft(d, speed);
    expect(saved.structure[1]).toEqual({ name: 'Work 1/8', duration_minutes: 1.5, target_hr_zone: 5, description: 'r32-34' });
    expect(saved.id).toBe(speed.id);
    expect(saved.duration_minutes).toBe(27); // 15 + 1.5 + 10, rounded
  });

  it('an interval set expands into Work / Recovery blocks', () => {
    const blocks = intervalSet(8, 1.5, 5, 1);
    expect(blocks).toHaveLength(15);
    expect(blocks[0]).toMatchObject({ name: 'Work 1/8', minutes: 1, seconds: 30, zone: 5 });
    expect(blocks[1]).toMatchObject({ name: 'Recovery 1/7', minutes: 1, seconds: 0, zone: 1 });
    expect(blocks.at(-1)?.name).toBe('Work 8/8');
  });

  it('TSS uses the coach intensity factors, or %FTP when set', () => {
    const d = toDraft(speed);
    d.blocks = [newBlock('Steady', 60, 2)];
    expect(estimateTss(d)).toBe(49); // 1 h × 0.70² × 100
    d.blocks = [newBlock('FTP', 60, 4, 100)];
    expect(estimateTss(d)).toBe(100);
  });

  it('strength is saved as one Z1 block for the whole session', () => {
    const d = toDraft({ ...speed, sport: 'strength', structure: [], primary_zone: 'Recovery', duration_minutes: 60 });
    expect(d.blocks).toEqual([]);
    expect(draftMinutes(d)).toBe(60);
    const saved = fromDraft(d, speed);
    expect(saved.structure).toEqual([{ name: 'Strength', duration_minutes: 60, target_hr_zone: 1 }]);
    expect(saved.primary_zone).toBe('Recovery');
    expect(saved.projected_tss).toBe(30);
  });

  it('reorders blocks and reports problems', () => {
    const d = toDraft(speed);
    expect(moveBlock(d.blocks, 0, 2).map((b) => b.name)).toEqual(['Work 1/8', 'Cooldown', 'Warmup']);
    expect(draftErrors(d)).toEqual([]);
    d.title = ' ';
    d.blocks[0].minutes = 0;
    d.blocks[0].seconds = 0;
    d.blocks[1].ftp = 400;
    expect(draftErrors(d)).toEqual(['Give the session a name.', 'Block 1 needs a length.', 'Block 2: %FTP must be between 1 and 300.']);
  });
});
