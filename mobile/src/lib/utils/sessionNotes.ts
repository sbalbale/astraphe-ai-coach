/**
 * Short plain-text summary of a planned session's coach notes, for cards (Today, plan cards).
 *
 * Notes can hold a GFM prescription table (rendered properly on the plan detail). Cards show
 * prose only: table rows are dropped, including tables flattened onto one line
 * ("| Phase | Duration | | :--- | :--- | | Warmup | 15 min |"), and markdown symbols removed.
 * Returns '' when nothing but a table was there.
 */
export function sessionNotesSummary(md?: string | null, max = 240): string {
  const text = String(md ?? '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('|'))
    .join(' ')
    // A table that lost its line breaks, inside a line: from the first pipe-led cell run
    // with a separator row (| :--- |) to the last pipe.
    .replace(/\|[^\n]*\|\s*:?-{3,}:?\s*\|[^\n]*\|/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[#*_>`]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + '…';
}
