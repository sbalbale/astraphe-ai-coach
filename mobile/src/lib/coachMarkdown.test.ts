import { describe, expect, it } from 'vitest';
import {
  extractFirstGfmPipeTable,
  normalizeMarkdownBlockStructure,
  renderCoachMarkdownToSafeHtml
} from './coachMarkdown';

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

describe('normalizeMarkdownBlockStructure', () => {
  it('inserts blank line before section heading after list items', () => {
    const src = [
      '* **The Drill:** rotate shoulder.',
      '* **Why it matters:** proper rotation.',
      '**High Elbow Catch (4x50m)**',
      'This is EVF.'
    ].join('\n');
    const out = normalizeMarkdownBlockStructure(src);
    expect(out).toBe(
      [
        '* **The Drill:** rotate shoulder.',
        '* **Why it matters:** proper rotation.',
        '',
        '**High Elbow Catch (4x50m)**',
        'This is EVF.'
      ].join('\n')
    );
  });

  it('does not change markdown that already has a blank line after the list', () => {
    const src = ['* item one', '', '**Next Section**'].join('\n');
    expect(normalizeMarkdownBlockStructure(src)).toBe(src);
  });

  it('does not insert blank line when heading is not preceded by a list item', () => {
    const src = ['Intro paragraph.', '**Section Two**'].join('\n');
    expect(normalizeMarkdownBlockStructure(src)).toBe(src);
  });
});

describe('renderCoachMarkdownToSafeHtml', () => {
  const swimDrillSample = [
    'Here is the breakdown:',
    '**Catch & Rotation (4x50m)**',
    'The focus here is alignment.',
    '* **The Drill:** rotate shoulder.',
    '* **Why it matters:** proper rotation.',
    '**High Elbow Catch (4x50m)**',
    'This is often called the Early Vertical Forearm.'
  ].join('\n');

  it('closes list before second section heading (not inside last li)', () => {
    const html = renderCoachMarkdownToSafeHtml(swimDrillSample);
    expect(html).toContain('</ul>');
    expect(html).toMatch(/<\/ul>[\s\S]*<p><strong>High Elbow Catch/);
    expect(html).not.toMatch(/<li>[\s\S]*<strong>High Elbow Catch[\s\S]*<\/li>/);
  });

  it('renders bullet lists as ul/li', () => {
    const html = renderCoachMarkdownToSafeHtml('* **The Drill:** one\n* **Why:** two');
    expect(html).toContain('<ul>');
    expect(html).toContain('<li>');
    expect(html).toContain('<strong>The Drill:</strong>');
  });
});
