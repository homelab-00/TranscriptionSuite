# Config Overlay Merge — Design Spec

- **Date:** 2026-06-24
- **Status:** Approved design (pending spec review) → next step: implementation plan
- **Area:** server config loading (`server/backend/config.py`), dashboard config bridge (`dashboard/electron/`), dead-code cleanup
- **Related:** Issue origin — "the loader does not merge"; a partial user `config.yaml` silently drops every setting it does not mention.

---

## 1. Problem

The server loads configuration with **first-file-wins, no merge** (`config.py::_load_config`, lines 166–178): it loads the first parseable candidate and returns. The user config file is **first** in the candidate order (`config.py:98–103`), so whenever a user `config.yaml` exists, the baked-in defaults (`/app/config.yaml` in Docker, `server/config.yaml` in dev) are **never read**. A user file that contains only the keys they wanted to change therefore drops *every other setting*.

This directly contradicts the user-facing promise. The dashboard's first-run stub literally says *"This file overrides the container defaults. … Uncomment and edit any section you want to customise."* (`main.ts:970–973`) — but a partial file does not override; it replaces.

### 1.1 The real shape of the bug — a broken cross-tier contract

Investigation (4-agent parallel map, 2026-06-24) found the "layering rework" is **already half-built on the frontend**, and the backend is the missing half:

- **Frontend is already overlay-aware and local-first.** `dashboard/components/views/ServerConfigEditor.tsx`:
  - reads the bundled **template** (full `server/config.yaml`) for structure + comments via `serverConfig:readTemplate()` (`:201`),
  - reads the user's **local** file as a *sparse overlay* via `serverConfig:readLocal()` (`:211`),
  - displays the **merged** effective view with precedence `pending > local > template` (`:237–244`),
  - on save writes a **sparse overlay** via `mergeConfigUpdates()` → `serverConfig:writeLocal()` (`SettingsModal.tsx:604`), then pings `POST /api/llm/config/reload` to invalidate the server singleton (`SettingsModal.tsx:607` → `llm.py:351–362` → `reload_config()`).
  - **It assumes the backend merges the sparse overlay onto defaults. The backend never did.**

- **The backend `/admin/config` editor is dead code** (≈95% confidence). `GET /api/admin/config/full` and `PATCH /api/admin/config` (`admin.py:120–179`), backed by `config_tree.py` (`parse_config_tree` / `apply_config_updates`), have **zero live callers** — the frontend reimplemented the parser in TS (`dashboard/src/utils/configTree.ts`) and went local-first. Only references: `admin.py` itself, `test_config_tree.py`, `test_p2_admin_routes.py`, and docs.

### 1.2 Two adjacent landmines surfaced

1. **`ensureServerConfig` full-copies the template** on first run (`main.ts:950–952`, `COPYFILE_EXCL`), only falling back to a sparse stub if no template is found. So existing installs carry a **full copy** that pins whatever default values were frozen at copy time — the staleness the overlay model was meant to avoid.

2. **The dashboard never mounts the user config into the container.** `dockerManager.ts` builds `composeEnv` but **never sets `USER_CONFIG_DIR`** (verified: no occurrence). The compose volume is `${USER_CONFIG_DIR:-./.empty}:/user-config` (`docker-compose.yml:130`), so a dashboard-launched container mounts the throwaway `./.empty`. Today only a handful of keys reach the server, via env-var bridges (`MAIN_TRANSCRIBER_MODEL`, `LIVE_TRANSCRIBER_MODEL`, `DIARIZATION_MODEL`, `WHISPERCPP_*`, `LOG_*` — see `_ENV_MODEL_OVERRIDES`/`_ENV_LOGGING_OVERRIDES`). The mounted-file path only works when launched via `start-common.sh` (which sets `USER_CONFIG_DIR`, `:351`). So **non-env-bridged settings edited in the dashboard are silently inert for dashboard-Docker users** — and the merge fix alone would not help them until the mount is wired.

### 1.3 Docker file reality (confirmed)

- Defaults baked at **`/app/config.yaml`**, root-owned → **read-only** to the `appuser` (UID 10000) the server runs as (`Dockerfile:93`, no `--chown`).
- User overlay mounts at **`/user-config/config.yaml`**, `appuser`-writable (`Dockerfile:107`).
- `config.set()` already has a read-only→`/user-config` write fallback (`config.py:284–313`).

---

## 2. Goals / Non-Goals

**Goals**

- G1. The running server honors a **sparse** user `config.yaml`: present keys override defaults; absent keys fall through to defaults. (Fixes the reported bug and the broken frontend contract.)
- G2. `config.set()` persists changes as a **sparse overlay**, not a re-materialized full file.
- G3. New installs seed a **sparse stub**, not a full copy, so the overlay stays thin and tracks future default changes.
- G4. Dashboard-launched containers actually **mount the user config** so all edited keys (not just env-bridged ones) reach the server.
- G5. Remove the **dead backend config editor** and its dual-maintenance burden.
- G6. **No regression**: existing full-copy overlays keep working unchanged; env overrides keep winning; explicit-path loads stay single-file.

**Non-Goals**

- No migration/rewrite of existing user files (decided: no migration — zero data-loss risk preferred). Merge already lets newly-added default keys fall through; only values explicitly present in an old full copy stay pinned until the user edits them.
- No change to the env-var bridge mechanism or its precedence.
- No change to the frontend editor's display/merge logic (it already does the right thing).
- No new config keys or schema changes.

---

## 3. Design

### 3.1 Precedence model (lowest → highest)

```
baked-in defaults  <  user overlay (sparse)  <  environment variables
   /app/config.yaml      /user-config/config.yaml     MAIN_TRANSCRIBER_MODEL, …
   (or server/config.yaml in dev)
```

`effective = apply_env( deep_merge(defaults, overlay) )`.

### 3.2 Backend loader — two-layer deep merge (`config.py`) — **core**

Replace first-file-wins with an explicit base+overlay model.

- **base (defaults):** first existing & readable of `[ /app/config.yaml, <server dir>/config.yaml, ./config.yaml ]` — i.e. the highest-priority **non-user** candidate.
- **overlay (user):** `get_user_config_dir()/config.yaml` if it exists & is readable; else none.
- `self.config = _deep_merge(base_dict, overlay_dict)`, then `_apply_env_overrides()` (unchanged, still last).
- **Explicit `config_path=` stays single-file / no-merge** — "load exactly this file." (Preserves test fixtures and the "trust me, this is complete" contract.)

**`_deep_merge(base, overlay) -> dict` semantics (pure, no input mutation):**
- Recurse when **both** sides are dicts.
- Otherwise the overlay value **replaces** the base value. This means:
  - **Lists replace** (never concatenate). Justified: every list in `config.yaml` is an atomic value-list (`local_attention_window: [128,128]`, `mlx_local_attention_window: [256,256]`, `suppress_tokens: [-1]`), never an "extend me" list.
  - **Scalars, `null`, and empty values replace.** Key *presence* in the overlay = override (including an explicit `null`, e.g. `language: null`).
  - **Type mismatch** (e.g. base dict vs overlay scalar): overlay wins wholesale (higher-precedence layer).
- Returns a new merged dict; inputs untouched.

**New properties / state:**
- `_defaults_path` — the base file actually loaded (for logging / diagnostics).
- `_overlay_path` — the user overlay file path (where writes go). Always defined in normal mode (`get_user_config_dir()/config.yaml`, even if not yet created); equals the explicit path in single-file mode.
- `loaded_from` — keep the property; returns `_overlay_path` when set else `_defaults_path`. (Its only remaining consumers — the dead admin routes — are being deleted in §3.6; tests mock it.)

**Error handling (durability-minded — a broken overlay must never take down a server that has valid defaults):**
- Overlay present but invalid YAML → log a warning, **ignore the overlay**, use base only.
- Base candidate invalid YAML → try the next base candidate (today's behavior).
- All base candidates invalid but a valid overlay exists → use the overlay alone (degrade, warn).
- Nothing valid anywhere → `RuntimeError` (unchanged).

### 3.3 `config.set()` — sparse overlay write (`config.py`) — **core**

Today `set()` dumps the **full** `self.config` to the loaded file; after merge that would re-materialize all defaults into the overlay (defeating G3). New behavior:

1. Update the in-memory **effective** config (`self.config`) — unchanged, so the running server sees the change immediately.
2. Persist **only the changed key** into the overlay file: read-or-create `_overlay_path`, set the nested key in that (sparse) dict, dump it back. Never write to `_defaults_path`.
3. Keep the existing read-only → `/user-config`/`/data/config` fallback for `_overlay_path`.

This keeps the live `/admin/diarization` route (`admin.py:109`, the one confirmed-live `set()` caller) writing a clean sparse overlay.

### 3.4 `ensureServerConfig` — seed a sparse stub (`dashboard/electron/main.ts`) — **alignment**

Stop the full template copy (`main.ts:950–960`). On first run, create the **minimal commented stub** that already exists as the fallback branch (`main.ts:963–985`) — sections commented out, ready to uncomment. New installs then get a true sparse overlay; the backend merge fills in everything else. Existing files are untouched (`flag: 'wx'` / EEXIST already no-ops).

`serverConfig:readTemplate/readLocal/writeLocal` are unchanged — they are already the sparse-overlay bridge.

### 3.5 Mount the user config into dashboard-launched containers (`dashboard/electron/dockerManager.ts`) — **mount-gap fix**

Set `composeEnv['USER_CONFIG_DIR'] = app.getPath('userData')` (the dir where `ensureServerConfig`/`ServerConfigEditor` already write `config.yaml`) using the **same mechanism** the other `composeEnv` keys use (compose `.env` / spawn env). Result: host `…/TranscriptionSuite/config.yaml` → container `/user-config/config.yaml`, which `get_user_config_dir()` picks up as the overlay.

- **Env still wins:** the dashboard also injects `MAIN_TRANSCRIBER_MODEL` etc. as env vars; `_apply_env_overrides` runs last, so a key present in both the mounted file and an env bridge resolves to the env value. Consistent, no double-source conflict.
- **Parity with start scripts:** mount the whole userData dir read-write (matching `start-common.sh`); the container only reads/writes `/user-config/config.yaml`, and `set()`'s fallback needs write access.
- **Risk (for the plan):** Windows/macOS userData paths contain spaces (`Application Support`, `AppData`); the compose bind-mount source must be quoted/escaped correctly. Validate on all three target platforms.

### 3.6 Remove the dead backend config editor — **cleanup**

Delete, after the §1.1 dead-code finding:
- `admin.py`: `GET /config/full` (`:120–145`) and `PATCH /config` (`:147–179`) handlers + their imports of `server.config_tree`.
- `server/backend/config_tree.py` (whole file).
- Tests: `tests/test_config_tree.py`; the config-editor classes in `tests/test_p2_admin_routes.py` (`TestP2Route003UpdateConfig`, `TestP2Route003GetFullConfig`) — keep the rest of that file.
- Docs: remove the endpoint rows in `docs/api-contracts-server.md:121–122` and `docs/README_DEV.md:125–126, 1659–1660, 1998–2001`.

Leave the frontend `dashboard/src/utils/configTree.ts` (it's the **live** parser the editor uses) untouched.

---

## 4. Data flow (after)

**Load (server startup / `reload_config()`):**
```
candidates → base = first non-user default file ──┐
get_user_config_dir()/config.yaml → overlay ──────┤→ deep_merge → apply_env → self.config (effective)
(explicit config_path → single file, no merge)
```

**Edit via dashboard (Docker):**
```
ServerConfigEditor (merged view: template ⊕ local) → writeLocal(sparse) → host …/config.yaml
   → mounted (NEW) to /user-config/config.yaml → POST /config/reload → reload_config()
   → loader re-merges defaults ⊕ sparse overlay ⊕ env → effective
```

**Edit via `/admin/diarization` (live):**
```
config.set("diarization","parallel", value) → self.config updated + sparse key written to overlay file
```

---

## 5. Backward compatibility

- **Full-copy overlays keep working**: `deep_merge(defaults, full_copy)` == `full_copy`; identical effective result. (Only caveat: explicitly-present stale values stay pinned — accepted, no migration.)
- **Env overrides unchanged**: applied last, still win.
- **Explicit `config_path` unchanged**: single-file load, no merge — test fixtures stay green.
- **No schema/keys change.**

---

## 6. Testing plan

**New backend tests (`tests/test_config.py` or a new `test_config_merge.py`):**
- Sparse overlay merges onto defaults: a file with only `diarization: {embedding_batch_size: 1}` yields `embedding_batch_size == 1` **and** all other defaults intact.
- Nested deep-merge: overlay `whisper_decode: {no_speech_threshold: 0.6}` merges into the default empty dict without dropping sibling sections.
- **List-replace:** overlay `stt: {suppress_tokens: [1,2]}` replaces (not concatenates) `[-1]`.
- **Explicit `null` overrides** a non-null default.
- **Env still wins** over a merged overlay value (`MAIN_TRANSCRIBER_MODEL` beats `main_transcriber.model` from both layers).
- **Explicit `config_path` = single file** (no merge): a partial explicit file stays partial.
- **`set()` writes sparse**: after `set("diarization","parallel", value=False)`, the overlay file contains only that key path, defaults file untouched, and a fresh `ServerConfig` still resolves all other defaults.
- **Invalid overlay degrades**: malformed overlay YAML → server loads base, logs warning, does not crash.

**Frontend:** no behavior change expected; keep `configTree.test.ts` green. Add/confirm a test that the dashboard sets `USER_CONFIG_DIR` in composeEnv (extend the existing `dockerManager*.test.ts` pattern).

**Deletions:** `test_config_tree.py`; the two config-editor classes in `test_p2_admin_routes.py`.

**Run:** `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`; frontend `cd dashboard && nvm use && npx vitest run` (Node 22).

---

## 7. Affected files

| File | Change |
|------|--------|
| `server/backend/config.py` | Two-layer deep-merge load; `_deep_merge`; `_defaults_path`/`_overlay_path`; sparse `set()`; overlay error handling |
| `server/backend/api/routes/admin.py` | Delete `/config/full` + `/config` handlers + `config_tree` imports |
| `server/backend/config_tree.py` | **Delete** |
| `server/backend/tests/test_config.py` (+ new tests) | Add merge/sparse/env/list tests |
| `server/backend/tests/test_config_tree.py` | **Delete** |
| `server/backend/tests/test_p2_admin_routes.py` | Remove config-editor classes only |
| `dashboard/electron/main.ts` | `ensureServerConfig` seeds sparse stub, not full copy |
| `dashboard/electron/dockerManager.ts` | Set `composeEnv['USER_CONFIG_DIR']` = userData dir |
| `dashboard/electron/__tests__/dockerManager*.test.ts` | Assert `USER_CONFIG_DIR` is set |
| `docs/api-contracts-server.md`, `docs/README_DEV.md` | Remove dead endpoint rows |

---

## 8. Risks & open items

- **R1 — Windows/macOS bind-mount path with spaces** (§3.5). Must quote/escape the compose mount source; validate on Linux + Windows 11 + macOS.
- **R2 — Mounting userData read-write** exposes the whole Electron userData dir (incl. `dashboard-config.json`, caches) to the container. This matches `start-common.sh` behavior, so it is established, but note it; the container only touches `/user-config/config.yaml`.
- **R3 — `gitnexus_impact` before edits.** Per project rules, the implementation plan must run `gitnexus_impact` on `_load_config`, `ServerConfig`, `config.set`, `get_config`/`reload_config` and report blast radius before editing, and `gitnexus_detect_changes` before commit.
- **R4 — `loaded_from` consumers.** After deleting the admin routes, confirm nothing else reads `loaded_from` except `set()` internals and tests.
- **R5 — Existing full-copy staleness** (accepted): document in the PR that users wanting the freshest defaults can delete keys from (or reset) their `config.yaml`.

---

## 9. Decisions (locked)

1. Scope = **full layering rework** (not load-path only).
2. **Delete** the dead backend config editor + update docs.
3. **Fix the mount gap** (`USER_CONFIG_DIR`) in this work.
4. **No migration** of existing user files.
