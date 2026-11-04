import { describe, expect, it } from 'vitest';
import {
  extractFirstGfmPipeTable,
  normalizeMarkdownBlockStructure,
  normalizeMarkdownSource,
  renderCoachMarkdownToSafeHtml,
  htmlTagsToMarkdown
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

  it('extracts table when newlines are escaped as literal \\n', () => {
    const src =
      '| Phase | Duration | Target | Notes |\\n| :--- | :--- | :--- | :--- |\\n' +
      '| Warmup | 20m | Z1-Z2 | Gradual ramp |\\n' +
      '| Main Set | 3x15m | 220-235W | Sweet Spot |';
    const { tableMarkdown, remainder } = extractFirstGfmPipeTable(src);
    expect(tableMarkdown).toContain('| Phase | Duration | Target | Notes |');
    expect(tableMarkdown).toContain('| Warmup | 20m | Z1-Z2 | Gradual ramp |');
    expect(remainder).toBe('');
  });
});

describe('normalizeMarkdownSource', () => {
  it('converts literal \\n to newlines', () => {
    expect(normalizeMarkdownSource('line1\\nline2')).toBe('line1\nline2');
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

describe('renderCoachMarkdownToSafeHtml security', () => {
  if (typeof window.matchMedia !== 'function') {
    (window as any).matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  }

  it('never runs event handlers from raw HTML in the reply', async () => {
    (window as any).__xss = 0;
    const html = renderCoachMarkdownToSafeHtml('Hi <img src=x onerror="window.__xss=1"> there');
    await new Promise((r) => setTimeout(r, 20));
    expect((window as any).__xss).toBe(0);
    expect(html).not.toMatch(/onerror/i);
  });

  it('strips handlers inside a table whose postscript row gets lifted', () => {
    const md =
      '| A | B |\n| --- | --- |\n| 1 | 2 |\n| <img src=x onerror="window.__xss=2"> a long trailing paragraph that marked pulled into the table |  |\n';
    const html = renderCoachMarkdownToSafeHtml(md);
    expect(html).not.toMatch(/onerror/i);
  });

  it('drops javascript: links and overlay styles', () => {
    const html = renderCoachMarkdownToSafeHtml(
      '[x](javascript:alert(1)) <div style="position:fixed;inset:0;z-index:9999">fake login</div>'
    );
    expect(html).not.toMatch(/javascript:/i);
    expect(html).not.toMatch(/position\s*:\s*fixed/i);
  });

  it('keeps safe external links with rel=noopener', () => {
    const html = renderCoachMarkdownToSafeHtml('[docs](https://example.com)');
    expect(html).toMatch(/href="https:\/\/example\.com"/);
    expect(html).toMatch(/rel="noopener noreferrer"/);
  });
});

describe('replies written in HTML', () => {
  const body = 'With your FTP set at **280W**, TSS scales as follows:\n* **175W**: **~39 TSS**\n* **180W**: **~41 TSS**';

  it('still renders markdown when the reply starts with <p>', () => {
    // A leading <p> made marked treat the reply as raw HTML: literal ** and the list run together.
    const html = renderCoachMarkdownToSafeHtml(`<p>${body}</p>`);
    expect(html).toContain('<strong>280W</strong>');
    expect(html).not.toContain('**');
    expect(html.match(/<li>/g)?.length).toBe(2);
  });

  it('does not render an empty bubble after <br> or a <thought> block', () => {
    expect(renderCoachMarkdownToSafeHtml(`<br>\n${body}`)).toContain('<strong>280W</strong>');
    const html = renderCoachMarkdownToSafeHtml(`<thought>plan the answer</thought>\n${body}`);
    expect(html).toContain('<strong>280W</strong>');
    expect(html).not.toContain('plan the answer');
  });

  it('maps inline and list tags to markdown and leaves code fences alone', () => {
    expect(htmlTagsToMarkdown('<ul><li><b>Z2</b></li><li><em>easy</em></li></ul>')).toBe('* **Z2**\n* *easy*');
    expect(htmlTagsToMarkdown('```\n<p>keep</p>\n```')).toBe('```\n<p>keep</p>\n```');
    expect(htmlTagsToMarkdown('Keep HR <150 and > 120')).toBe('Keep HR <150 and > 120');
  });
});
