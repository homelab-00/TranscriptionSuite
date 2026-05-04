/**
 * Read-time alias substitution (Issue #104, Stories 4.4 / 5.1 / 5.5).
 *
 * Mirror of `server/backend/core/alias_substitution.py::build_speaker_label_map`.
 * Both implementations:
 *   1. Walk segments in segment_index order.
 *   2. For each NEW raw `speaker` value:
 *      - if `aliases[raw]` exists → use the alias as the display label,
 *      - otherwise → assign `Speaker {N}` where N is the first-appearance counter.
 *   3. Cache the mapping so repeat calls within a render are O(1).
 *
 * The stored transcript (`segments.speaker`) is NEVER mutated — substitution
 * is applied at render time only. This protects R-EL3 (verbatim guarantee):
 * the user can rename and rename again, and the underlying transcription
 * artifact remains the ground truth.
 */

export interface AliasMap {
  [speakerId: string]: string;
}

/**
 * Build raw speaker_id → display_label map for the given segment list.
 *
 * The label_map's entry order matches first-appearance order in `segments`,
 * which is what backends rely on so that `Speaker 1` is consistent across
 * the view, the plain-text export, and the AI summary prompt.
 */
export function buildSpeakerLabelMap(
  segments: ReadonlyArray<{ speaker?: string | null }>,
  aliases: AliasMap,
): Map<string, string> {
  const labels = new Map<string, string>();
  let next = 1;
  for (const seg of segments) {
    const raw = seg.speaker;
    if (!raw || labels.has(raw)) continue;
    if (raw in aliases) {
      labels.set(raw, aliases[raw]);
    } else {
      labels.set(raw, `Speaker ${next}`);
      next += 1;
    }
  }
  return labels;
}

/**
 * Look up the display label for a raw speaker_id.
 *
 * Returns the empty string when `raw` is null/undefined (i.e. the segment
 * carries no speaker info — typically a transcription without diarization).
 * Returns the raw value when `raw` is non-empty but not in the label map
 * (defensive fallback; should not happen if labelMap was built from the
 * same segment list).
 */
export function labelFor(
  raw: string | null | undefined,
  labelMap: ReadonlyMap<string, string>,
): string {
  if (!raw) return '';
  return labelMap.get(raw) ?? raw;
}
