---
sprint: 1
date: 2026-05-03
project: TranscriptionSuite
issue: 104
epic_set: [epic-foundations (E1) Stories 1.2–1.9; epic-model-profiles (E8) Stories 8.1–8.4]
prereq: Story 1.1 DONE (commits cca1a83, 076022e)
budget_dev_days: 11–14 (E1 remaining 1.2–1.9 = 10–13d) + 3–4 (E8) ≈ 13–17 dev-days
target_loc_ceiling: ≤3500 LOC (per sprint prompt; escalate if exceeded)
ac_overrides_required: yes (path layout, missing-test references, electron-store fact)
---

# Sprint 1 — Platform Foundations Design

This document captures the design choices that bind the 12 stories together
**before** implementation, so commits A–G can be ~mechanical translation. It
also records every place where the literal AC text in `epics.md` had to be
adjusted to match the actual repo state — same pattern Story 1.1 followed.

---

## 0. Inline AC overrides (read first)

The same conditions Story 1.1 surfaced are present here. Each override below
is documented so the implementation isn't a violation; the overrides are
faithful to the AC's *intent*, not its surface text.

| AC literal text | Reality | Override |
|---|---|---|
| `server/backend/server/database/diarization_review_repository.py` | Backend layout is flat (`server/backend/database/`); the inner `server` only exists as the package alias set up in `tests/conftest.py::_ensure_server_package_alias()`. | Files live at `server/backend/database/diarization_review_repository.py`; **import path** stays `server.database.diarization_review_repository` (per the alias). |
| `server/backend/server/utils/keychain.py` (Story 1.7 AC2) | `server/backend/utils/` does not exist yet; `core/token_store.py` is the closest neighbor for credential code. | Create `server/backend/utils/__init__.py` + `utils/keychain.py`. Import path: `server.utils.keychain`. |
| `server/utils/config_migration.py` (Story 1.7 AC4) and "existing test `test_config_migration_generates_secret_on_v13x_config`" | Neither the module nor the test exists in the current tree (verified via `find` and `git log`). | Create the module **AND** the test as part of Story 1.7. The AC's "existing test passes" framing is an artifact of the planning narrative; in reality this is the first time the bootstrap is implemented for the QoL pack. Test file: `tests/test_config_migration_master_key.py`. |
| Migrations are "forward-only with no downgrade script" (multiple ACs cite NFR22) | Existing migrations 001–007 all define `downgrade()`; Alembic file-parse expects it. | New migrations 008–011 will define `downgrade()` that **raises `RuntimeError("forward-only — see NFR22")`** rather than reverse the schema. This honours NFR22 (no usable downgrade) without breaking Alembic's file-format expectations. |
| Story 1.2 AC3 says "Given `api/routes/notebook.py` ... `GET /api/profiles`..." | `api/routes/notebook.py` is mounted with prefix `/api/notebook`, so endpoints inside it would be served at `/api/notebook/profiles`, not `/api/profiles`. The URL contract is load-bearing (FR10). | Create new file **`api/routes/profiles.py`** mounted with `prefix="/api/profiles"` in `api/main.py`. The "Given notebook.py" framing was the planner's location guess; the URL contract wins. |
| Story 1.6 AC says "persists to electron-store under key `notebook.activeProfileId`" | `electron-store` is already installed (`dashboard/package.json` lists `^11.0.2`) and the renderer already has a generic `electronAPI.get/set(key, value)` bridge in `dashboard/electron/preload.ts`. | Use the **existing** bridge — no new IPC. Just write `electronAPI.set('notebook.activeProfileId', id)` from a Zustand subscription. |
| Story 8.1 AC1 says implementer chooses electron-store *or* SQLite for model profiles | Same as above — the bridge already exists, model selection already lives in electron-store under `model.*` keys. | Choose **electron-store**. Key namespace: `notebook.modelProfiles[]` and `notebook.activeModelProfileId`. No SQLite migration for E8. |
| Story 1.8 AC4 mentions `dashboard/lighthouserc.json` and adding a Lighthouse CI gate | Dashboard is an Electron desktop app, not a web app. Lighthouse CI is most useful against served pages; running it on Vite preview is possible but adds substantial CI weight (NFR25 explicitly accepts ~90s + 40MB). | Implement minimum viable: a `lighthouserc.json` that targets the Vite preview build of a representative profile-edit page; the workflow runs only on `dashboard/components/**` PR changes. **If the wiring proves brittle inside this sprint, downgrade to a manual `npm run lint:a11y` (eslint-plugin-jsx-a11y) gate and capture the full Lighthouse setup as deferred work** so the sprint isn't blocked on CI plumbing. |
| Story 1.9 AC2 names `test_diarization_review_state_survives_restore` performing "DB dump and restore cycle" | SQLite dump/restore at the test level means `iterdump()` → fresh in-memory connection → re-import. There's no production "restore" tooling tested by the existing suite. | Implement the test using `sqlite3.iterdump()` to a `StringIO`, then load into a fresh `:memory:` connection and assert the row survives. This is what NFR23 actually requires (round-trippable schema). |

---

## 1. Architectural through-lines

Three patterns recur across all 12 stories. Codifying them once here keeps
each commit mechanical.

### 1.1 Migration template

Every new migration in this sprint:

```python
"""<description>"""
from collections.abc import Sequence
from alembic import op
from sqlalchemy import text

revision: str = "00X"
down_revision: str | None = "00X-1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _revision_metadata():
    return revision, down_revision, branch_labels, depends_on


def upgrade() -> None:
    _revision_metadata()
    conn = op.get_bind()
    conn.execute(text("CREATE TABLE IF NOT EXISTS ..."))
    # idempotent on re-run; uses CREATE INDEX IF NOT EXISTS for indexes


def downgrade() -> None:
    raise RuntimeError(
        "forward-only migration — see NFR22; restore from backup if needed"
    )
```

Migration numbering after Story 1.1 lands at 007:

| # | Story | File |
|---|---|---|
| 008 | 1.2 | `008_add_profiles_table.py` |
| 009 | 1.3 | `009_add_profile_snapshot_to_transcription_jobs.py` |
| 010 | 1.9 | `010_add_recording_diarization_review.py` |

**Note:** Story 1.1 did NOT add a migration. Numbering continues from 007.

### 1.2 Repository module template

`database/<thing>_repository.py` for parameterised SQL CRUD:

```python
import json
import sqlite3
from datetime import datetime, UTC
from server.database.database import get_connection


def create_profile(name: str, schema_version: str, public_fields: dict,
                   private_field_refs: dict | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO profiles
               (name, description, schema_version,
                public_fields_json, private_field_refs_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, public_fields.get("description"), schema_version,
             json.dumps(public_fields, sort_keys=True),
             json.dumps(private_field_refs or {}, sort_keys=True),
             datetime.now(UTC).isoformat(),
             datetime.now(UTC).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
```

Constraints:
- Every write commits before returning. (Enforces NFR16 Persist-Before-Deliver
  at the repository layer; the route layer never has to remember.)
- `json.dumps(..., sort_keys=True)` so snapshot equality is deterministic.
- `datetime.now(UTC).isoformat()` so timestamps are TZ-aware. (In tests,
  `frozen_clock` controls this — but only when the test explicitly requests
  the fixture, which is the conftest convention.)

### 1.3 Route module pattern (additions to notebook.py)

Profile CRUD routes go into the existing `api/routes/notebook.py` (already
mounted by `api/main.py`). Pattern:

```python
@router.get("/api/profiles", response_model=list[ProfileResponse])
async def list_profiles():
    return profile_repository.list_profiles()  # public fields only


@router.post("/api/profiles", status_code=201,
             response_model=ProfileResponse)
async def create_profile(body: ProfileCreate):
    pid = profile_repository.create_profile(...)  # commit happens here
    # Persist-Before-Deliver: response only AFTER commit returns
    return profile_repository.get_profile(pid)


@router.put("/api/profiles/{pid}", response_model=ProfileResponse)
async def update_profile(pid: int, body: ProfileUpdate):
    if body.schema_version not in {"1.0"}:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_schema_version",
                "supported": ["1.0"],
                "received": body.schema_version,
            },
        )
    profile_repository.update_profile(pid, body)
    return profile_repository.get_profile(pid)
```

`GET` responses **must never include `private_field_refs`** — Pydantic
`response_model=ProfileResponse` (which omits the field) enforces this at
the type boundary, not via remember-to-strip logic.

### 1.4 Persist-Before-Deliver invariant

Two ACs make it explicit (1.2 AC6, 1.3 AC6, snapshot-at-job-start in 1.3).
Existing wave-1 durability work in `server/backend/database/job_repository.py`
already follows the pattern. New code in this sprint reuses that pattern:

1. Repository write → `conn.commit()` returns
2. Only then does the route return / the worker call `engine.transcribe()`

Test enforcement (Story 1.3 AC6):

```python
def test_snapshot_persisted_before_engine_call(frozen_clock, monkeypatch):
    """Assert SQLite write happens before engine.transcribe()."""
    call_order: list[str] = []

    def fake_commit(self):
        call_order.append("commit")
    def fake_transcribe(*args, **kwargs):
        call_order.append("transcribe")
        return [], None  # match real signature

    monkeypatch.setattr(sqlite3.Connection, "commit", fake_commit)
    monkeypatch.setattr(engine, "transcribe", fake_transcribe)
    # ... start job ...
    assert call_order == ["commit", "transcribe"]
```

### 1.5 Cross-cutting accessibility scaffold (Story 1.8) consumed by 1.4, 1.5, 8.2

Story 1.8 ships before Story 1.4 needs it (consumes via reference, not
import-time dependency), but in commit ordering 1.4 lands first. So Story 1.8's
helpers are **referenced by name** in commit B (folder picker) and commit C
(empty-profile screen) and commit G (model profile UI), then defined in commit E.

That's safe because each consumer just imports `useAriaAnnouncer` and
`downloadButtonLabel` — those imports won't resolve until commit E lands.
This *would* be a forward-import hazard if commits were partial deliverables,
but the sprint is shipped as one branch — `git diff main..HEAD` resolves
all references before review.

---

## 2. Per-story design

### Story 1.2 — `profiles` table + REST CRUD

**Schema** (migration 008):

```sql
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    schema_version TEXT NOT NULL,
    public_fields_json TEXT NOT NULL,
    private_field_refs_json TEXT,            -- keychain reference IDs only (FR11/R-EL22)
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name);
```

**`public_fields_json` shape (schema_version "1.0"):**

```json
{
  "filename_template": "{date} {title}.txt",
  "destination_folder": "/home/user/Documents",
  "auto_summary_enabled": false,
  "auto_export_enabled": false,
  "summary_model_id": null,
  "summary_prompt_template": null,
  "export_format": "plaintext"
}
```

This shape matches `tests/fixtures/profile_snapshots/full-v1.0.json` (already
on disk from Story 1.1). The golden snapshot is the source of truth.

**`private_field_refs_json` shape:**

```json
{
  "webhook_token": "profile.123.webhook_token",
  "summary_api_key": "profile.123.summary_api_key"
}
```

Values are keychain-reference *IDs* (`<service>.<id>.<field>`), never plaintext.
Story 1.7 implements the keychain that resolves these IDs.

**Route layer additions (`api/routes/notebook.py`):**

- `GET /api/profiles` → list (public fields only)
- `POST /api/profiles` → create (accepts public + private; persists private via keychain)
- `GET /api/profiles/{id}` → read (public only)
- `PUT /api/profiles/{id}` → update (with schema_version validation)
- `DELETE /api/profiles/{id}` → delete

**Pydantic models** added near the top of `notebook.py`:

```python
class ProfilePublicFields(BaseModel):
    filename_template: str
    destination_folder: str
    auto_summary_enabled: bool = False
    auto_export_enabled: bool = False
    summary_model_id: str | None = None
    summary_prompt_template: str | None = None
    export_format: str = "plaintext"

class ProfileCreate(BaseModel):
    name: str
    description: str | None = None
    schema_version: str = "1.0"
    public_fields: ProfilePublicFields
    private_fields: dict[str, str] | None = None  # write-only

class ProfileResponse(BaseModel):
    id: int
    name: str
    description: str | None
    schema_version: str
    public_fields: ProfilePublicFields
    created_at: str
    updated_at: str
    # NOTE: private_field_refs intentionally absent (FR11)
```

**Repository:** `server/backend/database/profile_repository.py` (new).

**Tests:** `tests/test_profile_repository.py`,
`tests/test_profile_routes.py`, `tests/test_profile_migration_non_destructive.py`.

### Story 1.3 — Profile snapshot column + crash rehydration

**Schema** (migration 009):

```sql
ALTER TABLE transcription_jobs ADD COLUMN job_profile_snapshot TEXT;
ALTER TABLE transcription_jobs ADD COLUMN snapshot_schema_version TEXT;
```

Existing rows get NULL — the worker code path checks `IS NOT NULL` before
attempting rehydration, so legacy jobs continue to work unchanged.

**Snapshot serialization:**

```python
import json
from server.database.profile_repository import get_profile

def snapshot_profile_at_job_start(profile_id: int) -> tuple[str, str]:
    """Returns (snapshot_json, schema_version). Caller persists to job row."""
    profile = get_profile(profile_id)  # reads live state
    snapshot = {
        "id": profile["id"],
        "name": profile["name"],
        "schema_version": profile["schema_version"],
        "public_fields": profile["public_fields"],
        # private_field_refs intentionally NOT snapshotted —
        # those are pointers to keychain entries that must be re-resolved
        # at job-start time. The keychain ENTRIES are immutable across the
        # job's lifetime by convention; ADR-005 reasoning holds for ADR-003.
    }
    return json.dumps(snapshot, sort_keys=True), profile["schema_version"]
```

**Where this hooks in:** `transcription_jobs` row creation already happens in
`server/backend/database/job_repository.py::create_transcription_job()`
(or equivalent). Add a `profile_id` parameter; if non-null, take a snapshot
inline before the INSERT and pass both columns. This keeps the
Persist-Before-Deliver chain intact (snapshot is part of the same INSERT).

**Crash rehydration (AC4, AC5):** existing `periodic_orphan_sweep` in the
durability layer already rehydrates job rows on startup. Extend the rehydration
to also re-emit the snapshot to the worker via the existing channel.

**Test:** `tests/test_profile_snapshot_durability.py`. Uses `frozen_clock` to
prove ordering (commit before transcribe).

### Story 1.4 — Native folder picker

**Electron main (`dashboard/electron/main.ts`):**

```typescript
ipcMain.handle('dialog:chooseFolder', async (_event, title?: string) => {
  const result = await dialog.showOpenDialog({
    title: title ?? 'Choose folder',
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});
```

**Preload bridge (`dashboard/electron/preload.ts`):** add
`chooseFolder: (title?: string) => ipcRenderer.invoke('dialog:chooseFolder', title)`
to the `electronAPI` block.

**React hook (`dashboard/src/hooks/useFolderPicker.ts`):**

```typescript
export function useFolderPicker() {
  return useCallback(async (title?: string) => {
    if (!window.electronAPI?.chooseFolder) {
      // Web/Vitest fallback — return null so callers can branch
      return null;
    }
    return window.electronAPI.chooseFolder(title);
  }, []);
}
```

**Cross-platform notes (documented in `docs/dashboard/folder-picker.md`):**

- **Linux KDE Wayland (primary):** native KDE dialog renders correctly via
  Electron's `dialog.showOpenDialog`.
- **Windows 11:** uses native Common Item Dialog (IFileOpenDialog).
- **macOS:** uses NSOpenPanel; folder selection requires
  `properties: ['openDirectory']` — verified.

**Tests:** unit-test the hook with a mocked `window.electronAPI`. The actual
Electron dialog is exercised in manual cross-platform smoke testing (AC2 is
manual by design — we don't have GUI E2E set up).

### Story 1.5 — Empty-profile screen

**Component:** `dashboard/components/profile/EmptyProfileForm.tsx` (new).

- Pre-populates fields per AC1 (template, destination from
  `os.homedir() + '/Documents'`, toggles OFF)
- Renders banner via existing `QueuePausedBanner` primitive (UX-DR2)
- Banner dismissal: `electronAPI.set('notebook.dismissedBanners.emptyProfile', true)`
- No "Next" / "Back" — only Save + Cancel
- Tab order enforced via DOM order (no `tabIndex` overrides except `0`)

**OS-default destination:** the renderer can't directly call `os.homedir()`,
but `app.getPath('documents')` from Electron main is available. Add an IPC
handler `app:getDocumentsPath` and expose it through the preload as
`electronAPI.getDocumentsPath()`. Default value is computed lazily on first
render of the empty form.

**Tests:** `dashboard/components/__tests__/EmptyProfileForm.test.tsx` covers
default population, banner dismissal persistence (mocked store), tab order.

### Story 1.6 — Active profile switch (Zustand + electron-store)

**Store (`dashboard/src/stores/activeProfileStore.ts`):**

```typescript
import { create } from 'zustand';

interface ActiveProfileState {
  activeProfileId: string | null;
  setActiveProfileId: (id: string | null) => void;
  hydrateFromStore: () => Promise<void>;
}

export const useActiveProfileStore = create<ActiveProfileState>((set) => ({
  activeProfileId: null,
  setActiveProfileId: (id) => {
    set({ activeProfileId: id });
    void window.electronAPI?.set('notebook.activeProfileId', id);
  },
  hydrateFromStore: async () => {
    const id = await window.electronAPI?.get('notebook.activeProfileId');
    if (typeof id === 'string') set({ activeProfileId: id });
  },
}));
```

`hydrateFromStore()` is invoked once at app boot in `App.tsx`'s init hook.

**Toolbar dropdown:** add to `Sidebar.tsx` (closest existing chrome) — a
profile selector with `<select>` semantics (real `<select>` — easiest a11y
win). On change, calls `setActiveProfileId(newId)`.

### Story 1.7 — OS keychain wrapper + headless fallback

**Module (`server/backend/utils/keychain.py`):**

```python
"""OS keychain wrapper with explicit headless fallback.

Backends (priority order):
  1. OS-native (macOS Keychain / Windows DPAPI / Linux libsecret) via `keyring`
  2. EncryptedFile (`keyrings.alt.file.EncryptedKeyring`) iff
     KEYRING_BACKEND_FALLBACK=encrypted_file is set AND no OS backend available

Tests must use the `fake_keyring` fixture (from conftest.py); never touch
the real OS keychain in tests. See FR49/FR50/NFR8/NFR33/NFR34.
"""
from __future__ import annotations
import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError, NoKeyringError

_SERVICE_PREFIX = "transcriptionsuite"


class KeychainUnavailableError(RuntimeError):
    """Raised when no usable keyring backend is available and the
    KEYRING_BACKEND_FALLBACK env-flag is not set."""


def _maybe_install_encrypted_file_backend() -> None:
    """Best-effort: switch to keyrings.alt.EncryptedKeyring if requested."""
    if os.environ.get("KEYRING_BACKEND_FALLBACK") != "encrypted_file":
        return
    from keyrings.alt.file import EncryptedKeyring
    backend = EncryptedKeyring()
    backend.file_path = str(_secrets_dir() / "encrypted_keyring.cfg")
    backend.keyring_key = _read_master_key()
    keyring.set_keyring(backend)


def _secrets_dir() -> Path:
    """secrets/ at the project root (NOT in the package)."""
    # Resolve relative to this file's location: backend/utils/keychain.py
    return (Path(__file__).resolve().parents[2] / "secrets")


def _read_master_key() -> str:
    p = _secrets_dir() / "master.key"
    return p.read_text(encoding="utf-8").strip()


def set(key: str, value: str) -> None:
    """key: '<entity>.<id>.<field>', e.g. 'profile.123.webhook_token'."""
    try:
        keyring.set_password(_SERVICE_PREFIX, key, value)
    except (NoKeyringError, KeyringError) as e:
        _maybe_install_encrypted_file_backend()
        try:
            keyring.set_password(_SERVICE_PREFIX, key, value)
        except (NoKeyringError, KeyringError) as e2:
            raise KeychainUnavailableError(
                "No usable keyring backend. "
                "Set KEYRING_BACKEND_FALLBACK=encrypted_file to use file fallback "
                "— security delta: see docs/deployment-guide.md."
            ) from e2


def get(key: str) -> str | None:
    try:
        return keyring.get_password(_SERVICE_PREFIX, key)
    except (NoKeyringError, KeyringError):
        return None


def delete(key: str) -> None:
    try:
        keyring.delete_password(_SERVICE_PREFIX, key)
    except (NoKeyringError, KeyringError):
        pass  # best-effort delete
```

**Bootstrap (`server/backend/utils/config_migration.py`, new):**

```python
"""Auto-generate secrets/master.key on first run.

Idempotent: if the file already exists, leave it alone.
Mode 0600. 32 random bytes hex-encoded.
"""
from __future__ import annotations
import secrets
from pathlib import Path

def ensure_master_key(secrets_dir: Path) -> Path:
    """Returns path to master.key after ensuring it exists."""
    secrets_dir.mkdir(parents=True, exist_ok=True)
    target = secrets_dir / "master.key"
    if not target.exists():
        target.write_text(secrets.token_hex(32), encoding="utf-8")
        target.chmod(0o600)
    return target
```

Called once from `api/main.py` lifespan startup; the `secrets/` dir is
bind-mounted in `docker-compose.yml` (existing convention).

**Tests:**
- `tests/test_keychain.py` — uses `fake_keyring` fixture; smoke tests
  set/get/delete and the `KeychainUnavailableError` path
- `tests/test_config_migration_master_key.py` — covers idempotency, mode 0600,
  hex content (length 64)

**docs/deployment-guide.md addition:** new section "Keychain fallback
(encrypted-file mode)" — what it protects against, what it does NOT.

### Story 1.8 — Accessibility scaffold

**ARIA announcer hook (`dashboard/src/hooks/useAriaAnnouncer.ts`):**

```typescript
import { useCallback } from 'react';
import { useAriaAnnouncerStore } from '../stores/ariaAnnouncerStore';

type Politeness = 'polite' | 'assertive';

export function useAriaAnnouncer() {
  const announce = useAriaAnnouncerStore(s => s.announce);
  return useCallback(
    (message: string, opts?: { politeness?: Politeness }) =>
      announce(message, opts?.politeness ?? 'polite'),
    [announce],
  );
}
```

**Store (`dashboard/src/stores/ariaAnnouncerStore.ts`):** holds two strings
(politeMessage, assertiveMessage) and clears each after 5s via setTimeout
(setTimeout is fine in production code; only banned in `**/*.test.ts`).

**Root mount (`dashboard/components/AriaLiveRegion.tsx`):**

```tsx
import { useAriaAnnouncerStore } from '../src/stores/ariaAnnouncerStore';

export function AriaLiveRegion() {
  const polite = useAriaAnnouncerStore(s => s.politeMessage);
  const assertive = useAriaAnnouncerStore(s => s.assertiveMessage);
  return (
    <>
      <div role="status" aria-live="polite" className="sr-only">{polite}</div>
      <div role="status" aria-live="assertive" className="sr-only">{assertive}</div>
    </>
  );
}
```

Mounted once in `App.tsx` near the top of the tree.

**Label utilities (`dashboard/src/utils/a11yLabels.ts`):**

```typescript
export type DownloadKind = 'transcript' | 'summary';
export function downloadButtonLabel(kind: DownloadKind): string {
  return kind === 'summary'
    ? 'Download summary as plain text'
    : 'Download transcript as plain text';
}
```

**ESLint rule:** rather than write a custom rule (high cost for one diagnostic),
extend `dashboard/eslint.config.js` to use **`eslint-plugin-jsx-a11y`** with a
narrow ruleset that flags the same problem:

```js
'jsx-a11y/no-redundant-roles': 'error',
'jsx-a11y/control-has-associated-label': ['error', {
  labelAttributes: ['aria-label', 'aria-labelledby'],
}],
```

This catches `<button>Download</button>` lacking accessible text. If the
narrow rule misses cases the AC cares about, we add a custom rule then —
not as part of this sprint (deferred).

**Lighthouse CI gate:** see override in §0. Implement minimum viable
`lighthouserc.json` against Vite preview. If wiring is brittle, downgrade to
`eslint-plugin-jsx-a11y`-only and capture deferred work.

**Doc (`docs/dashboard/accessibility.md`, new):** tab-order convention,
label-naming convention, manual screen-reader smoke-test checklist (AC5).

### Story 1.9 — `recording_diarization_review` migration (ADR-009)

**Schema** (migration 010):

```sql
CREATE TABLE IF NOT EXISTS recording_diarization_review (
    recording_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'in_review', 'completed', 'released')),
    reviewed_turns_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);
```

**Repository (`database/diarization_review_repository.py`, new):**
parameterised SQL only — `create_review`, `get_review`, `update_status`,
`update_reviewed_turns`. The lifecycle state-machine consumer (Story 5.6)
ships in Sprint 3; this sprint provides the table + smoke CRUD.

**Restore-survival test:**

```python
def test_diarization_review_state_survives_restore(tmp_path):
    src = tmp_path / "src.db"
    # Create + populate
    with sqlite3.connect(src) as conn:
        # ... apply migration via alembic ...
        conn.execute(
            "INSERT INTO recording_diarization_review "
            "(recording_id, status) VALUES (?, ?)",
            (42, "in_review"),
        )
    # Round-trip via iterdump
    with sqlite3.connect(src) as conn:
        dump_lines = list(conn.iterdump())
    restored = sqlite3.connect(":memory:")
    for stmt in dump_lines:
        restored.execute(stmt)
    row = restored.execute(
        "SELECT status FROM recording_diarization_review WHERE recording_id=?",
        (42,),
    ).fetchone()
    assert row[0] == "in_review"
```

### Stories 8.1–8.4 — Model profiles

**Storage decision (AC8.1):** electron-store under `notebook.modelProfiles[]`
(see §0 override). No SQLite migration. Active profile under
`notebook.activeModelProfileId`.

**Shape:**

```typescript
interface ModelProfile {
  id: string;          // crypto.randomUUID() at create time
  name: string;
  sttModel: string;            // e.g. 'nvidia/parakeet-tdt-0.6b-v2'
  sttLanguage: string;         // e.g. 'en'
  translateTarget: string | null;  // for Canary; null otherwise
  createdAt: string;   // ISO
  updatedAt: string;   // ISO
}
```

**Service (`dashboard/src/services/modelProfileStore.ts`, new):** wraps
`electronAPI.get/set` with typed accessors. Same pattern as the proven
`importQueueStore.ts`.

**Settings UI:** new section in `SettingsModal.tsx` — list + add/edit form
with the field set described in AC8.2. Keyboard tab order documented
inline; `aria-label`s use `a11yLabels.ts` helpers (Story 1.8).

**Toolbar selector:** add to `Sidebar.tsx` next to (or replacing) the
existing model selection dropdown — a small selector that switches model
profile in one click, shows spinner during swap, reads
`isLiveModeActive()` to reject the switch with a toast (existing
`useLiveMode.ts` exposes the active flag).

**`model_manager` integration:** the existing `core/model_manager.py`
already exposes `load_transcription_model(model_id, language, ...)` — the
toolbar selector simply re-uses the existing model-swap UX (which already
shows "Switching model…"). Story 8.3 is a thin wrapper.

**Persistence (8.4):** the existing electron-store `set` from 8.3
already persists; AC just requires reading on first paint (one
`useEffect` in the toolbar component).

**Independence test (`dashboard/src/services/modelProfileStore.test.ts`):**
```ts
test('model profile delete does not affect notebook profile', () => {
  modelProfileStore.set([{ id: 'm1', ... }]);
  notebookProfileStore.set([{ id: 'p1', ... }]);  // separate store
  modelProfileStore.delete('m1');
  expect(notebookProfileStore.get('p1')).toBeDefined();
});
```

The "they don't share an `id` namespace" property is satisfied by virtue
of using separate electron-store keys (`notebook.modelProfiles[]` vs the
SQLite `profiles` table) — the test just demonstrates the property.

---

## 3. E1 ↔ E8 reuse cross-check

The sprint prompt asks whether E1 (user profiles, SQLite) and E8 (model
profiles, electron-store) share enough to extract a base class.

**Answer: no, they should NOT share a base class.** Reasoning:

- **Different persistence layers:** SQLite vs electron-store. Wrapping both
  behind a `ProfileRepositoryProtocol` would force one or the other into
  awkward async/sync mismatch (electron-store reads are IPC-async; SQLite
  reads are sync).
- **Different read sites:** user profiles are read by the backend worker
  during transcription — they MUST be on disk where the backend can see
  them. Model profiles are read by the dashboard toolbar — they MUST be on
  disk where the renderer can see them without server round-trips. These
  are mutually exclusive constraints.
- **Different schema-versioning needs:** user profiles need forward-only
  schema versioning (FR16, R-EL30) because they're snapshotted into
  `transcription_jobs`. Model profiles don't get snapshotted; the active
  profile id is a runtime selector, not a frozen artifact.

What CAN be shared cheaply:
- **Shape conventions** — both have `id`, `name`, `created_at`, `updated_at`
- **Toolbar selector pattern** — Story 1.6 (active user profile) and
  Story 8.3 (active model profile) both use a `<select>` in `Sidebar.tsx`
  with an electron-store-backed Zustand store. The Zustand-store *file
  pattern* should be identical (same `set`-then-persist hook); we'll write
  Story 1.6 first and Story 8.3 will copy/paste-with-rename. 30-line
  duplication beats premature abstraction (per project rule).

**Conclusion:** keep E1 and E8 separate. The 30 lines of selector-store
duplication is acceptable. If a third profile-like entity appears in
future work, refactor at that point.

---

## 4. Risks and Stop-Conditions

Per the sprint prompt's "Stop and ask before continuing if" list:

| Risk | Mitigation | Stop-condition |
|---|---|---|
| Story 1.7 needs a dep beyond keyring + keyrings.alt | Pre-checked: `cryptography` is already a transitive dep of `keyrings.alt`; no new direct dep needed | If the EncryptedKeyring path requires additional libs at runtime, STOP and ask |
| Story 1.9 schema deviates from ADR-009 | Schema in §2 matches v2 readiness report lines 115–120 verbatim (column names, CHECK constraint, lifecycle states) | If a column type or constraint can't be expressed in SQLite, STOP and ask |
| Sprint diff exceeds ~3500 LOC | Estimated LOC budget per commit: A=400, B=150, C=350, D=400, E=350, F=200, G=550 → ~2400 LOC + ~800 test LOC = ~3200 LOC | If commit G alone exceeds 800 LOC, STOP and split E8 across sprints |
| Lighthouse CI wiring proves brittle | Pre-planned downgrade to eslint-plugin-jsx-a11y narrow gate (see §0 override) | No stop required; downgrade documented |
| `model_manager` integration in Story 8.3 surfaces hidden coupling with live engine | Story 8.3 AC3 ("switch REJECTED while live mode is in progress") is the only documented coupling; existing `useLiveMode.ts` exposes the flag | If switching mid-non-live-job is also unsafe (e.g., orphans GPU memory), STOP and ask |

---

## 5. Commit plan recap (with LOC estimates)

| Commit | Stories | Files | Est. LOC | Notes |
|---|---|---|---|---|
| A | 1.2 + 1.3 | migration 008/009, profile_repository, profile model on notebook.py, snapshot helper, 4 test files | ~700 | Foundation; everything else depends on this |
| B | 1.4 | electron main IPC, preload, useFolderPicker hook, hook test, doc | ~150 | Tiny but cross-cutting |
| C | 1.5 + 1.6 | EmptyProfileForm.tsx, activeProfileStore.ts, Sidebar.tsx changes, 3 test files | ~450 | UI-heavy |
| D | 1.7 | utils/keychain.py, utils/config_migration.py, deployment-guide.md addition, 2 test files | ~400 | Backend + docs |
| E | 1.8 | useAriaAnnouncer hook, store, AriaLiveRegion, a11yLabels.ts, eslint update, lighthouserc.json (or downgrade), accessibility.md, 3 test files | ~400 | A11y scaffold; fed by C and G |
| F | 1.9 | migration 010, diarization_review_repository.py, 2 test files | ~250 | Data layer only — consumer in Sprint 3 |
| G | 8.1–8.4 | modelProfileStore.ts service, SettingsModal additions, Sidebar additions, 3 test files | ~600 | Largest UI commit; carries the "same selector pattern" duplication |
| Final | mark 12 stories DONE in epics.md | epics.md | ~30 | Bookkeeping |

**Total ~2980 LOC + tests** — within the 3500 ceiling.

---

## 6. Dependency order recap

```
   Commit A (1.2 + 1.3) ─┐
                         ├─► Commit C (1.5 + 1.6 — needs profile CRUD)
   Commit B (1.4) ───────┘
                                  │
   Commit D (1.7) — depends on A's private_field_refs only
   Commit E (1.8) — depends on nothing (scaffold)
   Commit F (1.9) — depends on nothing (independent migration)
   Commit G (8.1-8.4) — depends on E's a11y helpers (consumed)
```

Within the sprint, A → B → C → D → E → F → G is a safe sequential order
that satisfies all import-time and consumer-pattern dependencies. The
forward references E1.5 and E1.6 make to Story 1.8's `a11yLabels.ts` are
resolved before the sprint review (commit E lands before review).
