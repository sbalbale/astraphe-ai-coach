import DOMPurify from 'dompurify';
import { Marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import 'katex/dist/katex.min.css';

/**
 * marked-katex-extension treats inline math as `$ … $` (often with spaces). Tight
 * delimiters like `$CTL - ATL$` fail unless we loosen the inner segment slightly.
 * Does not alter `$$ … $$` display blocks (even indices after split).
 */
export function normalizeTightInlineDollarMath(markdown: string): string {
  const parts = markdown.split('$$');
  for (let i = 0; i < parts.length; i += 2) {
    parts[i] = parts[i].replace(/\$(?!\s)((?:[^$\\]|\\.)+?)(?<!\s)\$/g, (_full, inner: string) => {
      if (!String(inner).trim()) return `$${inner}$`;
      return `$ ${inner} $`;
    });
  }
  return parts.join('$$');
}

function escapeHtmlAttr(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function escapeHtmlText(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

/** Display-only: straight quotes wrap reliably in narrow chat bubbles. */
export function normalizeTypographyForWrap(text: string): string {
  return text.replace(/[\u201C\u201D]/g, '"').replace(/[\u2018\u2019]/g, "'");
}

/**
 * marked sometimes pulls a trailing paragraph into the last tbody row when
 * the AI response has no blank line between the table and the footnote text.
 * This detects rows where the first <td> has long text and all other <td>s
 * are empty, removes them from the table, and re-inserts them as <p> tags
 * immediately after the </table>.
 */
function liftTablePostscripts(html: string): string {
  if (typeof document === 'undefined') return html; // SSR guard

  const tmp = document.createElement('div');
  tmp.innerHTML = html;

  for (const table of Array.from(tmp.querySelectorAll('table'))) {
    const tbody = table.querySelector('tbody');
    if (!tbody) continue;

    const isMisplacedParagraph = (tr: Element): boolean => {
      const cells = Array.from(tr.querySelectorAll('td'));
      if (cells.length < 2) return false;
      const firstText = cells[0].textContent?.trim() ?? '';
      const restEmpty = cells.slice(1).every((td) => (td.textContent?.trim() ?? '') === '');
      return firstText.length > 40 && restEmpty;
    };

    const makeNote = (tr: Element): string => {
      const cells = Array.from(tr.querySelectorAll('td'));
      return `<p class="chat-table-note">${cells[0].innerHTML}</p>`;
    };

    // --- Lift from the TOP (insert before the table) ---
    const before: string[] = [];
    let rows = Array.from(tbody.querySelectorAll(':scope > tr'));
    for (const tr of rows) {
      if (isMisplacedParagraph(tr)) {
        before.push(makeNote(tr));
        tbody.removeChild(tr);
      } else {
        break; // stop at first real data row
      }
    }

    // --- Lift from the BOTTOM (insert after the table) ---
    const after: string[] = [];
    rows = Array.from(tbody.querySelectorAll(':scope > tr')); // re-query after top removals
    for (let i = rows.length - 1; i >= 0; i--) {
      const tr = rows[i];
      if (isMisplacedParagraph(tr)) {
        after.unshift(makeNote(tr));
        tbody.removeChild(tr);
      } else {
        break;
      }
    }

    // Insert "before" nodes before the table
    if (before.length > 0) {
      const frag = document.createRange().createContextualFragment(before.join(''));
      table.parentNode?.insertBefore(frag, table);
    }

    // Insert "after" nodes after the table
    if (after.length > 0) {
      const frag = document.createRange().createContextualFragment(after.join(''));
      table.parentNode?.insertBefore(frag, table.nextSibling);
    }
  }

  return tmp.innerHTML;
}

/** Cells between pipes (drops optional leading/trailing `|` segment). */
function splitPipeCells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map((c) => c.trim());
}

function isGfmDelimiterRow(line: string): boolean {
  const t = line.trim();
  if (!t.includes('|')) return false;
  const cells = splitPipeCells(t);
  return cells.length >= 2 && cells.every((c) => /^:?-{3,}:?$/.test(c));
}

/** Row that can be table header/body cells (GFM pipe), not delimiter lines. */
function isLikelyPipeDataRow(line: string): boolean {
  const t = line.trim();
  if (!t || !t.includes('|')) return false;
  if (isGfmDelimiterRow(t)) return false;
  const cells = splitPipeCells(t);
  return cells.length >= 2;
}

/**
 * First GFM pipe table | block | delimiter | rows… in markdown; remainder is text outside the table.
 * Used so UI can split “prescription table” vs “coach notes”.
 */
export function extractFirstGfmPipeTable(src: string): { tableMarkdown: string | null; remainder: string } {
  const text = src ?? '';
  const normalized = text.replace(/\r\n/g, '\n');
  const lines = normalized.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const next = lines[i + 1];
    if (next !== undefined && isLikelyPipeDataRow(line) && isGfmDelimiterRow(next)) {
      const start = i;
      let j = i + 2;
      while (j < lines.length) {
        const L = lines[j];
        if (L.trim() === '') break;
        if (!isLikelyPipeDataRow(L)) break;
        j++;
      }
      const tableLines = lines.slice(start, j);
      const tableMarkdown = tableLines.join('\n').trimEnd();
      const before = lines.slice(0, start).join('\n').trimEnd();
      const after = lines.slice(j).join('\n').trimStart();
      const parts: string[] = [];
      if (before) parts.push(before);
      if (after) parts.push(after);
      const remainder = parts.join('\n\n').trim();
      return {
        tableMarkdown: tableMarkdown || null,
        remainder
      };
    }
    i++;
  }
  return { tableMarkdown: null, remainder: text.trim() };
}

const coachMd = new Marked();

coachMd.use(
  markedKatex({
    throwOnError: false,
    nonStandard: true
  })
);

const mdRenderer = new coachMd.Renderer();
mdRenderer.link = (...args: unknown[]) => {
  const token = args[0] && typeof args[0] === 'object' ? (args[0] as Record<string, unknown>) : null;
  const href = (token?.href as string | undefined) ?? (args[0] as string);
  const title = (token?.title as string | undefined) ?? (args[1] as string | undefined);
  const text = (token?.text as string | undefined) ?? (args[2] as string | undefined);

  const safeHref = typeof href === 'string' ? href : '';
  const safeTitle = typeof title === 'string' ? title : undefined;
  const safeText = typeof text === 'string' ? escapeHtmlText(text) : escapeHtmlText(safeHref);
  const titleAttr = safeTitle ? ` title="${escapeHtmlAttr(safeTitle)}"` : '';
  return `<a href="${escapeHtmlAttr(safeHref)}"${titleAttr} target="_blank" rel="noreferrer noopener">${safeText}</a>`;
};

coachMd.setOptions({
  gfm: true,
  breaks: true,
  renderer: mdRenderer
});

const PURIFY_MATH: Parameters<typeof DOMPurify.sanitize>[1] = {
  USE_PROFILES: { html: true },
  ADD_TAGS: [
    'math',
    'annotation',
    'semantics',
    'mrow',
    'mi',
    'mn',
    'mo',
    'msup',
    'msub',
    'msubsup',
    'mfrac',
    'munder',
    'mover',
    'mtable',
    'mtr',
    'mtd',
    'mspace',
    'mtext',
    'menclose',
    'mstyle',
    'mpadded',
    'svg',
    'path',
    'line',
    'g',
    'defs',
    'use'
  ],
  ADD_ATTR: [
    'xmlns',
    'encoding',
    'displaystyle',
    'style',
    'class',
    'aria-hidden',
    'aria-label',
    'aria-describedby',
    'depth',
    'lspace',
    'rspace',
    'height',
    'width',
    'viewBox',
    'd',
    'stroke',
    'fill',
    'x',
    'y',
    'preserveAspectRatio',
    'xlink:href',
    'href',
    'version',
    'focusable',
    'xmlns:xlink',
    'stroke-width',
    'stroke-linecap',
    'stroke-linejoin',
    'fill-rule',
    'fill-opacity',
    'stroke-opacity',
    'marker-start',
    'marker-end',
    'transform',
    'text-anchor',
    'dominant-baseline'
  ]
};

/**
 * Coach reply markdown → sanitized HTML (GFM + line breaks + KaTeX + safe links).
 */
export function renderCoachMarkdownToSafeHtml(text: string): string {
  const src = normalizeTightInlineDollarMath(normalizeTypographyForWrap(text ?? ''));
  const html = coachMd.parse(src, { async: false }) as string;
  const lifted = liftTablePostscripts(html);
  return normalizeTypographyForWrap(DOMPurify.sanitize(lifted, {
    ...PURIFY_MATH,
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|\/)/i
  }));
}
