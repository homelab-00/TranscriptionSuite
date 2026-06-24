# Config Overlay Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend config loader deep-merge a sparse user `config.yaml` overlay onto the baked-in defaults, so partial user files override individual keys instead of silently dropping everything else — fulfilling the contract the dashboard editor already assumes.

**Architecture:** `effective = apply_env( deep_merge(defaults, sparse_overlay) )`. Defaults = first readable of `/app/config.yaml` → `server/config.yaml` → `./config.yaml`. Overlay = `get_user_config_dir()/config.yaml`. `config.set()` persists only the changed key to the overlay. The dashboard seeds a sparse stub (not a full copy) and mounts `USER_CONFIG_DIR` so its edits reach the container. The abandoned backend `/admin/config` editor (`config_tree.py`) is deleted. Docs corrected last.

**Tech Stack:** Python 3.13 + PyYAML (backend), pytest (build venv); Electron/TypeScript + Vitest (dashboard, Node 22).

**Spec:** `docs/superpowers/specs/2026-06-24-config-overlay-merge-design.md`

**Pre-flight (run once before Task 1):**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_config.py -q` → confirm baseline green.
- Per project rules, run `gitnexus_impact({target: "_load_config", direction: "upstream"})` and on `ServerConfig` / `config.set` before editing; report blast radius. (If GitNexus index is stale/unavailable, run `npx gitnexus analyze` first.) Run `gitnexus_detect_changes({repo:"TranscriptionSuite"})` before each code commit.

---

## Task 1: `_deep_merge` pure function

**Files:**
- Modify: `server/backend/config.py` (add module-level function near the top, after `DISABLED_MODEL_SENTINEL`)
- Test: `server/backend/tests/test_config_merge.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `server/backend/tests/test_config_merge.py`:

```python
"""Tests for config deep-merge + sparse-overlay loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server import config


# ── _deep_merge (pure) ───────────────────────────────────────────────────────


def test_deep_merge_overrides_scalar():
    assert config._deep_merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}


def test_deep_merge_recurses_nested_dicts():
    base = {"s": {"x": 1, "y": 2}}
    overlay = {"s": {"y": 9}}
    assert config._deep_merge(base, overlay) == {"s": {"x": 1, "y": 9}}


def test_deep_merge_replaces_lists_not_concatenate():
    assert config._deep_merge({"t": [-1]}, {"t": [1, 2]}) == {"t": [1, 2]}


def test_deep_merge_null_overrides_value():
    assert config._deep_merge({"lang": "en"}, {"lang": None}) == {"lang": None}


def test_deep_merge_type_mismatch_overlay_wins():
    assert config._deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}


def test_deep_merge_adds_new_keys():
    assert config._deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_does_not_mutate_inputs():
    base = {"s": {"x": 1}}
    overlay = {"s": {"y": 2}}
    config._deep_merge(base, overlay)
    assert base == {"s": {"x": 1}}
    assert overlay == {"s": {"y": 2}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py -q`
Expected: FAIL — `AttributeError: module 'server.config' has no attribute '_deep_merge'`

- [ ] **Step 3: Implement `_deep_merge`**

In `server/backend/config.py`, add after the `DISABLED_MODEL_SENTINEL` constant (≈ line 28):

```python
def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overlay* onto *base*, returning a NEW dict.

    - When a key holds a dict on BOTH sides, merge recursively.
    - Otherwise the overlay value replaces the base value. Scalars, lists,
      ``None`` and type mismatches all replace wholesale; lists are never
      concatenated (every list in config.yaml is an atomic value-list).

    Neither input is mutated.
    """
    merged: dict[str, Any] = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = _deep_merge(base_value, overlay_value)
        else:
            merged[key] = overlay_value
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add server/backend/config.py server/backend/tests/test_config_merge.py
git commit -m "feat(config): add pure deep-merge helper for sparse overlays"
```

---

## Task 2: Two-layer loader (defaults + sparse overlay)

**Files:**
- Modify: `server/backend/config.py` — `__init__` (≈70-80), replace `_find_config_file`/`_find_config_candidates`/`_load_config` (≈82-188), add helpers + `defaults_path`/`overlay_path` properties
- Test: `server/backend/tests/test_config_merge.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_config_merge.py`:

```python
# ── Two-layer load (defaults + sparse overlay) ──────────────────────────────
# The autouse fixture _isolate_user_config_dir (conftest.py) points
# get_user_config_dir() at the per-test tmp_path, so a config.yaml written
# there is picked up as the user overlay; defaults come from server/config.yaml.


def test_sparse_overlay_merges_onto_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "diarization:\n  embedding_batch_size: 1\n", encoding="utf-8"
    )
    cfg = config.ServerConfig()
    assert cfg.get("diarization", "embedding_batch_size") == 1   # overridden
    assert cfg.get("diarization", "device") == "auto"            # inherited
    assert cfg.get("diarization", "parallel") is False           # inherited
    assert cfg.get("stt", "buffer_size") == 512                  # untouched section


def test_no_overlay_loads_defaults_only(tmp_path: Path):
    cfg = config.ServerConfig()  # tmp_path has no config.yaml
    assert cfg.get("stt", "buffer_size") == 512
    assert cfg.defaults_path is not None
    assert cfg.defaults_path.name == "config.yaml"


def test_explicit_config_path_is_single_file_no_merge(tmp_path: Path):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("diarization:\n  parallel: true\n", encoding="utf-8")
    cfg = config.ServerConfig(config_path=explicit)
    assert cfg.get("diarization", "parallel") is True
    assert cfg.get("stt", "buffer_size") is None  # defaults NOT merged in


def test_env_override_wins_over_merged_overlay(tmp_path: Path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "main_transcriber:\n  model: from-overlay\n", encoding="utf-8"
    )
    monkeypatch.setenv("MAIN_TRANSCRIBER_MODEL", "from-env")
    cfg = config.ServerConfig()
    assert cfg.get("main_transcriber", "model") == "from-env"


def test_invalid_overlay_degrades_to_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("foo: [1, 2\n", encoding="utf-8")  # unclosed
    cfg = config.ServerConfig()  # must NOT raise
    assert cfg.get("stt", "buffer_size") == 512


def test_overlay_path_points_at_user_file(tmp_path: Path):
    cfg = config.ServerConfig()
    assert cfg.overlay_path == tmp_path / "config.yaml"
    assert cfg.loaded_from == tmp_path / "config.yaml"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py -q`
Expected: FAIL — `AttributeError: 'ServerConfig' object has no attribute 'defaults_path'` (and merge assertions fail).

- [ ] **Step 3: Implement the two-layer loader**

In `server/backend/config.py`:

(a) In `__init__`, after `self._loaded_from: Path | None = None` add:

```python
        self._defaults_path: Path | None = None
        self._overlay_path: Path | None = None
```

(b) **Delete** the methods `_find_config_file` (≈82-116) and `_find_config_candidates` (≈118-149), and **replace** `_load_config` (≈151-188) with the following block of methods:

```python
    @staticmethod
    def _is_readable(path: Path) -> bool:
        """Return True when *path* is an existing, readable file."""
        if not (path.exists() and path.is_file()):
            return False
        try:
            with path.open("r", encoding="utf-8"):
                return True
        except (PermissionError, OSError):
            return False

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        """Parse *path* as a YAML mapping. Empty file -> {}."""
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise yaml.YAMLError(
                f"Config root must be a mapping, got {type(data).__name__}: {path}"
            )
        return data

    def _defaults_candidates(self) -> list[Path]:
        """Readable baked-in default config files (NON-user), priority order."""
        candidates = [
            Path("/app/config.yaml"),  # Docker image default
            Path(__file__).parent.parent / "config.yaml",  # server/config.yaml (dev)
            Path.cwd() / "config.yaml",  # current-directory fallback
        ]
        return [p for p in candidates if self._is_readable(p)]

    def _load_defaults(
        self,
    ) -> tuple[dict[str, Any], Path | None, list[tuple[Path, Exception]]]:
        """Load the highest-priority readable, parseable defaults file."""
        errors: list[tuple[Path, Exception]] = []
        for path in self._defaults_candidates():
            try:
                return self._read_yaml(path), path, errors
            except (yaml.YAMLError, OSError) as e:
                print(f"ERROR: Could not load defaults config {path}: {e}")
                errors.append((path, e))
        return {}, None, errors

    def _load_overlay(self) -> tuple[dict[str, Any], Path | None]:
        """Load the sparse user overlay file if present and valid."""
        path = get_user_config_dir() / "config.yaml"
        if not self._is_readable(path):
            return {}, None
        try:
            return self._read_yaml(path), path
        except (yaml.YAMLError, OSError) as e:
            print(f"WARNING: Ignoring invalid user config overlay {path}: {e}")
            return {}, None

    def _load_config(self) -> None:
        """Load configuration.

        Normal mode: deep-merge a sparse user overlay onto the baked-in
        defaults (defaults < overlay < environment variables). Explicit
        ``config_path`` mode: load that single file as-is (no merge).
        """
        if self._config_path is not None:
            if not self._is_readable(self._config_path):
                raise RuntimeError(
                    f"Configuration file not found or unreadable: {self._config_path}"
                )
            try:
                self.config = self._read_yaml(self._config_path)
            except (yaml.YAMLError, OSError) as e:
                raise RuntimeError(
                    f"Failed to load configuration from {self._config_path}: {e}"
                ) from e
            self._defaults_path = self._config_path
            self._overlay_path = self._config_path
            self._loaded_from = self._config_path
            self._apply_env_overrides()
            print(f"Loaded configuration from: {self._config_path}")
            return

        base_dict, base_path, base_errors = self._load_defaults()
        overlay_dict, overlay_path = self._load_overlay()

        if base_path is None and overlay_path is None:
            details = "\n".join(f"  - {p}: {e}" for p, e in base_errors)
            raise RuntimeError(
                "No configuration file found. Expected baked-in defaults at "
                "/app/config.yaml or server/config.yaml, or a user overlay at "
                f"{get_user_config_dir() / 'config.yaml'}."
                + ("\n" + details if details else "")
            )

        if base_path is None:
            print(
                "WARNING: No valid defaults config found; using user overlay "
                f"only ({overlay_path})."
            )

        self.config = _deep_merge(base_dict, overlay_dict)
        self._defaults_path = base_path
        self._overlay_path = overlay_path or (get_user_config_dir() / "config.yaml")
        self._loaded_from = self._overlay_path
        self._apply_env_overrides()
        print(
            f"Loaded configuration: defaults={base_path}, "
            f"overlay={overlay_path if overlay_path else '(none)'}"
        )
```

(c) After the existing `loaded_from` property (≈235-238) add:

```python
    @property
    def defaults_path(self) -> Path | None:
        """Path of the baked-in defaults file used as the merge base."""
        return self._defaults_path

    @property
    def overlay_path(self) -> Path | None:
        """Path of the writable user overlay file (where set() persists)."""
        return self._overlay_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py tests/test_config.py -q`
Expected: PASS (all merge tests + existing test_config.py).

- [ ] **Step 5: Run the broader config-touching suite for regressions**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config.py tests/test_config_merge.py tests/test_model_manager.py -q`
Expected: PASS (pre-existing unrelated failures noted in TESTING.md may remain; no NEW failures).

- [ ] **Step 6: Commit**

```bash
git add server/backend/config.py server/backend/tests/test_config_merge.py
git commit -m "feat(config): deep-merge sparse user overlay onto baked-in defaults

* feat(config): two-layer loader — defaults (/app or server/config.yaml) merged with sparse user overlay; env overrides still win
* feat(config): explicit config_path stays single-file (no merge); add defaults_path/overlay_path properties
* feat(config): invalid overlay degrades to defaults instead of crashing"
```

---

## Task 3: `config.set()` writes a sparse overlay

**Files:**
- Modify: `server/backend/config.py` — replace `set()` (≈240-313)
- Test: `server/backend/tests/test_config_merge.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_config_merge.py`:

```python
# ── set() persists a sparse overlay ─────────────────────────────────────────


def test_set_creates_sparse_overlay(tmp_path: Path):
    cfg = config.ServerConfig()  # no overlay file yet
    cfg.set("diarization", "parallel", value=False)
    assert cfg.get("diarization", "parallel") is False
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert written == {"diarization": {"parallel": False}}  # SPARSE, not full


def test_set_merges_into_existing_sparse_overlay(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "diarization:\n  parallel: false\n", encoding="utf-8"
    )
    cfg = config.ServerConfig()
    cfg.set("diarization", "embedding_batch_size", value=1)
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert written == {"diarization": {"parallel": False, "embedding_batch_size": 1}}
    # defaults still resolved for untouched keys
    assert cfg.get("stt", "buffer_size") == 512


def test_set_does_not_materialize_full_defaults(tmp_path: Path):
    cfg = config.ServerConfig()
    cfg.set("diarization", "parallel", value=True)
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "stt" not in written and "main_transcriber" not in written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py -k set -q`
Expected: FAIL — current `set()` writes the full merged `self.config`, so `written` contains `stt`, `main_transcriber`, etc.

- [ ] **Step 3: Implement sparse `set()`**

In `server/backend/config.py`, replace the entire `set()` method (≈240-313) with:

```python
    def set(self, *keys: str, value: Any) -> None:
        """Set a nested config value and persist it as a sparse user overlay.

        Updates the in-memory effective config, then writes ONLY the changed
        key into the overlay file (creating it if needed). Defaults files are
        never modified.
        """
        if not keys:
            raise ValueError("At least one key is required")
        for i, key in enumerate(keys):
            if not isinstance(key, str):
                raise TypeError(
                    f"All configuration keys must be strings, got {type(key).__name__} "
                    f"for keys[{i}]: {repr(key)}."
                )
        if self._overlay_path is None:
            raise RuntimeError("Cannot persist config: no overlay path")

        # 1. Update the in-memory effective config.
        self._set_nested(self.config, keys, value)

        # 2. Persist as a sparse overlay (load-or-create, set one key, dump).
        overlay: dict[str, Any] = {}
        if self._overlay_path.exists():
            try:
                overlay = self._read_yaml(self._overlay_path)
            except (yaml.YAMLError, OSError):
                overlay = {}
        self._set_nested(overlay, keys, value)
        self._dump_overlay(overlay)

    @staticmethod
    def _set_nested(target: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
        """Set ``target[keys[0]][...][keys[-1]] = value``, creating dicts."""
        section = target
        for key in keys[:-1]:
            nxt = section.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                section[key] = nxt
            section = nxt
        section[keys[-1]] = value

    def _dump_overlay(self, overlay: dict[str, Any]) -> None:
        """Dump *overlay* to the overlay path, with a read-only fallback chain."""
        fallbacks = [
            p
            for p in (Path("/user-config/config.yaml"), Path("/data/config/config.yaml"))
            if p != self._overlay_path
        ]
        last_error: Exception | None = None
        for target in [self._overlay_path, *fallbacks]:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding="utf-8") as f:
                    yaml.dump(
                        overlay,
                        f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                if target != self._overlay_path:
                    logger.warning(
                        "Config overlay %s is not writable; persisted to %s",
                        self._overlay_path,
                        target,
                    )
                    self._overlay_path = target
                    self._loaded_from = target
                return
            except (PermissionError, OSError) as e:
                last_error = e
                continue
        raise PermissionError(
            f"Cannot write config overlay to {self._overlay_path} or any fallback path"
        ) from last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_config_merge.py -q`
Expected: PASS (all merge + set tests).

- [ ] **Step 5: Regression — the live `/admin/diarization` route still works**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -k "diariz or admin" -q`
Expected: PASS (no new failures). The live `update_diarization_settings` calls `config.set("diarization","parallel", ...)`.

- [ ] **Step 6: Commit**

```bash
git add server/backend/config.py server/backend/tests/test_config_merge.py
git commit -m "feat(config): persist config.set() changes as a sparse overlay, not a full copy"
```

---

## Task 4: Remove the dead backend config editor

**Files:**
- Modify: `server/backend/api/routes/admin.py` — delete `get_full_config` + `update_config` handlers
- Delete: `server/backend/config_tree.py`
- Delete: `server/backend/tests/test_config_tree.py`
- Delete: `server/backend/tests/test_p2_admin_routes.py`

- [ ] **Step 1: Confirm dead (no live callers)**

Run:
```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
grep -rn "config/full\|parse_config_tree\|apply_config_updates" --include=*.py server/ | grep -v tests/ | grep -v config_tree.py
grep -rn "config/full\|/admin/config\b" dashboard/src dashboard/components dashboard/electron | grep -v node_modules
```
Expected: only `admin.py` self-references; **zero** dashboard hits. (The dashboard edits config via Electron IPC `serverConfig:*`, not these endpoints.)

- [ ] **Step 2: Delete the two handlers in `admin.py`**

Remove the block from `@router.get("/config/full")` through the end of `update_config` (the `raise HTTPException(status_code=500, detail=str(e)) from e` just before `@router.post("/webhook/test")`). Exact text to delete:

```python
@router.get("/config/full")
async def get_full_config(request: Request) -> dict[str, Any]:
    """Return the full config.yaml parsed into a structured tree with metadata.

    The tree includes sections, fields, types, and YAML comments so the
    dashboard can dynamically render a settings editor.
    """
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        config = request.app.state.config
        config_path = config.loaded_from
        if config_path is None:
            raise HTTPException(status_code=500, detail="No config file loaded")

        from server.config_tree import parse_config_tree

        tree = parse_config_tree(config_path)
        return tree
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get full config: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/config")
async def update_config(request: Request) -> dict[str, Any]:
    """Update config.yaml values in-place, preserving comments and formatting.

    Expects JSON body: ``{"updates": {"section.key": value, ...}}``
    """
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    updates = body.get("updates")
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=400, detail="'updates' must be a non-empty object")

    config = request.app.state.config
    config_path = config.loaded_from
    if config_path is None:
        raise HTTPException(status_code=500, detail="No config file loaded")

    try:
        from server.config_tree import apply_config_updates, parse_config_tree

        results = apply_config_updates(config_path, updates)
        # Return the freshly-parsed tree so the frontend can reconcile
        tree = parse_config_tree(config_path)
        return {"results": results, **tree}
    except Exception as e:
        logger.error("Failed to update config: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
```

- [ ] **Step 3: Delete the dead module + its tests**

```bash
git rm server/backend/config_tree.py server/backend/tests/test_config_tree.py server/backend/tests/test_p2_admin_routes.py
```

- [ ] **Step 4: Verify nothing imports the removed module + suite still collects**

Run:
```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
grep -rn "config_tree" server/backend --include=*.py || echo "OK: no references"
cd server/backend && ../../build/.venv/bin/pytest tests/ -q --collect-only >/dev/null && echo "COLLECT OK"
```
Expected: "OK: no references" and "COLLECT OK".

- [ ] **Step 5: Run the admin route tests + full backend suite**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -q`
Expected: PASS — no collection errors from the deleted files; no new failures vs. baseline.

- [ ] **Step 6: Commit**

```bash
git add -A server/backend/api/routes/admin.py
git commit -m "refactor(server): remove dead /admin/config editor + config_tree.py

* refactor(server): delete unused GET /api/admin/config/full and PATCH /api/admin/config handlers
* refactor(server): delete config_tree.py (superseded by dashboard local-first editor) and its tests"
```

---

## Task 5: `ensureServerConfig` seeds a sparse stub (not a full copy)

**Files:**
- Modify: `dashboard/electron/main.ts` — `app:ensureServerConfig` handler (≈936-992)

- [ ] **Step 1: Replace the full-copy logic with the sparse stub**

Replace the body of the `ipcMain.handle('app:ensureServerConfig', ...)` handler (≈936-992) with:

```typescript
ipcMain.handle('app:ensureServerConfig', async () => {
  const configDir = app.getPath('userData');
  const configPath = path.join(configDir, 'config.yaml');

  fs.mkdirSync(configDir, { recursive: true });

  // Seed a SPARSE overlay stub. The backend deep-merges this onto the
  // baked-in defaults, so the file should contain ONLY user overrides — not
  // a full copy of the defaults (which would pin stale values over time).
  try {
    fs.writeFileSync(
      configPath,
      [
        '# ============================================================================',
        '# TranscriptionSuite — User Configuration (sparse overrides)',
        '# ============================================================================',
        '# Only the keys you set here override the server defaults; everything else',
        '# is inherited from the bundled config.yaml. See the full reference at',
        '# server/config.yaml in the project repository.',
        '#',
        '# Uncomment and edit only what you want to change.',
        '',
        '# main_transcriber:',
        '#   model: "nvidia/parakeet-tdt-0.6b-v3"',
        '#   compute_type: "default"',
        '#   device: "cuda"',
        '',
        '# diarization:',
        '#   parallel: false',
        '',
      ].join('\n'),
      { encoding: 'utf-8', flag: 'wx' },
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
  }
  return configPath;
});
```

(This removes the `candidates`/`fs.copyFileSync(..., COPYFILE_EXCL)` full-copy loop. The `getTemplateConfigPath` / `serverConfig:readTemplate` handlers below it are unchanged — the editor still reads the bundled template for structure + comments.)

- [ ] **Step 2: Typecheck + build the Electron main**

Run: `cd dashboard && nvm use && npx tsc --noEmit -p electron/tsconfig.json 2>/dev/null || npx tsc --noEmit`
Expected: no new type errors. (If the project has a dedicated build, also run `npm run build:electron` or the equivalent listed in `package.json`.)

- [ ] **Step 3: Commit**

```bash
git add dashboard/electron/main.ts
git commit -m "fix(dashboard): seed sparse config stub instead of full template copy

* fix(dashboard): ensureServerConfig writes a comment-only overrides stub so the backend merge fills in defaults (no stale full copies)"
```

---

## Task 6: Mount the user config into dashboard-launched containers

**Files:**
- Modify: `dashboard/electron/dockerManager.ts` — add `composeEnv['USER_CONFIG_DIR']` (near the other `composeEnv[...]` assignments, ≈2389)
- Test: extend an existing `dashboard/electron/__tests__/dockerManager*.test.ts`

- [ ] **Step 1: Read the existing compose-env test pattern**

Open `dashboard/electron/__tests__/dockerManagerRuntimeProfile.test.ts` and find how it asserts `composeEnv` / the compose `.env` (it captures the spawn `env` or the written `.env`). Mirror that assertion style in Step 3.

- [ ] **Step 2: Add the mount env var**

In `dockerManager.ts`, alongside the other `composeEnv[...]` assignments (immediately before `composeEnv['STARTUP_EVENTS_DIR'] = eventsDir;`, ≈2389), add:

```typescript
  // Mount the user's config.yaml into the container so dashboard-edited
  // settings (beyond the env-bridged model keys) actually reach the server.
  // The backend deep-merges this sparse overlay onto its baked-in defaults;
  // env bridges (MAIN_TRANSCRIBER_MODEL, etc.) still win on top.
  composeEnv['USER_CONFIG_DIR'] = app.getPath('userData');
```

(`app` is already imported in `dockerManager.ts`. The compose volume `${USER_CONFIG_DIR:-./.empty}:/user-config` then resolves to the real userData dir; `composeEnv` is passed as the `docker compose` spawn env at ≈2435.)

- [ ] **Step 3: Add a test asserting USER_CONFIG_DIR is set**

Following the pattern from Step 1, add a test (in the same file or a focused new `dockerManagerUserConfig.test.ts`) asserting that after building the compose env / starting the container, `USER_CONFIG_DIR` equals the mocked `app.getPath('userData')`. Example shape (adapt to the file's existing harness/mocks):

```typescript
it('sets USER_CONFIG_DIR to the userData dir so config.yaml mounts', async () => {
  // ...arrange mocks identical to the existing startContainer test...
  const env = capturedComposeEnv(); // however the suite captures it
  expect(env.USER_CONFIG_DIR).toBe(MOCK_USER_DATA_DIR);
});
```

- [ ] **Step 4: Run the dockerManager tests**

Run: `cd dashboard && nvm use && npx vitest run electron/__tests__/dockerManager`
Expected: PASS, including the new assertion.

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/dockerManager.ts dashboard/electron/__tests__/
git commit -m "fix(dashboard): mount user config.yaml into the container (set USER_CONFIG_DIR)

* fix(dashboard): dockerManager sets USER_CONFIG_DIR on compose env so non-env-bridged settings reach the server via the deep-merge loader"
```

---

## Task 7: Documentation — correct README_DEV + api-contracts (last)

**Files:**
- Modify: `docs/README_DEV.md` — TOC (125-126), endpoint table (1659-1660), endpoint prose (1998-2006), config-priority section (2368-2375), Docker user-config note (1112-1114)
- Modify: `docs/api-contracts-server.md` — endpoint rows (121-122)

- [ ] **Step 1: README_DEV — remove dead endpoint TOC links (125-126)**

Delete these two lines:
```markdown
        - [`GET /api/admin/config/full`](#get-apiadminconfigfull)
        - [`PATCH /api/admin/config`](#patch-apiadminconfig)
```

- [ ] **Step 2: README_DEV — remove dead endpoint table rows (1659-1660)**

Delete:
```markdown
| `/api/admin/config/full` | GET | Admin | Full parsed config tree for the settings editor |
| `/api/admin/config` | PATCH | Admin | Update config.yaml values in-place |
```

- [ ] **Step 3: README_DEV — remove dead endpoint prose (1998-2006)**

Delete the two sections:
```markdown
##### `GET /api/admin/config/full`
Return the full parsed `config.yaml` as a structured tree with sections, fields, types, and inline YAML comments. Used by the dashboard settings editor to dynamically render fields.

##### `PATCH /api/admin/config`
Update one or more config values in-place, preserving YAML comments and formatting.

**Request body (JSON):** `{"updates": {"section.key": value, ...}}`

**Response:** `{"results": {"section.key": "updated"}, ...full config tree...}`

```
(Leave `##### \`GET /api/admin/status\`` above and `##### \`PATCH /api/admin/diarization\`` below intact.)

- [ ] **Step 4: README_DEV — correct the Configuration System priority (2368-2375)**

Replace:
```markdown
### 8.3 Configuration System

All modules use `get_config()` from `server.config`. Configuration is loaded with priority:

1. `/user-config/config.yaml` (Docker with mounted user config)
2. `~/.config/TranscriptionSuite/config.yaml` (Linux user config)
3. `/app/config.yaml` (Docker default)
4. `server/config.yaml` (native development)
```

with:
```markdown
### 8.3 Configuration System

All modules use `get_config()` from `server.config`. Configuration is built by
**deep-merging a sparse user overlay onto the baked-in defaults**, then applying
environment-variable overrides. Precedence (lowest → highest):

1. **Defaults (base)** — first readable of `/app/config.yaml` (Docker image),
   `server/config.yaml` (native development), `./config.yaml`.
2. **User overlay (sparse)** — `get_user_config_dir()/config.yaml`
   (`/user-config/config.yaml` in Docker; `~/.config/TranscriptionSuite/config.yaml`
   on Linux). Only the keys present here override the defaults; everything else is
   inherited. Lists replace (never concatenate); a key present with value `null`
   still overrides.
3. **Environment variables** — e.g. `MAIN_TRANSCRIBER_MODEL`, `LIVE_TRANSCRIBER_MODEL`,
   `DIARIZATION_MODEL`, `WHISPERCPP_*`, `LOG_LEVEL`/`LOG_DIR` — applied last, so they win.

`config.set()` (e.g. the `/api/admin/diarization` toggle) persists changes back to the
**user overlay** as sparse keys; the defaults file is never modified. Passing an explicit
`config_path` to `ServerConfig` loads that single file as-is (no merge). The dashboard's
settings editor is local-first (Electron IPC: `serverConfig:readTemplate/readLocal/writeLocal`)
and writes the same sparse overlay; the dashboard mounts it into the container via
`USER_CONFIG_DIR`.
```

- [ ] **Step 5: README_DEV — note the dashboard now sets USER_CONFIG_DIR (1112-1114)**

Replace:
```markdown
**Optional user config** (bind mount to `/user-config`):

When `USER_CONFIG_DIR` is set, mounts custom config and logs.
```
with:
```markdown
**User config** (bind mount to `/user-config`):

The dashboard sets `USER_CONFIG_DIR` to its Electron `userData` dir automatically,
mounting the user's `config.yaml` to `/user-config/config.yaml` so dashboard-edited
settings reach the server (deep-merged over the image defaults). Manual `docker compose`
launches can set `USER_CONFIG_DIR` themselves; when unset it falls back to `./.empty`.
```

- [ ] **Step 6: api-contracts-server.md — remove dead endpoint rows (121-122)**

Delete:
```markdown
| GET | `/api/admin/config/full` | admin | Full `config.yaml` as a tree (comments/types) |
| PATCH | `/api/admin/config` | admin | In-place config updates `{updates:{section.key:value}}` |
```

- [ ] **Step 7: Verify no stale references remain**

Run:
```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
grep -rn "config/full\|config.yaml values in-place\|loaded with priority" docs/ || echo "OK: no stale config-editor docs"
```
Expected: "OK: no stale config-editor docs".

- [ ] **Step 8: Commit**

```bash
git add docs/README_DEV.md docs/api-contracts-server.md
git commit -m "docs(config): document overlay-merge loading; drop dead /admin/config editor docs

* docs(config): rewrite README_DEV 8.3 to describe defaults<overlay<env deep-merge precedence and sparse set()
* docs(config): note dashboard auto-sets USER_CONFIG_DIR; remove /api/admin/config(/full) rows from README_DEV + api-contracts-server"
```

---

## Final verification

- [ ] **Backend suite:** `cd server/backend && ../../build/.venv/bin/pytest tests/ -q` → no new failures vs. baseline (TESTING.md documents 2 known pre-existing failures).
- [ ] **Frontend:** `cd dashboard && nvm use && npx vitest run` → green; `npx tsc --noEmit` → clean.
- [ ] **GitNexus:** `gitnexus_detect_changes({repo:"TranscriptionSuite"})` → affected symbols limited to `ServerConfig` loader/`set` + admin route removal; no surprise blast radius.
- [ ] **Manual smoke (optional):** write `~/.config/TranscriptionSuite/config.yaml` containing only `diarization:\n  embedding_batch_size: 1`, start the server, confirm logs show `Loaded configuration: defaults=…, overlay=…` and that other defaults (e.g. `stt.buffer_size`) are intact.

## Task coverage check (self-review)

- Spec §3.2 loader merge → Tasks 1–2. §3.3 sparse `set()` → Task 3. §3.4 ensureServerConfig stub → Task 5. §3.5 USER_CONFIG_DIR mount → Task 6. §3.6 dead-code removal → Task 4. §6 testing → tests in Tasks 1–3, 6. §7 affected files → all tasks. Docs (incl. user-requested README_DEV correction) → Task 7 (last). No spec requirement is unmapped.
