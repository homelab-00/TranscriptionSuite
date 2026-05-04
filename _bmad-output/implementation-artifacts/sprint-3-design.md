---
sprint: 3
date: 2026-05-04
project: TranscriptionSuite
issue: 104
epic_set: [epic-aliases-mvp (E4) Stories 4.1–4.5; epic-aliases-growth (E5) Stories 5.1–5.9]
prereq: Sprint 1 DONE (commits ec6acee, 1a77d50, 38c1e59, 0888bc8, 6116b19); Sprint 2 merged (gh-104-prd HEAD)
budget_dev_days: 5–7 (E4) + 7–9 (E5) ≈ 12–16 dev-days
target_loc_ceiling: ≤4500 LOC (sprint prompt allows larger envelope for this sprint)
ac_overrides_required: yes (URL-prefix, confidence sourcing, segments-confidence column omitted)
---

# Sprint 3 — Speakers (alias MVP + propagation + diarization review) Design

This sprint implements 14 stories that all share one data backbone:
the `recording_speaker_aliases` table plus a single read-time
substitution function consumed by every surface that ever renders a
speaker label. Same pattern as Sprint 1/2 — overrides up front, then
through-lines, then per-story design.

---

## 0. Sprint 1/2 prerequisite verification

Audit run before this design pass:

| Prerequisite | Path | Status |
|---|---|---|
| `recording_diarization_review` table | migration 010 | PRESENT |
| `diarization_review_repository.py` | `database/diarization_review_repository.py` | PRESENT (status helpers, no lifecycle yet) |
| ARIA live region + `useAriaAnnouncer` | `dashboard/components/AriaLiveRegion.tsx`, `dashboard/src/hooks/useAriaAnnouncer.ts` | PRESENT |
| `QueuePausedBanner` primitive | `dashboard/components/ui/QueuePausedBanner.tsx` | PRESENT |
| Plain-text streaming exporter | `server/backend/core/plaintext_export.py` | PRESENT |
| Subtitle exporter (SRT/ASS) | `server/backend/core/subtitle_export.py` | PRESENT |
| `notebook.py::export_recording` (`format=plaintext`) | `api/routes/notebook.py:998` | PRESENT |
| LLM summary route | `api/routes/llm.py::summarize_recording` | PRESENT |
| LLM chat route | `api/routes/llm.py::chat_with_llm` | PRESENT |
| Migrations 008–013 in place | `database/migrations/versions/` | PRESENT (next free = **014**) |

All Sprint 3 work can build on these.

---

## 1. Inline AC overrides (read first)

| AC literal text | Reality | Override |
|---|---|---|
| Story 4.2 AC1: `GET /api/recordings/{id}/aliases` | There is no top-level `/api/recordings/*` router; recordings live under `/api/notebook/recordings/*` (notebook.py mounted at `/api/notebook`). | Mount alias endpoints on the **notebook** router as `GET/PUT /api/notebook/recordings/{id}/aliases`. URL-shape difference is purely a prefix; the contract (path-tail + body) is intact. Same precedent as Sprint 2 (Story 2.4 dedup endpoint, Story 3.6 reexport). |
| Story 5.4 AC1: `GET /api/recordings/{id}/diarization-confidence` | Same router collision. | Mount as `GET /api/notebook/recordings/{id}/diarization-confidence`. |
| Story 5.9 AC5: `POST /api/recordings/{id}/diarization-review` | Same router collision. | Mount as `POST /api/notebook/recordings/{id}/diarization-review`. |
| Story 5.4 AC1: "confidence sourced from pyannote-emitted scores already stored on the existing transcription artifact" | The current schema stores **per-word** confidence on `words.confidence`. There is no per-segment confidence column; `segments` carries `(speaker, text, start_time, end_time)` only. | Per-turn confidence is **derived** at API time as the arithmetic mean of the segment's word-level `confidence` values (NULL words excluded). When a segment has zero usable word-confidence values, the turn is omitted from the response (Story 5.4 AC2 "empty fallback" applies on a per-turn basis). The endpoint never adds a column, never re-runs diarization. |
| Story 5.5 AC1 buckets: high ≥ 0.8 (no chip), medium 0.6–0.8 (neutral chip), low < 0.6 (amber) | UX-DR3 (PRD §922) carries the same buckets. | Buckets canonicalized in `dashboard/src/utils/confidenceBuckets.ts` so backend (Story 5.6 trigger predicate) and frontend (Story 5.5 chip + Story 5.7 banner threshold) agree. The Python side mirrors the same constants in `server/backend/core/diarization_confidence.py`. |
| Story 5.6 AC1: insert pending row "when transcription completes with at least one turn at confidence < 0.6" | Transcription completion is multi-path: longform (transcription.py worker), notebook upload (notebook.py upload). Each has a different completion site. Hooking each is invasive. | Sprint 3 wires the trigger only on the **notebook upload completion path** (the path that exercises diarization for J4 — researcher uploads recording, opens detail view, sees banner). Longform/import paths do diarization but their completion lifecycle is owned by the durability worker; that hook is captured as deferred work for Sprint 4 alongside Story 6.2 auto-summary. **Documented in §6.** |
| Story 5.7 AC1: banner uses `QueuePausedBanner` visual primitive | `QueuePausedBanner.tsx` is a specific component (paused queue UI). Per UX-DR2 the banner is a **visual primitive pattern** — yellow/amber background, full-width, top of detail view — not an import of that exact component. | Create `dashboard/components/ui/PersistentInfoBanner.tsx` mirroring `QueuePausedBanner` styling (same Tailwind tokens), parameterized by `severity` and `cta`. The two components share the same visual language; per the project's UI-contract policy, the new component's classes are added to the contract baseline. |
| Story 5.8 AC1 says auto-summary is SKIPPED with HOLD predicate | The auto-summary lifecycle itself does not exist yet — it lands in Sprint 4 Story 6.2. | This sprint exposes only the predicate function `auto_summary_is_held(recording_id) -> bool` plus a fake-consumer test asserting it. Story 6.2 in Sprint 4 will import and call it. Documented at the call site. |
| Story 5.9 AC6: `pytest-benchmark` linearity nightly | Benchmark wiring under `pytest-benchmark` is not currently in the test infra. | Implement filter linearity test in standard pytest using `time.perf_counter_ns` over 4 sample sizes; assert `r²>0.95` via numpy linregress (already a transitive dep) and p95 <200ms at N=100. The "nightly" framing becomes a `@pytest.mark.slow` marker; the per-PR assertion (p95<200ms at N=100) runs on every push. |
| Story 4.4 AC2 "≥4 propagation snapshots" | The "4 propagation surfaces" are: (1) transcript view rendering, (2) plain-text export, (3) subtitle export, (4) AI summary prompt, (5) AI chat context. That's 5, not 4. | Snapshot test count: 1 view + 1 plaintext + 1 subtitle + 1 summary-prompt + 1 chat-context = **5 snapshots**, exceeding the ≥4 floor. Distributed across commit B (view) and commit D (the four backend surfaces). |

**Not an override but worth recording:** The `segments.speaker` column stores
the **raw diarization label** the engine emits (e.g. `SPEAKER_00`,
`SPEAKER_01` from pyannote). That raw label IS the `speaker_id` for
alias storage. The frontend's existing `buildSpeakerMap` (in
`dashboard/src/services/transcriptionFormatters.ts`) converts raw → "Speaker N"
by appearance. The alias system layers on top: alias takes precedence,
otherwise fall back to the existing "Speaker N" mapping.

---

## 2. Architectural through-lines

### 2.1 Alias storage + READ-TIME substitution invariant (R-EL3)

```sql
-- migration 014
CREATE TABLE IF NOT EXISTS recording_speaker_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    speaker_id TEXT NOT NULL,
    alias_name TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
    UNIQUE (recording_id, speaker_id)
);
CREATE INDEX IF NOT EXISTS idx_recording_speaker_aliases_recording_id
    ON recording_speaker_aliases(recording_id);
```

**Invariant — no transcript mutation anywhere:**
- `segments.speaker` is **never updated** by alias work. The PUT
  endpoint writes only into `recording_speaker_aliases`.
- All consumers (view, plaintext, subtitle, summary, chat) read
  `segments` AS-IS and apply aliases via a single helper at render time.
- This is what R-EL3 ("verbatim guarantee") protects: the stored
  artifact is the ground truth; alias edits are an overlay.

**Substitution helper (`server/backend/core/alias_substitution.py`):**

```python
"""Read-time alias substitution (Issue #104, Stories 4.4 / 5.1 / 5.2 / 5.3).

Single source of truth for "what speaker name does this surface render?"
Consumers: subtitle exporter, plaintext exporter, AI summary prompt,
AI chat context. The transcript-view substitution lives in the
dashboard so the renderer can re-render after a PUT without a server
round-trip; the *fallback labels* must agree across both layers, which
is what `default_label_for(speaker_id, raw_order)` enforces.

Stored transcript is never modified — see R-EL3.
"""
from __future__ import annotations
from collections.abc import Iterable, Iterator, Mapping
from typing import Any


def build_speaker_label_map(
    segments: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> dict[str, str]:
    """Return raw_speaker_id → display_label.

    `aliases` maps `speaker_id` → `alias_name` (typically the result of
    `recording_speaker_aliases` lookup for the recording). Where an
    alias is absent, the raw label gets a fallback "Speaker N" assigned
    in first-appearance order, matching the dashboard's existing
    `buildSpeakerMap` in `transcriptionFormatters.ts`.
    """
    labels: dict[str, str] = {}
    next_index = 1
    for seg in segments:
        raw = seg.get("speaker")
        if not raw or raw in labels:
            continue
        if raw in aliases:
            labels[raw] = aliases[raw]
        else:
            labels[raw] = f"Speaker {next_index}"
            next_index += 1
    return labels


def apply_aliases(
    segments: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> Iterator[dict[str, Any]]:
    """Yield COPIES of segments with `speaker` replaced by display label.

    Lazy (generator) — preserves the bounded-RAM property of
    `iter_segments` (Sprint 2 plaintext exporter).

    Verbatim guarantee (R-EL3): the alias_name is substituted EXACTLY as
    stored — no NFC normalization, no truncation, no nickname inference.
    SQLite's TEXT column already preserves arbitrary Unicode bytes; we
    just pass the value through.
    """
    label_map: dict[str, str] = {}
    next_index = 1

    def _label_for(raw: str | None) -> str | None:
        if raw is None:
            return None
        if raw not in label_map:
            if raw in aliases:
                label_map[raw] = aliases[raw]
            else:
                nonlocal next_index
                label_map[raw] = f"Speaker {next_index}"
                next_index += 1
        return label_map[raw]

    for seg in segments:
        copy = dict(seg)
        copy["speaker"] = _label_for(seg.get("speaker"))
        yield copy


def speaker_key_preface(
    aliases: Mapping[str, str],
    raw_order: list[str],
) -> str:
    """Construct the "Speaker key:" preamble for LLM prompts (Story 5.2).

    Format: ``Speakers in this transcript: Elena Vasquez (spk_0),
    Marco Rivera (spk_1), Speaker 3 (spk_2 — unaliased)``.
    """
    if not raw_order:
        return ""
    parts: list[str] = []
    next_index = 1
    seen: set[str] = set()
    for raw in raw_order:
        if raw in seen:
            continue
        seen.add(raw)
        if raw in aliases:
            parts.append(f"{aliases[raw]} ({raw})")
        else:
            parts.append(f"Speaker {next_index} ({raw} — unaliased)")
            next_index += 1
    return "Speakers in this transcript: " + ", ".join(parts) + "."
```

The function is pure (no I/O), so propagation tests are deterministic
golden snapshots.

### 2.2 Confidence derivation (per-turn) — Story 5.4 backbone

```python
# server/backend/core/diarization_confidence.py — new helper
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Any

# Constants mirrored in dashboard/src/utils/confidenceBuckets.ts
HIGH_CONFIDENCE_THRESHOLD = 0.8
LOW_CONFIDENCE_THRESHOLD = 0.6


def bucket_for(confidence: float) -> str:
    """Return 'high' / 'medium' / 'low' per UX-DR3."""
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= LOW_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def per_turn_confidence(
    segments: Iterable[Mapping[str, Any]],
    words: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return [{turn_index, speaker_id, confidence}, ...] for the recording.

    Per-turn confidence is the arithmetic mean of word-level
    confidence values within the segment. Words with NULL confidence
    are skipped. Segments with zero usable word-confidence values are
    omitted (the dashboard treats absent turns as "no chip" — Story
    5.5 AC2 graceful fallback).
    """
    by_segment: dict[int, list[float]] = {}
    for w in words:
        seg_id = w.get("segment_id")
        c = w.get("confidence")
        if seg_id is None or c is None:
            continue
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        by_segment.setdefault(int(seg_id), []).append(cf)

    out: list[dict[str, Any]] = []
    for seg in segments:
        seg_id = seg.get("id")
        if seg_id is None:
            continue
        scores = by_segment.get(int(seg_id))
        if not scores:
            continue
        out.append({
            "turn_index": seg.get("segment_index", 0),
            "speaker_id": seg.get("speaker"),
            "confidence": round(sum(scores) / len(scores), 4),
        })
    return out
```

**Why mean over word-confidences?** Pyannote's segment-level scores
aren't currently persisted; word-level confidence is. The mean is a
defensible proxy under the same monotonicity assumption (low
word-confidence segments are also low diarization-confidence). The
UX-DR3 spec is bucket-based, so bucket-stability matters more than
exact percentage agreement with pyannote's internal score.

**Storage decision:** No new column. The endpoint computes on demand.
Cost analysis: a 60-min recording has ~6k–12k words; aggregation is
O(words) which on SQLite is ~5ms. Sprint 3 gets the API contract
right; if perf becomes a hotspot a denormalized `segments.confidence`
column is a one-migration fix in Sprint 4.

### 2.3 ADR-009 lifecycle state machine (Story 5.6 backbone)

```python
# server/backend/core/diarization_review_lifecycle.py — new module
"""ADR-009 lifecycle state machine.

States: pending → in_review → completed → released
Triggers (one transition per trigger; order is sequential):
  - on_transcription_complete()      → insert pending (only if low-conf turns)
  - on_review_view_opened()          → pending → in_review
  - on_run_summary_now_clicked()     → in_review → completed
  - on_auto_summary_fired()          → completed → released

Banner predicate:        status IN {'pending', 'in_review'}
Auto-summary HOLD:       status NOT IN {'released'}  (i.e. != 'released')

The state machine NEVER skips intermediate states. Going pending → released
directly is a bug — every exit path must pass through completed.
"""
from __future__ import annotations
import logging
from server.database import diarization_review_repository as repo

logger = logging.getLogger(__name__)

# ---- transition predicates (used by callers; raise if illegal) -------

_VALID_TRANSITIONS: dict[str | None, set[str]] = {
    None:        {"pending"},
    "pending":   {"in_review"},
    "in_review": {"completed"},
    "completed": {"released"},
    "released":  set(),  # terminal
}


class IllegalReviewTransitionError(RuntimeError):
    pass


def _transition(recording_id: int, target: str) -> None:
    row = repo.get_review(recording_id)
    current = row["status"] if row else None
    if target not in _VALID_TRANSITIONS.get(current, set()):
        raise IllegalReviewTransitionError(
            f"recording {recording_id}: {current!r} → {target!r} not allowed"
        )
    if current is None:
        repo.create_review(recording_id, status=target)
    else:
        repo.update_status(recording_id, target)


# ---- public trigger functions -----------------------------------------

def on_transcription_complete(recording_id: int, has_low_confidence_turn: bool) -> None:
    """Insert pending row IFF at least one turn is low-confidence."""
    if not has_low_confidence_turn:
        return  # no row → no banner → no HOLD
    _transition(recording_id, "pending")


def on_review_view_opened(recording_id: int) -> bool:
    """pending → in_review. Returns True if a transition occurred."""
    row = repo.get_review(recording_id)
    if not row or row["status"] != "pending":
        return False
    _transition(recording_id, "in_review")
    return True


def on_run_summary_now_clicked(recording_id: int) -> None:
    _transition(recording_id, "completed")


def on_auto_summary_fired(recording_id: int) -> None:
    _transition(recording_id, "released")


# ---- predicates consumed by Stories 5.7 / 5.8 -------------------------

def banner_visible(recording_id: int) -> bool:
    row = repo.get_review(recording_id)
    return bool(row) and row["status"] in {"pending", "in_review"}


def auto_summary_is_held(recording_id: int) -> bool:
    """True iff auto-summary should be HELD for this recording.

    Story 5.8 AC1 — the predicate is read by the auto-summary lifecycle
    hook (which lands in Sprint 4 Story 6.2). Manual summary always
    bypasses HOLD (Story 5.8 AC3 is enforced at the call site, not here).
    """
    row = repo.get_review(recording_id)
    if not row:
        return False  # no review row at all → no HOLD
    return row["status"] != "released"
```

**Persistence-Before-Deliver invariant:** every public trigger calls
`repo.{create_review,update_status}` which already commit before
returning (Sprint 1 Story 1.9 invariant). So any HTTP route that
invokes a trigger and then returns is automatically Persist-Before-Deliver.

### 2.4 Cross-cutting accessibility (Story 5.9 keyboard contract)

The Diarization-Review Keyboard Contract (PRD §900–920) is a
**WAI-ARIA composite-widget pattern**. Implementation skeleton:

```tsx
// dashboard/components/recording/DiarizationReviewView.tsx (excerpt)
function DiarizationReviewTurnList({turns, ...}: Props) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [activeAttributionIndex, setActiveAttributionIndex] = useState(0);
  const announce = useAriaAnnouncer();
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); moveSelection(+1); break;
      case 'ArrowUp':   e.preventDefault(); moveSelection(-1); break;
      case 'ArrowLeft': e.preventDefault(); cycleAttribution(-1); break;
      case 'ArrowRight': e.preventDefault(); cycleAttribution(+1); break;
      case 'Enter':     e.preventDefault(); acceptCurrent(); break;
      case 'Escape':    e.preventDefault(); skipCurrent(); break;
      case ' ':         e.preventDefault(); bulkAccept(); break;  // Space
    }
  };

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Uncertain turns to review"
      aria-activedescendant={`turn-${turns[activeIndex]?.turn_index}`}
      tabIndex={0}            // single tab stop
      onKeyDown={onKeyDown}
    >
      {turns.map((t, i) => (
        <div
          id={`turn-${t.turn_index}`}
          role="option"
          aria-selected={i === activeIndex}
          aria-label={`${t.text} · current speaker: ${t.speaker_label} · confidence: ${t.bucket}`}
          key={t.turn_index}
        >
          {/* ... per-turn UI ... */}
        </div>
      ))}
    </div>
  );
}
```

Tab order in the surrounding view: review-banner → confidence-filter →
turn-list (single tab stop) → bulk-action button → "Run summary now"
button. Focus traps are NOT used — Esc inside the turn-list cycles
turns; Esc outside the list (on the dialog wrapper) closes the view.

---

## 3. Per-story design

### Story 4.1 — `recording_speaker_aliases` table migration

Migration **014** matches the schema in §2.1. `downgrade()` raises
`RuntimeError("forward-only migration — see NFR22")` per project
convention. Tests:
- `tests/test_alias_table_migration.py` — apply migration to fresh
  fixture DB; assert table + index exist; FK enforced (insert with
  unknown `recording_id` raises `IntegrityError`).
- Per-recording scope (AC3): two recordings, alias_name="Elena" in
  both — both rows insert successfully (separate `recording_id`).

### Story 4.2 — REST endpoints

**Repository (`server/backend/database/alias_repository.py`, new):**

```python
from __future__ import annotations
from datetime import UTC, datetime
from server.database.database import get_connection


def list_aliases(recording_id: int) -> list[dict]:
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT speaker_id, alias_name "
                "FROM recording_speaker_aliases WHERE recording_id = ? "
                "ORDER BY speaker_id",
                (recording_id,),
            ).fetchall()
        ]


def replace_aliases(recording_id: int, aliases: list[dict]) -> None:
    """Full-replace: delete rows for speaker_ids not in `aliases`,
    upsert the rest. One transaction; commit before returning
    (NFR16 Persist-Before-Deliver).
    """
    now = datetime.now(UTC).isoformat()
    incoming_ids = {a["speaker_id"] for a in aliases}
    with get_connection() as conn:
        cur = conn.cursor()
        if incoming_ids:
            placeholders = ",".join("?" * len(incoming_ids))
            cur.execute(
                f"DELETE FROM recording_speaker_aliases "
                f"WHERE recording_id = ? AND speaker_id NOT IN ({placeholders})",
                (recording_id, *incoming_ids),
            )
        else:
            cur.execute(
                "DELETE FROM recording_speaker_aliases WHERE recording_id = ?",
                (recording_id,),
            )
        for a in aliases:
            cur.execute(
                """
                INSERT INTO recording_speaker_aliases
                    (recording_id, speaker_id, alias_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recording_id, speaker_id) DO UPDATE SET
                    alias_name = excluded.alias_name,
                    updated_at = excluded.updated_at
                """,
                (recording_id, a["speaker_id"], a["alias_name"], now, now),
            )
        conn.commit()
```

**Routes (additions to `api/routes/notebook.py`):**

```python
class AliasItem(BaseModel):
    speaker_id: str
    alias_name: str

class AliasesPayload(BaseModel):
    aliases: list[AliasItem]

class AliasesResponse(BaseModel):
    recording_id: int
    aliases: list[AliasItem]


@router.get("/recordings/{recording_id}/aliases", response_model=AliasesResponse)
async def list_recording_aliases(recording_id: int) -> AliasesResponse:
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return AliasesResponse(
        recording_id=recording_id,
        aliases=[AliasItem(**a) for a in alias_repository.list_aliases(recording_id)],
    )


@router.put("/recordings/{recording_id}/aliases", response_model=AliasesResponse)
async def update_recording_aliases(
    recording_id: int, payload: AliasesPayload
) -> AliasesResponse:
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    # Trim alias names but never normalize Unicode (R-EL3 verbatim).
    cleaned = [
        {"speaker_id": a.speaker_id, "alias_name": a.alias_name.strip()}
        for a in payload.aliases
        if a.alias_name.strip()
    ]
    alias_repository.replace_aliases(recording_id, cleaned)
    return AliasesResponse(
        recording_id=recording_id,
        aliases=[AliasItem(**a) for a in alias_repository.list_aliases(recording_id)],
    )
```

Tests: `tests/test_alias_routes.py` covers GET-empty, PUT upsert,
PUT delete-by-omission (full-replace semantics), 404 on unknown
recording, Persist-Before-Deliver via `monkeypatch` on `sqlite3.Connection.commit`.

### Story 4.3 — Speaker rename UI

**Component (`dashboard/components/recording/SpeakerRenameInput.tsx`, new):**

- Prop: `currentLabel`, `onCommit(newName: string)`, `onCancel()`,
  `aria-label` for the input.
- Behavior: Click or Enter on the speaker label → input pre-filled;
  Enter commits, Esc cancels, blur commits.

Wired into `AudioNoteModal.tsx` at the `seg.speaker` render site
(line ~2052). The modal owns a small subscription to React Query's
`['notebook-aliases', recording_id]`.

**Hook (`dashboard/src/hooks/useRecordingAliases.ts`, new):**

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

interface Alias { speaker_id: string; alias_name: string; }
interface AliasesResponse { recording_id: number; aliases: Alias[]; }

export function useRecordingAliases(recordingId: number) {
  return useQuery<AliasesResponse>({
    queryKey: ['notebook-aliases', recordingId],
    queryFn: () => api.get(`/api/notebook/recordings/${recordingId}/aliases`),
    enabled: Number.isFinite(recordingId) && recordingId > 0,
  });
}

export function useUpdateRecordingAliases(recordingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (aliases: Alias[]) =>
      api.put(`/api/notebook/recordings/${recordingId}/aliases`, { aliases }),
    onSuccess: (next) =>
      qc.setQueryData(['notebook-aliases', recordingId], next),
  });
}
```

A11y: input has `aria-label="Speaker label for {speaker_id}"`; ARIA
announcement on focus uses Sprint 1 `useAriaAnnouncer`:
`announce("Edit speaker label, current value: {current_label}")`.

### Story 4.4 — Alias substitution at view render

The dashboard parallel of `apply_aliases()` lives at
`dashboard/src/utils/aliasSubstitution.ts`:

```typescript
export interface AliasMap { [speakerId: string]: string; }

export function buildSpeakerLabelMap(
  segments: { speaker?: string | null }[],
  aliases: AliasMap,
): Map<string, string> {
  const labels = new Map<string, string>();
  let next = 1;
  for (const seg of segments) {
    const raw = seg.speaker;
    if (!raw || labels.has(raw)) continue;
    if (raw in aliases) labels.set(raw, aliases[raw]);
    else labels.set(raw, `Speaker ${next++}`);
  }
  return labels;
}

export function labelFor(
  raw: string | null | undefined,
  labelMap: Map<string, string>,
): string {
  return raw ? (labelMap.get(raw) ?? raw) : '';
}
```

`AudioNoteModal.tsx` renders via `labelFor(seg.speaker, labelMap)`
instead of `seg.speaker` directly. The label map is rebuilt from
`aliasesQuery.data?.aliases` on every change — cheap, since segments
list is already O(N) for render.

**Sync test:** `tests/test_alias_substitution_resolvers_sync.py` reads
the TS file and asserts the bucket math + first-appearance fallback
behavior matches the Python `build_speaker_label_map`. Catches drift.

**Snapshot test (NFR52):**
`dashboard/components/recording/__tests__/SpeakerLabelRendering.test.tsx`
fixture: 5 speakers, 2 aliased; assert rendered HTML matches a golden
snapshot.

### Story 4.5 — FK cascade verification

Test only — no production code changes. Migration 014's
`ON DELETE CASCADE` does the work; this story proves it:

```python
# tests/test_alias_cascade_on_recording_delete.py
def test_alias_rows_cascade(database_at_head):
    rec_id = _insert_test_recording()
    alias_repository.replace_aliases(rec_id, [
        {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
        {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        {"speaker_id": "SPEAKER_02", "alias_name": "Sami"},
    ])
    assert len(alias_repository.list_aliases(rec_id)) == 3

    delete_recording(rec_id)

    assert len(alias_repository.list_aliases(rec_id)) == 0
```

A second test does `iterdump()` → fresh `:memory:` connection (Sprint 1
pattern from `test_diarization_review_state_survives_restore`) and
re-runs the cascade to prove FK survives restore.

### Story 5.1 — Alias propagation: plaintext + subtitles

**Plaintext exporter:** `stream_plaintext` already iterates segments;
the route layer applies aliases first:

```python
# notebook.py::export_recording — plaintext branch update
if requested_format == "plaintext":
    aliases = {a["speaker_id"]: a["alias_name"]
               for a in alias_repository.list_aliases(recording_id)}
    return StreamingResponse(
        stream_plaintext(recording, apply_aliases(iter_segments(recording_id), aliases)),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": _content_disposition("attachment", rendered_filename)},
    )
```

**Subtitle exporter:** the existing `subtitle_export.normalize_speaker_labels`
maps raw → "Speaker N". For aliases, build the cue list with
substituted speaker names — refactored as:

```python
# subtitle_export.py — small change in build_subtitle_cues
def build_subtitle_cues(
    segments, words, has_diarization,
    *, alias_overrides: Mapping[str, str] | None = None,  # NEW
) -> list[SubtitleCue]:
    ...
    normalized_speakers = normalize_speaker_labels(raw_speaker_order)
    if alias_overrides:
        # Override "Speaker N" with alias_name where speaker_id (raw) has alias.
        for raw, alias in alias_overrides.items():
            if raw in normalized_speakers:
                normalized_speakers[raw] = alias
    ...
```

The route layer passes `alias_overrides` from `alias_repository.list_aliases`.

**Snapshot tests:**
- `tests/test_plaintext_alias_propagation_snapshot.py` — fixture
  recording with `SPEAKER_00→"Elena Vasquez"`, `SPEAKER_01→"Marco Rivera"`;
  full plaintext output matches golden.
- `tests/test_subtitle_alias_propagation_snapshot.py` — same fixture;
  SRT output matches golden.

### Story 5.2 — Alias propagation: AI summary prompt

Modify `summarize_recording` (and `summarize_recording_stream`) to:
1. Load aliases for `recording_id`.
2. Build `full_text` using `apply_aliases(transcription["segments"], aliases)`.
3. Prepend `speaker_key_preface(aliases, raw_order)` to the prompt.
4. Append a system-prompt augmentation:
   `"Use the speaker names provided verbatim. Do not infer relationships, abbreviate, or merge names."`
   (R-EL3 enforcement — the model is told the names are authoritative.)

The change is localized to `llm.py::summarize_recording` (≈10 LOC) +
the same in the stream variant. The verbatim guarantee (R-EL3) holds
because `aliases[raw]` is passed through `apply_aliases` — the value
SQLite stored is the value the prompt sees. No `.strip()`, no `.lower()`,
no normalization.

**Snapshot test:** `tests/test_summary_prompt_alias_snapshot.py`
captures the constructed messages array and matches a golden file.

### Story 5.3 — Alias propagation: AI chat

Modify `chat_with_llm` to apply the same substitution + preface to
`transcription_context`. Identical pattern to Story 5.2.

**Snapshot test:** `tests/test_chat_context_alias_snapshot.py`.

### Story 5.4 — Per-turn confidence API

**Route addition (`api/routes/notebook.py`):**

```python
class TurnConfidence(BaseModel):
    turn_index: int
    speaker_id: str | None
    confidence: float

class DiarizationConfidenceResponse(BaseModel):
    recording_id: int
    turns: list[TurnConfidence]


@router.get(
    "/recordings/{recording_id}/diarization-confidence",
    response_model=DiarizationConfidenceResponse,
)
async def get_diarization_confidence(recording_id: int) -> DiarizationConfidenceResponse:
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    segments = get_segments(recording_id)
    words = get_words(recording_id)
    from server.core.diarization_confidence import per_turn_confidence
    return DiarizationConfidenceResponse(
        recording_id=recording_id,
        turns=[TurnConfidence(**t) for t in per_turn_confidence(segments, words)],
    )
```

**Tests:** `tests/test_diarization_confidence_endpoint.py` covers
3-turn fixture with 2 having confidence and 1 without (returned list
has 2 entries), the "all-NULL words" fallback (returns `turns: []`),
and 404 on unknown recording.

### Story 5.5 — Confidence chip UI

**Component (`dashboard/components/recording/ConfidenceChip.tsx`, new):**

```tsx
import { bucketFor, type Bucket } from '../../src/utils/confidenceBuckets';

interface Props { confidence: number; }

export function ConfidenceChip({ confidence }: Props) {
  const bucket = bucketFor(confidence);
  if (bucket === 'high') return null;     // no chip — UX-DR3
  const label = bucket === 'medium' ? 'medium' : 'low';
  const colorClass =
    bucket === 'low'
      ? 'bg-amber-500/20 text-amber-200'
      : 'bg-slate-500/20 text-slate-300';
  const pct = Math.round(confidence * 100);
  return (
    <span
      role="status"
      aria-label={`confidence: ${label}`}
      title={`confidence: ${pct}%`}        // tooltip
      className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs ${colorClass}`}
    >
      {label}
    </span>
  );
}
```

**Bucket utility (`dashboard/src/utils/confidenceBuckets.ts`, new):**

```typescript
// Mirrors server/backend/core/diarization_confidence.py constants.
export const HIGH_CONFIDENCE_THRESHOLD = 0.8;
export const LOW_CONFIDENCE_THRESHOLD = 0.6;
export type Bucket = 'high' | 'medium' | 'low';

export function bucketFor(confidence: number): Bucket {
  if (confidence >= HIGH_CONFIDENCE_THRESHOLD) return 'high';
  if (confidence >= LOW_CONFIDENCE_THRESHOLD) return 'medium';
  return 'low';
}
```

A sync test asserts both files agree on the constants.

`AudioNoteModal.tsx` renders `<ConfidenceChip confidence={...} />`
beside `seg.speaker`, looking up the per-turn confidence from a new
`useDiarizationConfidence` hook (similar to `useRecordingAliases`).

**UI contract:** new component → `npm run ui:contract:extract → build →
validate --update-baseline → check`. Captured in commit F.

### Story 5.6 — ADR-009 lifecycle state machine

Wire `on_transcription_complete()` into the **notebook upload completion
path** (override §1: longform/import paths deferred to Sprint 4).
Concretely, after `save_longform_to_database` returns inside
`upload_and_transcribe` (notebook.py upload route), check for
low-confidence turns and call the trigger:

```python
# notebook.py::upload_and_transcribe — additions after save_longform_to_database
from server.core.diarization_confidence import per_turn_confidence, LOW_CONFIDENCE_THRESHOLD
from server.core.diarization_review_lifecycle import on_transcription_complete

segments = get_segments(recording_id)
words = get_words(recording_id)
turns_with_conf = per_turn_confidence(segments, words)
has_low = any(t["confidence"] < LOW_CONFIDENCE_THRESHOLD for t in turns_with_conf)
on_transcription_complete(recording_id, has_low_confidence_turn=has_low)
```

**Tests (`tests/test_diarization_review_lifecycle.py`):**
- Each transition (None→pending, pending→in_review, in_review→completed,
  completed→released) — happy path.
- Illegal transitions raise `IllegalReviewTransitionError`.
- `on_transcription_complete(_, has_low=False)` is a no-op.
- `auto_summary_is_held` predicate: True for pending/in_review/completed,
  False for released, False for missing row.
- Banner predicate: True for pending/in_review, False for completed/released.
- AC5 persistence-across-restart: write `in_review`, close conn,
  reopen, read — still `in_review`.

### Story 5.7 — Persistent banner

**Component (`dashboard/components/ui/PersistentInfoBanner.tsx`, new):**

```tsx
interface Props {
  message: string;
  ctaLabel?: string;
  onCta?: () => void;
  severity: 'info' | 'warning';
  ariaAnnouncement?: string;
}

export function PersistentInfoBanner({
  message, ctaLabel, onCta, severity, ariaAnnouncement,
}: Props) {
  const announce = useAriaAnnouncer();
  useEffect(() => {
    if (ariaAnnouncement) announce(ariaAnnouncement);
  }, [ariaAnnouncement, announce]);

  return (
    <div
      role="status"
      className={`w-full ${severity === 'warning'
        ? 'bg-amber-500/15 border-amber-500/40 text-amber-100'
        : 'bg-blue-500/15 border-blue-500/40 text-blue-100'
      } border-b px-4 py-3 flex items-center justify-between`}
    >
      <span>{message}</span>
      {ctaLabel && onCta && (
        <button onClick={onCta} className="ml-4 underline hover:no-underline">
          {ctaLabel}
        </button>
      )}
    </div>
  );
}
```

**Wiring (in `AudioNoteModal.tsx` near top):**

```tsx
const { data: reviewState } = useDiarizationReviewState(recordingId);
const lowConfCount = useDiarizationLowConfCount(recordingId);

if (reviewState?.status === 'pending' || reviewState?.status === 'in_review') {
  banner = (
    <PersistentInfoBanner
      severity="warning"
      message={`⚠ Speaker labels uncertain on ${lowConfCount} turn boundaries — review before auto-summary runs.`}
      ctaLabel="Review uncertain turns"
      onCta={openReviewView}
      ariaAnnouncement={`Transcription complete. ${lowConfCount} turn boundaries flagged low-confidence.`}
    />
  );
}
```

**Hooks:** `useDiarizationReviewState(id)` queries
`GET /api/notebook/recordings/{id}/diarization-review` (new endpoint —
returns the row as JSON or `{status: null}`); `useDiarizationLowConfCount`
counts turns from `useDiarizationConfidence(id)`.

`openReviewView` opens the modal AND fires
`on_review_view_opened()` server-side (POST a small "open" endpoint,
or piggyback on the GET — chose: POST `/diarization-review` with
`action: 'open'` because GET shouldn't mutate state).

### Story 5.8 — Auto-summary HOLD hook

The HOLD predicate is already exposed by §2.3
(`auto_summary_is_held`). This story:
1. Adds a unit test consuming the predicate from a **fake auto-summary
   consumer** to prove the contract is callable from the lifecycle
   that lands in Sprint 4.
2. Documents the import path in `_bmad-output/implementation-artifacts/deferred-work.md`
   for Sprint 4 Story 6.2 reference.

```python
# tests/test_auto_summary_hold_hook.py
from server.core.diarization_review_lifecycle import (
    auto_summary_is_held,
    on_transcription_complete,
    on_run_summary_now_clicked,
    on_auto_summary_fired,
)

def fake_auto_summary_consumer(recording_id: int) -> str:
    """Pretends to be Sprint 4 Story 6.2 auto-summary lifecycle."""
    if auto_summary_is_held(recording_id):
        return "HELD"
    return "FIRED"

def test_held_when_pending(test_recording):
    on_transcription_complete(test_recording.id, has_low_confidence_turn=True)
    assert fake_auto_summary_consumer(test_recording.id) == "HELD"

def test_fires_after_release(test_recording):
    on_transcription_complete(test_recording.id, has_low_confidence_turn=True)
    on_review_view_opened(test_recording.id)
    on_run_summary_now_clicked(test_recording.id)
    on_auto_summary_fired(test_recording.id)
    assert fake_auto_summary_consumer(test_recording.id) == "FIRED"

def test_not_held_when_no_low_confidence(test_recording):
    on_transcription_complete(test_recording.id, has_low_confidence_turn=False)
    # No row was inserted; predicate returns False.
    assert fake_auto_summary_consumer(test_recording.id) == "FIRED"
```

**Manual summary always allowed (AC3):** the predicate is consulted
ONLY by auto-summary lifecycle. The manual `summarize_recording` route
does NOT consult it. (Test: `tests/test_manual_summary_bypasses_hold.py`
sets up a held recording, calls the manual summary route, asserts a
200 response with summary text — no 409, no skip.)

### Story 5.9 — Diarization-review focused view

**View (`dashboard/components/recording/DiarizationReviewView.tsx`, new):**

A modal/page with:
- **Confidence-threshold filter** dropdown:
  *"bottom-5%" / "<60%" / "<80%" / "all uncertain"*
- **Turn-list** — composite-widget `role="listbox"` (single tab stop)
  rendering filtered low-confidence turns. Each turn:
  - Speaker label + speaker-cycle ←/→ buttons
  - Excerpt of the turn text
  - Confidence chip (Story 5.5)
  - "Accept" / "Skip" inline buttons (mirror Enter/Esc)
- **Bulk-action button:** "Mark all visible as auto-accept best guess"
  (mirror Space)
- **"Run summary now"** primary button at the bottom

**State management:** local React state for `activeIndex`,
`activeAttributionIndex`, `acceptedTurns: Set<number>`,
`skippedTurns: Set<number>`. On commit (Run summary now), POST
to:

```python
# notebook.py — new endpoint
class DiarizationReviewSubmit(BaseModel):
    reviewed_turns: list[dict]  # [{"turn_index": int, "decision": "accept"|"skip", "speaker_id": str}]
    action: str  # "open" | "complete"


@router.post("/recordings/{recording_id}/diarization-review")
async def submit_diarization_review(
    recording_id: int, payload: DiarizationReviewSubmit,
) -> dict:
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    if payload.action == "open":
        on_review_view_opened(recording_id)
    elif payload.action == "complete":
        # Persist reviewed_turns_json BEFORE the state transition
        repo.update_reviewed_turns(
            recording_id,
            json.dumps(payload.reviewed_turns, ensure_ascii=False, sort_keys=True),
        )
        on_run_summary_now_clicked(recording_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    row = repo.get_review(recording_id)
    return row or {"status": None}
```

**Filter linearity benchmark (`tests/test_review_filter_linearity.py`):**

```python
import time
import numpy as np
import pytest
from server.core.diarization_review_filter import filter_low_confidence

@pytest.mark.parametrize("n", [10, 100, 500, 1000])
def test_filter_p95_is_linear(n, sample_turn_factory):
    turns = sample_turn_factory(n)
    samples_ns: list[int] = []
    for _ in range(50):
        t0 = time.perf_counter_ns()
        _ = filter_low_confidence(turns, threshold=0.6)
        samples_ns.append(time.perf_counter_ns() - t0)
    p95 = float(np.percentile(samples_ns, 95))
    if n == 100:
        assert p95 < 200_000_000, f"p95 at N=100 = {p95}ns > 200ms budget"
```

A second test fits a linear regression across (N, mean) pairs and
asserts `r²>0.95`.

**A11y test:**
`dashboard/components/recording/__tests__/DiarizationReviewView.keyboard.test.tsx`
covers each row of the keyboard contract using `@testing-library/user-event`.
This is the canonical regression test for FR54 + the keyboard contract.

---

## 4. Risks and Stop-Conditions

| Risk | Mitigation | Stop-condition |
|---|---|---|
| Alias substitution slows view render past 10ms | `apply_aliases` is O(N) over a small `aliases` map; React Query caches the alias list. Build label map once per render | If a 60-min recording (1k segments) takes >10ms render, profile and add memo |
| Confidence-mean proxy disagrees with pyannote intent | Buckets are coarse (3 levels); even if exact pct differs, bucket stability is what UX-DR3 requires | If bucket assignment flips heavily relative to pyannote's emitted score, add `segments.confidence` column in Sprint 4 |
| ADR-009 lifecycle test infrastructure is heavy | All triggers are pure DB ops; tests use in-memory DB | If migration 014 + 010 conflict on test DB setup, STOP and verify migration order |
| Keyboard contract feels brittle on screen-reader testing | WAI-ARIA `listbox` is the canonical pattern; aria-activedescendant is well-supported | If JAWS / NVDA misread `aria-activedescendant`, switch to `tabindex` roving (deferred polish) |
| Sprint diff exceeds ~4500 LOC | LOC budget per commit (see §6) totals ~3200 + ~1000 tests = ~4200 LOC | If commits A-F together exceed 2500 LOC, STOP and ask whether to split E5 across sprints |
| Alias verbatim guarantee (R-EL3) regression | Helper function unit tests assert byte-equivalence of alias_name in/out | If anywhere normalizes (`.strip()`, `.lower()`, NFC) the alias_name BEFORE storage or BEFORE prompt, fix at that exact site |

---

## 5. Recording-deletion + cascade matrix (R-EL13 update)

| User action | DB row (recordings) | DB rows (segments / words / aliases / review) |
|---|---|---|
| Click Delete (default) | DELETED | segments + words = ON DELETE CASCADE existing; aliases = ON DELETE CASCADE (Story 4.1); review = ON DELETE CASCADE (Sprint 1 migration 010) |

All four child-table FK cascades are now in place. The "no leak on
restore" property (Story 4.5 AC2) holds for all four because each
cascade is encoded at the schema level.

---

## 6. Out-of-sprint observations (record only)

- **Longform / import diarization completion path** for Story 5.6
  trigger is deferred to Sprint 4 alongside Story 6.2 auto-summary
  wiring. The trigger function (`on_transcription_complete`) is
  shared; only the call sites differ. Captured in `deferred-work.md`.
- **Per-segment confidence column** if perf becomes a hotspot. Sprint 3's
  per-call O(words) aggregation is acceptable.
- **Bulk-accept undo** (per v2 readiness Minor 3 — partially resolved)
  is not implemented in this sprint; bulk-accept commits immediately.
- **Identity-level aliases** (cross-recording — R-EL8) explicitly
  Vision-tier, NOT this sprint.

---

## 7. Commit plan recap (with LOC estimates)

| Commit | Stories | Files | Est. LOC | Notes |
|---|---|---|---|---|
| A | 4.1 + 4.2 | migration 014, alias_repository, notebook.py route additions, 2 test files | ~450 | Foundation |
| B | 4.3 + 4.4 | useRecordingAliases hook, SpeakerRenameInput component, AudioNoteModal wiring, aliasSubstitution.ts util, view-snapshot test, sync test | ~500 | UI-heavy |
| C | 4.5 | cascade test + restore-survival test | ~120 | Tests-only |
| D | 5.1 + 5.2 + 5.3 | alias_substitution.py module, plaintext route + subtitle build_subtitle_cues param, llm.py summarize + chat changes, 4 snapshot tests | ~600 | Cross-cutting backend |
| E | 5.4 | diarization_confidence.py, notebook.py confidence endpoint, 1 test file | ~250 | Tiny |
| F | 5.5 | confidenceBuckets.ts, ConfidenceChip.tsx, useDiarizationConfidence hook, AudioNoteModal wiring, ui-contract baseline update | ~350 | UI-heavy |
| G | 5.6 | diarization_review_lifecycle.py, notebook.py upload-completion hook, 1 test file | ~350 | Pure logic |
| H | 5.7 + 5.8 | PersistentInfoBanner.tsx, useDiarizationReviewState hook, AudioNoteModal wiring, auto_summary_is_held hook test (+manual bypass test), endpoint POST /diarization-review (open), ui-contract update | ~500 | UI + small backend |
| I | 5.9 | DiarizationReviewView.tsx (composite widget), filter util, submit endpoint (complete action), keyboard contract test, filter linearity test, ui-contract update | ~900 | Largest commit |
| Final | mark 14 stories DONE in epics.md | epics.md | ~30 | Bookkeeping |

**Total ~4050 LOC + tests** — within the ~4500 LOC envelope sprint
prompt allows for this larger sprint.

---

## 8. Dependency order recap

```
   Commit A (4.1 + 4.2 — table + REST) ─► Commit B (4.3 + 4.4 — UI consumes API)
                                       └► Commit D (5.1+5.2+5.3 — propagation reads aliases)
   Commit C (4.5 — FK cascade test) — independent, runs after A
   Commit E (5.4 — confidence API) — independent of aliases
   Commit F (5.5 — confidence chip UI) — depends on E + B (chip lives next to speaker label)
   Commit G (5.6 — lifecycle) — depends on E (low-confidence detection)
   Commit H (5.7 + 5.8 — banner + HOLD hook) — depends on G
   Commit I (5.9 — review view) — depends on H (banner CTA opens this view)
```

Linear order A → B → C → D → E → F → G → H → I satisfies all
import-time and consumer-pattern dependencies. Each commit lands as
its own logical unit; the sprint ships as one branch.
