/**
 * filenameTemplate — TypeScript mirror of
 * `server/backend/core/filename_template.py` (Issue #104, Story 3.3).
 *
 * Used by the live preview so we don't round-trip to the server on every
 * keystroke (NFR2: p95 < 50ms is trivially met by a synchronous regex
 * replace, but a network round-trip would blow it on slow links).
 *
 * Sync invariant: every key in `RESOLVERS` must also exist in the Python
 * `PLACEHOLDER_RESOLVERS`. The backend test
 * `test_filename_template_resolvers_sync.py` reads this file and asserts
 * the sets match. Adding a placeholder = update both sides + the test.
 */

export interface SampleRecording {
  id: string;
  title: string;
  model: string;
  date: string;
}

export const DEFAULT_TEMPLATE = '{date} - {title}.txt';

/** The fixed sample used in the preview (AC3.3.AC1). */
export const PREVIEW_SAMPLE: SampleRecording = {
  id: '0001',
  title: 'Sample title',
  model: 'parakeet-tdt-0.6b-v2',
  // The preview always shows today's date as 2026-05-08 — chosen to match
  // the Story 3.1 AC1 example so the docs and the UI agree visually.
  date: '2026-05-08',
};

/**
 * Resolver registry — keyed by placeholder name. Adding a placeholder is
 * a one-line change here AND in the Python equivalent.
 */
export const RESOLVERS: Record<string, (r: SampleRecording) => string> = {
  date: (r) => r.date,
  title: (r) => r.title,
  recording_id: (r) => r.id,
  model: (r) => r.model,
};

const PLACEHOLDER_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

/**
 * Render `template` against `recording`. Unknown placeholders pass through
 * as literal text including the braces (matches the Python engine).
 */
export function renderTemplate(template: string, recording: SampleRecording): string {
  return template.replace(PLACEHOLDER_RE, (whole, name) => {
    const r = RESOLVERS[name];
    return r ? r(recording) : whole;
  });
}

/**
 * Return every `{name}` in `template` whose name is NOT a registered
 * resolver. Used by the live preview to flag invalid templates inline.
 */
export function findUnknownPlaceholders(template: string): string[] {
  const out: string[] = [];
  for (const match of template.matchAll(PLACEHOLDER_RE)) {
    const name = match[1];
    if (!RESOLVERS[name]) out.push(name);
  }
  return out;
}
