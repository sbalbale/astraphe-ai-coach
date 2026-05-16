import { describe, expect, it } from 'vitest';
import { extractFirstGfmPipeTable } from './coachMarkdown';

describe('extractFirstGfmPipeTable', () => {
  it('returns null table when no markdown table', () => {
    expect(extractFirstGfmPipeTable('Easy spin; focus cadence.')).toEqual({
      tableMarkdown: null,
      remainder: 'Easy spin; focus cadence.'
    });
  });

  it('extracts sole table with empty remainder', () => {
    const src =
      '| Phase | Duration | Target |\n' + '| --- | --- | --- |\n' + '| Main | 20m | Z2 |\n';
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(src);
    expect(tableMarkdown).toContain('| Phase | Duration | Target |');
    expect(tableMarkdown).toContain('| Main | 20m | Z2 |');
    expect(remainder).toBe('');
  });

  it('splits intro prose from table', () => {
    const intro = 'Ramp smooth into the main set.';
    const table =
      '\n\n| Interval | Duration | Target |\n' +
      '| --- | --- | --- |\n' +
      '| A | 4m | 105% |\n';
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(intro + table);
    expect(remainder.trim()).toBe(intro.trim());
    expect(tableMarkdown ?? '').toContain('| Interval |');
  });

  it('keeps text after table in remainder', () => {
    const src =
      '| Block | Minutes |\n| --- | --- |\n| A | 5 |\n\nCool down patiently.' +
      ' Do not spike HR.';
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(src);
    expect(tableMarkdown ?? '').toContain('| Block |');
    expect(remainder).toContain('Cool down patiently.');
  });

  it('normalizes CRLF line endings', () => {
    const src = '| A | B |\r\n| --- | --- |\r\n| 1 | 2 |\r\n';
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(src);
    expect(tableMarkdown).not.toBeNull();
    expect(remainder).toBe('');
  });
});
