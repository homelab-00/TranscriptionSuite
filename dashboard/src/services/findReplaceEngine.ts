/**
 * findReplaceEngine — pure literal substring find/replace.
 *
 * Literal (NOT regex) matching, non-overlapping, scanned left-to-right.
 * All functions are pure and immutable: inputs are never mutated and replace
 * helpers return new strings. Shared by every transcript editor surface via
 * useFindReplace.
 */

/** Half-open offset range into the source text: [start, end). */
export interface Match {
  start: number;
  end: number;
}

export interface FindOptions {
  caseSensitive: boolean;
}

/** True when a query can never produce a match (empty or whitespace-only). */
function isBlankQuery(query: string): boolean {
  return query.trim() === '';
}

/**
 * All non-overlapping matches of `query` in `text`, left-to-right.
 * Empty/whitespace-only query → []. Case-insensitive search compares lowercased
 * copies while the returned offsets index into the original `text`.
 */
export function computeMatches(text: string, query: string, opts: FindOptions): Match[] {
  if (isBlankQuery(query)) return [];

  const haystack = opts.caseSensitive ? text : text.toLowerCase();
  const needle = opts.caseSensitive ? query : query.toLowerCase();
  const matches: Match[] = [];

  let from = 0;
  while (from <= haystack.length) {
    const idx = haystack.indexOf(needle, from);
    if (idx === -1) break;
    matches.push({ start: idx, end: idx + needle.length });
    from = idx + needle.length; // advance past the match → non-overlapping
  }
  return matches;
}

/**
 * Replace the single occurrence delimited by `match` with `replacement`.
 * Returns a new string; `text` is unchanged.
 */
export function replaceCurrent(text: string, match: Match, replacement: string): string {
  return text.slice(0, match.start) + replacement + text.slice(match.end);
}

/**
 * Replace every non-overlapping match of `query` with `replacement`.
 * Returns the new text and the number of replacements made. No-op (count 0)
 * for empty/whitespace-only queries or when there are no matches.
 */
export function replaceAll(
  text: string,
  query: string,
  replacement: string,
  opts: FindOptions,
): { text: string; count: number } {
  const matches = computeMatches(text, query, opts);
  if (matches.length === 0) return { text, count: 0 };

  let result = '';
  let lastEnd = 0;
  for (const m of matches) {
    result += text.slice(lastEnd, m.start) + replacement;
    lastEnd = m.end;
  }
  result += text.slice(lastEnd);
  return { text: result, count: matches.length };
}
