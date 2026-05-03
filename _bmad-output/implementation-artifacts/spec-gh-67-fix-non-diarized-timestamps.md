---
title: 'GH-67: Fix non-diarized import output to include timestamps'
type: 'bugfix'
created: '2026-04-10'
status: 'done'
baseline_commit: '47d9139'
context:
  - docs/api-contracts-server.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Session import always writes plain `.txt` with no timecodes when diarization is off, even when timestamps are enabled and segments carry timing data. The branching logic in `resolveTranscriptionOutput` gates timed formats exclusively on `diarizationPerformed`, ignoring `hideTimestamps`.

**Approach:** Restructure the output selection logic so `hideTimestamps` is the primary gate for plain text vs timed output. When timestamps are not hidden and segments exist, use the user's format preference (`diarizedFormat`) for SRT/ASS output regardless of diarization status. The existing renderers (`renderSrt`, `renderAss`) already handle absent speaker data gracefully.

## Boundaries & Constraints

**Always:**
- Preserve existing diarized output behavior exactly (SRT/ASS with speaker labels).
- When `hideTimestamps` is true, always output `.txt` (existing early-exit at line 161).
- Fall back to `.txt` when `transcription.segments` is empty or missing, even if timestamps are enabled.

**Ask First:**
- Renaming `diarizedFormat` to a more accurate name like `timedFormat` (semantic cleanup, separate concern).
- Adding word-level timestamp rendering (out of scope per issue, but flagged).

**Never:**
- Change server-side transcription logic — this is a client-side formatting bug only.
- Alter `renderSrt` or `renderAss` internals — they already work without speakers.
- Remove or change the `diarizationPerformed` field from the options type.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Diarization OFF, timestamps ON, segments present | `hideTimestamps: false`, `diarizationPerformed: false`, segments: `[{start,end,text}]` | `{stem}.srt` or `{stem}.ass` (per `diarizedFormat`) with timecodes, no speaker labels | N/A |
| Diarization OFF, timestamps ON, segments empty | `hideTimestamps: false`, `diarizationPerformed: false`, segments: `[]` | `{stem}.txt` with plain text | N/A |
| Diarization OFF, timestamps OFF | `hideTimestamps: true`, `diarizationPerformed: false` | `{stem}.txt` with plain text | N/A |
| Diarization ON, timestamps ON | `hideTimestamps: false`, `diarizationPerformed: true`, segments with speakers | `{stem}.srt` or `{stem}.ass` with timecodes + speaker labels (unchanged) | N/A |
| Diarization ON, timestamps OFF | `hideTimestamps: true`, `diarizationPerformed: true` | `{stem}.txt` with plain text (unchanged) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/services/transcriptionFormatters.ts` -- bug site: `resolveTranscriptionOutput` output selection logic (lines 165-173)
- `dashboard/src/stores/importQueueStore.ts` -- caller 1: passes options at line ~268
- `dashboard/src/hooks/useSessionImportQueue.ts` -- caller 2: passes options at line ~187

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/transcriptionFormatters.ts` -- Restructure `resolveTranscriptionOutput` branching: after the existing `hideTimestamps` early exit, check whether `transcription.segments` has entries; if yes, use `diarizedFormat` for filename and the matching renderer; if no segments, fall back to `.txt` with `renderTxt` -- Decouples timed output from diarization status
- [x] `dashboard/src/services/transcriptionFormatters.test.ts` -- Add 13 unit tests covering all I/O matrix scenarios (renderers + resolveTranscriptionOutput) -- Prevents regression

**Acceptance Criteria:**
- Given diarization OFF, word-level timestamps ON, and hide-timestamps OFF, when a file is imported and transcription completes, then the output file is `.srt` (or `.ass` per preference) with parseable timecodes.
- Given hide-timestamps ON, when a file is imported regardless of diarization, then the output file is `.txt` with plain text only.
- Given diarization ON, when a file is imported, then SRT/ASS output with speaker labels is unchanged from current behavior.
- Given segments array is empty or undefined, when output is resolved, then the output falls back to `.txt` regardless of other settings.

## Verification

**Commands:**
- `cd dashboard && npx vitest run src/services/transcriptionFormatters.test.ts` -- expected: all tests pass
- `cd dashboard && npx vitest run` -- expected: no regressions in existing test suite

## Suggested Review Order

- Decision cascade replaces diarization-gated ternary with segments-presence check
  [`transcriptionFormatters.ts:165`](../../dashboard/src/services/transcriptionFormatters.ts#L165)

- Early-exit for `hideTimestamps` preserved unchanged (context for the new logic below it)
  [`transcriptionFormatters.ts:161`](../../dashboard/src/services/transcriptionFormatters.ts#L161)

- Empty-segments fallback returns `.txt` with plain text
  [`transcriptionFormatters.ts:175`](../../dashboard/src/services/transcriptionFormatters.ts#L175)

- 13 unit tests covering all I/O matrix scenarios plus renderer edge cases
  [`transcriptionFormatters.test.ts:1`](../../dashboard/src/services/transcriptionFormatters.test.ts#L1)
