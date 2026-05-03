---
title: 'GH-73: Multitrack Recording Support'
type: 'feature'
created: '2026-04-11'
status: 'done'
baseline_commit: 'b0ea558'
context: ['docs/architecture-server.md', 'docs/api-contracts-server.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Multi-channel audio files (podcasts, film sound, panels, TTRPG recordings) are silently mixed to mono during upload, destroying per-speaker isolation that hardware multitrack recorders provide. Users must manually split channels before uploading.

**Approach:** Add an opt-in `multitrack` parameter to the transcription API. When enabled, detect channels via ffprobe, filter silent channels by dB threshold, extract each active channel to a temp mono file, transcribe each sequentially, and merge results into a unified speaker-labeled transcript using the existing `build_speaker_segments()` pipeline. Diarization is skipped — each channel IS one speaker.

## Boundaries & Constraints

**Always:**
- Opt-in only (`multitrack` form field, default false); default behavior unchanged
- Skip diarization when multitrack is active — channel = speaker
- Reuse `build_speaker_segments()` for merging per-track word lists
- Clean up all temp channel files after processing
- Persist result to durable storage before delivery (critical project invariant)
- Process channels sequentially within one transcription job
- Single-channel files with multitrack=true fall through to standard transcription

**Ask First:**
- Changing silence threshold from -60 dBFS (if -80 dBFS preferred per issue)
- Adding multitrack as a server-side config default vs. purely per-request

**Never:**
- Parallel channel transcription (model is single-instance)
- Per-channel naming UI (v2)
- Multi-stream container support (focus on multi-channel PCM)
- Sub-diarization within a single channel

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy: 4-ch podcast | 4-channel WAV, multitrack=true | Merged transcript, 4 speakers, interleaved by time | N/A |
| 2 active + 2 silent | 4-ch, ch3/ch4 below threshold | Only ch1/ch2 transcribed and merged | Log silent channels skipped |
| Single channel | Mono WAV, multitrack=true | Standard transcription, no split | Log: "single channel, skipping multitrack" |
| All channels silent | 4-ch, all below threshold | Empty result with warning | Return error message to client |
| Stereo forced | 2-ch WAV, multitrack=true | 2 speakers in merged transcript | N/A |
| Default (multitrack=false) | Any multi-ch file | Current mono-mix behavior | N/A |
| Non-audio file | Invalid file, multitrack=true | Existing error handling unchanged | ffprobe failure falls back to standard path |

</frozen-after-approval>

## Code Map

- `server/backend/core/multitrack.py` -- NEW: probe_channels(), filter_silent_channels(), split_channels(), merge_track_results()
- `server/backend/api/routes/transcription.py:67` -- MODIFY: add multitrack Form param, route multitrack files through new pipeline
- `server/backend/core/speaker_merge.py:204` -- READ-ONLY: reuse build_speaker_segments() for merge
- `server/backend/core/stt/engine.py:50` -- READ-ONLY: TranscriptionResult structure
- `dashboard/components/views/SessionView.tsx` -- MODIFY: add multitrack toggle in transcription options
- `dashboard/src/hooks/useTranscription.ts` -- MODIFY: pass multitrack option in upload form data

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/multitrack.py` -- CREATE module: probe_channels, filter_silent_channels, split_channels, merge_track_results, transcribe_multitrack
- [x] `server/backend/api/routes/transcription.py` -- ADD multitrack: bool = Form(False) to /audio and /import routes; multitrack pipeline before diarization path
- [x] `dashboard/components/views/SessionImportTab.tsx` -- ADD multitrack toggle with mutual exclusivity vs diarization
- [x] `dashboard/src/api/types.ts` + `dashboard/src/api/client.ts` -- PASS multitrack flag in FormData for all upload methods
- [x] `server/backend/tests/test_multitrack.py` -- ADD 28 unit tests for probe, filter, split, merge, and full pipeline

**Acceptance Criteria:**
- Given a 4-channel WAV with 2 silent channels, when transcribed with multitrack=true, then result contains 2 speakers with correctly merged word timings sorted by timestamp
- Given a mono file with multitrack=true, then standard transcription occurs with no multitrack processing
- Given multitrack=false (default), then multi-channel files are mixed to mono as before
- Given all channels below silence threshold, then client receives an error message

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_multitrack.py -v --tb=short` -- expected: all tests pass
- Upload a multi-channel test file via dashboard with multitrack toggle enabled -- expected: per-speaker transcript with channel-based speaker labels

## Suggested Review Order

**Core multitrack pipeline**

- Entry point: high-level pipeline orchestrating probe → filter → split → transcribe → merge
  [`multitrack.py:291`](../../server/backend/core/multitrack.py#L291)

- Channel detection via ffprobe with timeout and MAX_CHANNELS cap
  [`multitrack.py:40`](../../server/backend/core/multitrack.py#L40)

- Silent channel filtering by dBFS threshold
  [`multitrack.py:118`](../../server/backend/core/multitrack.py#L118)

- Channel extraction to temp mono WAV files via ffmpeg
  [`multitrack.py:132`](../../server/backend/core/multitrack.py#L132)

- Result merge using canonical `build_speaker_segments()` with pre-assigned speaker labels
  [`multitrack.py:188`](../../server/backend/core/multitrack.py#L188)

**Route integration**

- Sync `/audio` route: multitrack param + early return before diarization path
  [`transcription.py:78`](../../server/backend/api/routes/transcription.py#L78)

- Background `/import` route: multitrack path with job_tracker persistence + webhook
  [`transcription.py:556`](../../server/backend/api/routes/transcription.py#L556)

**Frontend**

- Multitrack toggle with mutual exclusivity vs diarization
  [`SessionImportTab.tsx:669`](../../dashboard/components/views/SessionImportTab.tsx#L669)

- FormData passthrough in all 3 upload methods
  [`client.ts:360`](../../dashboard/src/api/client.ts#L360)

- Type definition
  [`types.ts:105`](../../dashboard/src/api/types.ts#L105)

**Tests**

- 27 unit tests covering probe, filter, split, merge, pipeline, and edge cases
  [`test_multitrack.py:1`](../../server/backend/tests/test_multitrack.py#L1)
