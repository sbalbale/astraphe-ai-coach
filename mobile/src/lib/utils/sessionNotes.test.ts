import { describe, expect, it } from 'vitest';
import { sessionNotesSummary } from './sessionNotes';

describe('sessionNotesSummary', () => {
  it('drops a table flattened onto one line (prod, Today card)', () => {
    const md =
      '| Phase | Duration | Intensity | Target | | :--- | :--- | :--- | :--- | | Warmup | 15 min | Z1-Z2 | Easy spin | | Main Set | 40 min | Sweet Spot | 85-90% FTP | | Cooldown | 5 min | Z1 | Easy spin |';
    expect(sessionNotesSummary(md)).toBe('');
  });

  it('keeps prose around a multi-line table', () => {
    const md = 'Smooth and controlled.\n\n| Phase | Duration |\n| :--- | :--- |\n| Warmup | 10 min |\n\nStay relaxed.';
    expect(sessionNotesSummary(md)).toBe('Smooth and controlled. Stay relaxed.');
  });

  it('keeps prose before a one-line table', () => {
    expect(sessionNotesSummary('**Easy** day. | A | B | | --- | --- | | 1 | 2 |')).toBe('Easy day.');
  });

  it('strips markdown and shortens long text', () => {
    expect(sessionNotesSummary('## Go [hard](http://x)')).toBe('Go hard');
    expect(sessionNotesSummary('a'.repeat(300), 10)).toBe('aaaaaaaaa…');
    expect(sessionNotesSummary(undefined)).toBe('');
  });
});
