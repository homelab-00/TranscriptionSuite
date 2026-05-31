/**
 * transcriptFlatten — collapse structured transcript segments into editable
 * plain text for the Audio-Note hybrid edit mode (design D1).
 *
 * Word-level seek is intentionally given up once text is flattened; the original
 * segments are never mutated and remain the source of truth in the DB.
 */

import type { TranscriptionSegment } from '../api/types';

/**
 * Flatten segments to editable plain text: one segment per line, each trimmed,
 * blank segments dropped. No speaker prefixes (out of scope for MVP).
 */
export function flattenSegmentsToText(segments: TranscriptionSegment[]): string {
  return segments
    .map((seg) => (seg.text ?? '').trim())
    .filter((text) => text.length > 0)
    .join('\n');
}
