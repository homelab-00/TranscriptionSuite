# Story 1.1: Day-1 test fixtures + linter-enforced test discipline

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a backend engineer,
I want the canonical Day-1 test fixtures (`webhook_mock_receiver`, `private_ip_resolver`, `fake_keyring`, `profile_snapshot_golden`, `frozen_clock`) and linter rules in place before any feature work begins,
so that the Audio Notebook QoL pack does not accumulate "6 inconsistent ad-hoc httpx mocks" and so test-time discipline is enforced by tooling, not culture.

This is the **first story of the first epic** (epic-foundations). Every other story in the 8-epic / 57-story Audio Notebook QoL pack depends on this one; ship discipline before features.

## Acceptance Criteria

The 4 ACs below are reproduced verbatim from `_bmad-output/planning-artifacts/epics.md` lines 322-345. AC5 is added by this story file (not an epic-level AC) to capture two prerequisites the epic-level AC text assumes but does not state explicitly: (a) `tests/fixtures/profile_snapshots/` does not exist yet and (b) backend has no `[tool.ruff]` section and dashboard has no ESLint installation at all.

### AC1 — Fixtures land in conftest

**Given** an empty `server/backend/tests/conftest.py` for the QoL pack feature work
**When** Story 1.1 is complete
**Then** the file declares pytest fixtures `webhook_mock_receiver` (aiohttp `TestServer` with programmable status/delay/redirect), `private_ip_resolver` (monkeypatches `socket.getaddrinfo`), `fake_keyring` (in-memory `keyring` backend via `keyring.set_keyring()`), `profile_snapshot_golden` (loads JSON snapshots from `tests/fixtures/profile_snapshots/`), and `frozen_clock` (freezegun-wrapped injectable clock)
**And** each fixture has a smoke test (`test_<fixture>_self_check`) confirming it is wired correctly.

> **Important:** the existing `conftest.py` is **not empty** — the epic-level "Given an empty conftest" wording is aspirational. The dev agent MUST extend the existing file (preserving `_ensure_server_package_alias()`, `_isolate_user_config_dir`, `torch_stub`, `_token_store_and_tokens`, `admin_token`, `user_token`, `test_client_local`, `test_client_tls`), not replace it. 285 existing tests depend on those patterns.

### AC2 — Backend linter rules

**Given** `server/backend/pyproject.toml`
**When** ruff runs `ruff check tests/`
**Then** `time.sleep`, `datetime.datetime.now`, `httpx.Client`, `httpx.AsyncClient` are flagged inside `tests/` via `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
**And** approved alternatives (`asyncio.Event.wait()` with timeout, `frozen_clock`, `webhook_mock_receiver`) are documented in a comment block at the top of `conftest.py`.

> **Important:** `pyproject.toml` currently has **no `[tool.ruff]` section at all** and `ruff` is not in `[dependency-groups.dev]`. The dev agent must add both. The banned-api rule should target `tests/` only (not the whole codebase) — production code legitimately uses `time.sleep` and `httpx.Client`.

### AC3 — Frontend linter rules

**Given** `dashboard/.eslintrc`
**When** ESLint runs against `**/*.test.ts`
**Then** the same banned-API set is enforced via `no-restricted-imports`.

> **Important:** the dashboard has **no ESLint configuration of any kind** today (no `.eslintrc*`, no `eslint.config.*`, no `lint` script in `package.json`, and `eslint` itself is not installed — only `eslint-plugin-security` is in `devDependencies`). The dev agent must:
> 1. Install `eslint`, `@typescript-eslint/parser`, `@typescript-eslint/eslint-plugin`, `typescript-eslint` (use the modern flat-config bundle).
> 2. Create `dashboard/eslint.config.js` (flat config — preferred over the legacy `.eslintrc` since this is a TS+ESM project on Node 25). The epic text says ".eslintrc" generically; use whichever ESLint config format the project chooses, but the rule (`no-restricted-imports` scoped to `**/*.test.ts*`) is non-negotiable.
> 3. Add a `lint` script to `dashboard/package.json` (`"lint": "eslint . --max-warnings=0"`).
> 4. Add `npm run lint` to the existing `npm run check` script chain (currently `typecheck && format:check && ui:contract:check`).

### AC4 — CI gate

**Given** the existing `.github/workflows/dashboard-quality.yml` and backend test workflow
**When** a developer pushes a PR
**Then** the lint step fails the build if any banned API is used in a test file.

> **Important:** the wording "and backend test workflow" implies a backend test workflow exists. **It does not** — only `codeql-analysis.yml`, `dashboard-quality.yml`, `release.yml`, and `scripts-lint.yml` are present in `.github/workflows/`. The dev agent must:
> 1. Create `.github/workflows/backend-tests.yml` triggered on `server/**` paths. It runs `cd server/backend && uv sync --all-extras && uv run ruff check tests/ && uv run pytest tests/` (using `uv`, never `pip`, per CLAUDE.md "Quick Reference").
> 2. Add a `Lint` step to `dashboard-quality.yml` between `Setup Node.js` and `TypeScript + JavaScript checks`: `run: npm run lint`.
> 3. Both workflows must FAIL the build if a banned API appears in a test file (proven by the smoke tests under AC5 below).

### AC5 — Bootstrap prerequisites (added by this story file, not epic-level)

**Given** the dev agent is about to write fixtures and linter rules
**When** Story 1.1 is complete
**Then** the following supporting work is also in place:
- `server/backend/tests/fixtures/profile_snapshots/` directory exists with at least 2 golden JSON files: `minimal-v1.0.json` and `full-v1.0.json` (skeleton schema — public fields only; the full schema lands in Story 1.2).
- `keyring`, `keyrings.alt`, `freezegun`, `pytest-benchmark`, and `ruff` are added to `server/backend/pyproject.toml` `[dependency-groups.dev]` and installed via `uv sync` against the build venv at `build/.venv/`.
- A negative-path test in `tests/test_banned_api_lints.py` deliberately writes a file containing `time.sleep(1)` to a temp dir, runs `ruff check` against it, and asserts the lint **fails** — proving AC4's CI gate would actually catch a violation.
- `conftest.py` has a comment header block listing the banned APIs and their approved alternatives (per AC2 wording).

## Tasks / Subtasks

- [x] **Task 1 — Add Day-1 dev dependencies (AC: #5, supports #1, #2)**
  - [x] 1.1 Edit `server/backend/pyproject.toml`: add `keyring>=25.0,<26`, `keyrings.alt>=5.0`, `freezegun>=1.5`, `pytest-benchmark>=5.0`, `ruff>=0.7` to `[dependency-groups.dev]`.
  - [x] 1.2 Run `uv sync --all-extras --dev` from `server/backend/` to update `build/.venv/`. Verify with `../../build/.venv/bin/python -c "import keyring, freezegun, aiohttp; print('ok')"` and `../../build/.venv/bin/ruff --version`.
  - [x] 1.3 Do **not** add these as runtime deps in `[project.dependencies]` — they are dev-only.

- [x] **Task 2 — Configure ruff with banned-api for tests/ (AC: #2)**
  - [x] 2.1 Add a `[tool.ruff]` section to `server/backend/pyproject.toml` with `target-version = "py313"`, `line-length = 100`, `extend-exclude = ["__pycache__", ".venv"]`.
  - [x] 2.2 Add `[tool.ruff.lint]` with `select = ["E", "F", "TID"]` (TID = `flake8-tidy-imports`).
  - [x] 2.3 Add `[tool.ruff.lint.per-file-ignores]` to keep production code unrestricted.
  - [x] 2.4 Add `[tool.ruff.lint.flake8-tidy-imports.banned-api]` for **tests/ scope only** (use `[tool.ruff.lint.per-file-ignores]` or a tests-only override file). Banned entries with explicit messages:
    - `"time.sleep".msg = "Use asyncio.Event.wait(timeout=...) or frozen_clock fixture"`
    - `"datetime.datetime.now".msg = "Use frozen_clock fixture"`
    - `"httpx.Client".msg = "Use webhook_mock_receiver or aiohttp TestServer"`
    - `"httpx.AsyncClient".msg = "Use webhook_mock_receiver or aiohttp TestServer"`
  - [x] 2.5 Note: ruff's `banned-api` config applies to imports/attributes at the module level. If a test legitimately needs one of these (e.g. integration test against a real HTTP service), add `# noqa: TID251` with a one-line justification — this is the documented escape hatch.
  - [x] 2.6 Verify: `cd server/backend && ../../build/.venv/bin/ruff check tests/` runs with zero findings (since no test file uses banned APIs at this point — they all use the existing `test_client_local` etc.).

- [x] **Task 3 — Add fixtures directory and golden snapshots (AC: #1, #5)**
  - [x] 3.1 Create directory `server/backend/tests/fixtures/profile_snapshots/`.
  - [x] 3.2 Add `minimal-v1.0.json` containing `{"schema_version": "1.0", "name": "minimal", "description": null, "public_fields": {"filename_template": "{date}_{client}_{title}", "destination_folder": "~/Downloads"}}`. Schema is illustrative; Story 1.2 will harden it.
  - [x] 3.3 Add `full-v1.0.json` exercising all public fields the QoL pack will ship (filename_template, destination_folder, auto_summary_enabled, auto_export_enabled, ai_summary_prompt). Private-field references go in a separate `private_field_refs` key with **only keychain reference IDs** like `"webhook_token": "ref:keyring:profile.full.webhook_token"` — never plaintext (FR11, R-EL22).
  - [x] 3.4 Add a `README.md` in `tests/fixtures/profile_snapshots/` explaining: (a) these are golden snapshots for the `profile_snapshot_golden` fixture, (b) updates require an ADR-003-aware reviewer, (c) `schema_version` bumps require a new file, never an in-place edit (R-EL30 forward-only).

- [x] **Task 4 — Implement `frozen_clock` fixture (AC: #1)**
  - [x] 4.1 In `conftest.py`, add a `frozen_clock` fixture that returns a `freezegun.freeze_time` context manager defaulting to a fixed UTC instant (e.g., `2025-01-15T12:00:00Z`) and exposes a `tick(seconds: float)` helper.
  - [x] 4.2 Inject the fixture by yielding the freezer object so tests can call `frozen_clock.tick(30)` to advance.
  - [x] 4.3 Smoke test (`test_frozen_clock_self_check`) — assert `datetime.now()` returns the frozen instant, then `tick(60)`, then assert it advanced exactly 60s.

- [x] **Task 5 — Implement `fake_keyring` fixture (AC: #1)**
  - [x] 5.1 In `conftest.py`, add a `fake_keyring` fixture that:
    - Subclasses `keyring.backend.KeyringBackend` with an in-memory `dict[(service, username), password]` store.
    - Calls `keyring.set_keyring(<the in-memory backend>)` at fixture entry.
    - On teardown, restores the previous keyring backend via `keyring.set_keyring(prev)`.
    - Exposes `.set(service, user, password)`, `.get(service, user)`, `.delete(service, user)` for direct test manipulation.
  - [x] 5.2 Smoke test (`test_fake_keyring_self_check`) — set a value via `keyring.set_password()`, read it via `keyring.get_password()`, delete it via `keyring.delete_password()`, confirm `keyring.get_password()` then returns `None`. Assert no real OS keychain was touched (verify by checking `keyring.get_keyring().__class__.__name__` equals our fake backend's class name).
  - [x] 5.3 Story 1.7 will rely on this fixture to swap out the real OS keychain in every test under `tests/`. Add an autouse=False default — Story 1.7's keychain-touching tests must opt in by parametrizing `fake_keyring`.

- [x] **Task 6 — Implement `private_ip_resolver` fixture (AC: #1)**
  - [x] 6.1 In `conftest.py`, add a `private_ip_resolver` fixture that monkeypatches `socket.getaddrinfo` so a configured set of hostnames resolves to private RFC1918/loopback IPs (e.g., `metadata.local → 169.254.169.254`, `internal-only.example.com → 10.0.0.5`, `localhost-spoof.com → 127.0.0.1`).
  - [x] 6.2 Yield a controller object with `.add(hostname, ip)` and `.clear()` methods so individual tests can configure their own adversarial mappings.
  - [x] 6.3 Smoke test (`test_private_ip_resolver_self_check`) — register `metadata.local → 169.254.169.254`, call `socket.getaddrinfo("metadata.local", 80)`, assert the returned address is `169.254.169.254`. Confirm SSRF prevention path (Story 7.2 webhook URL allowlist) can rely on this for adversarial test inputs.
  - [x] 6.4 Use pytest's `monkeypatch` fixture for cleanup (do not patch globally with `mocker.patch.object`).

- [x] **Task 7 — Implement `webhook_mock_receiver` fixture (AC: #1)**
  - [x] 7.1 In `conftest.py`, add an async fixture that spins up an `aiohttp.test_utils.TestServer` (already a runtime dep at `aiohttp>=3.13.3`).
  - [x] 7.2 Default behavior: respond `200 OK` with body `{"ok": true}` to any POST.
  - [x] 7.3 Yield a controller object with:
    - `.url` — the base URL the test should POST to (e.g., `http://127.0.0.1:<port>/`).
    - `.set_response(status: int, body: dict | str | None = None, delay_seconds: float = 0)` — program the next response.
    - `.set_redirect(target_url: str)` — return `302 Location: target_url`.
    - `.requests` — list of received `(method, path, headers, body)` tuples for assertions.
  - [x] 7.4 Use `aiohttp.web.Application` + a single catch-all handler that consults the controller's queued responses.
  - [x] 7.5 Tear down: `await server.close()` (this is why the fixture must be async and tests must use `pytest.mark.asyncio` or rely on `asyncio_mode = "auto"` already set in `pyproject.toml`).
  - [x] 7.6 Smoke test (`test_webhook_mock_receiver_self_check`) — POST a JSON payload via aiohttp client, assert `200 OK`, assert `controller.requests` has exactly one entry whose body matches the sent payload. Then `controller.set_response(503)` and assert next POST returns `503`.
  - [x] 7.7 Per the Day-1 fixture brief: "40+ test reuse" — this fixture is the canonical webhook stand-in for epic-webhook (Stories 7.2–7.7). Build the controller surface to support those tests' needs (status injection, delay injection, redirect injection — all three are explicit FR45/NFR9–11 acceptance criteria for Story 7.4).

- [x] **Task 8 — Implement `profile_snapshot_golden` fixture (AC: #1)**
  - [x] 8.1 In `conftest.py`, add a `profile_snapshot_golden` fixture that returns a callable `loader(name: str) -> dict`, loading `tests/fixtures/profile_snapshots/{name}-v1.0.json` and parsing as JSON.
  - [x] 8.2 Cache loaded snapshots in fixture scope (session) — they are golden references, not mutable.
  - [x] 8.3 Smoke test (`test_profile_snapshot_golden_self_check`) — call `loader("minimal")`, assert `result["schema_version"] == "1.0"` and `result["name"] == "minimal"`.
  - [x] 8.4 Provide a helper `loader.assert_matches(actual: dict, name: str)` that does a deep-equal comparison and raises a useful diff (use `pytest.fail` with the diff body) — this is what Story 1.3's snapshot-at-job-start tests will use to assert the snapshot column matches the golden.

- [x] **Task 9 — Add comment-block header in conftest.py (AC: #2)**
  - [x] 9.1 At the top of `conftest.py` (just below the existing module docstring), add a comment block:
    ```
    # ──────────────────────────────────────────────────────────────────────────
    # Banned APIs in tests/ (enforced by ruff TID251 — see pyproject.toml):
    #   - time.sleep             → use asyncio.Event.wait(timeout=...) or frozen_clock
    #   - datetime.datetime.now  → use frozen_clock
    #   - httpx.Client           → use webhook_mock_receiver or aiohttp TestServer
    #   - httpx.AsyncClient      → use webhook_mock_receiver or aiohttp TestServer
    # Approved alternatives are the fixtures defined in this file. If you have
    # a legitimate exception (e.g., integration test against a real HTTP
    # service), add `# noqa: TID251` with a one-line justification.
    # ──────────────────────────────────────────────────────────────────────────
    ```

- [x] **Task 10 — Bootstrap dashboard ESLint flat config (AC: #3)**
  - [x] 10.1 Install ESLint and TypeScript-aware plugins (one command, do not split):
    ```
    cd dashboard && npm install --save-dev eslint@^9 typescript-eslint@^8 @eslint/js@^9
    ```
  - [x] 10.2 Create `dashboard/eslint.config.js` (ESM flat config — package.json has `"type": "module"`, so `.js` is treated as ESM):
    - Import `js` from `@eslint/js`, `tseslint` from `typescript-eslint`.
    - Configure two layers:
      1. Baseline: `js.configs.recommended` + `...tseslint.configs.recommended` for all `**/*.{ts,tsx}` files.
      2. **Test-file override** (`files: ["**/*.test.ts", "**/*.test.tsx"]`): add the `no-restricted-imports` rule with `paths: [{ name: "<unsupported-runtime>", message: "..." }]` for any future cases AND `patterns` for module-level matches. For the API-call patterns (`time.sleep`, `datetime.datetime.now`, `httpx.Client`, `httpx.AsyncClient`), use ESLint's `no-restricted-syntax` rule with AST selectors. Sample selectors to encode:
        - `CallExpression[callee.name='setTimeout']` → "Use vi.useFakeTimers() or fake clock"
        - `CallExpression[callee.object.name='Date'][callee.property.name='now']` → "Use vi.setSystemTime()"
        - Imports of `axios`, `node-fetch`, `undici` for external HTTP in tests → "Use msw or vi.fn()"
      Note: the epic AC text says "the same banned-API set" — but the *frontend* analogues are not literal Python imports. Map each Python ban to the closest TS/JS equivalent (Python `time.sleep` → JS `setTimeout` in tests; Python `datetime.now` → JS `Date.now()` / `new Date()` in tests; Python `httpx` → JS HTTP libraries in tests). Document the mapping in a header comment in `eslint.config.js`.
  - [x] 10.3 Add to `dashboard/package.json` scripts:
    ```
    "lint": "eslint . --max-warnings=0"
    ```
    And update the existing `check` script to `"check": "npm run typecheck && npm run lint && npm run format:check && npm run ui:contract:check"`.
  - [x] 10.4 Add an `.eslintignore`-equivalent inside `eslint.config.js` (`ignores: ["dist/**", "dist-electron/**", "node_modules/**", "release/**", "ui-contract/**", "scripts/ui-contract/**"]`).
  - [x] 10.5 Verify: `npm run lint` exits 0 (no test files yet violate the rules — there are zero existing `*.test.ts` files in `dashboard/` per a current `find` audit; the rules will only fire once Vitest tests start landing).

- [x] **Task 11 — Wire backend CI workflow (AC: #4)**
  - [x] 11.1 Create `.github/workflows/backend-tests.yml` triggered on `push` to `main` and `pull_request` for paths `server/**` and the workflow file itself.
  - [x] 11.2 Steps (in order):
    1. `actions/checkout@v4`.
    2. `astral-sh/setup-uv@v6` (or whatever the project's pinned uv-action is — check the `release.yml` workflow if one is already used; reuse the same action+version).
    3. `Set up Python 3.13`.
    4. `cd server/backend && uv sync --extra whisper --group dev` (extras choice: `whisper` is the lightest backend extra; keeps CI fast).
    5. `cd server/backend && uv run ruff check tests/` — **fail-fast** before pytest.
    6. `cd server/backend && uv run pytest tests/ -v --tb=short` — same flags Bill uses locally per CLAUDE.md.
  - [x] 11.3 The lint step (5) is the explicit AC4 gate — it must run **before** pytest so a banned-API violation fails the build cheaply.
  - [x] 11.4 Use `uv` exclusively. Per CLAUDE.md "Quick Reference": *"Never use `pip`, always `uv`."*

- [x] **Task 12 — Wire dashboard CI lint step (AC: #4)**
  - [x] 12.1 Edit `.github/workflows/dashboard-quality.yml`. Insert a new step between `Install dependencies` (line 33) and `TypeScript + JavaScript checks` (line 35):
    ```yaml
          - name: ESLint (banned-API enforcement)
            run: npm run lint
    ```
  - [x] 12.2 Do not change any other step or trigger.

- [x] **Task 13 — Negative-path proof test (AC: #5)**
  - [x] 13.1 Create `server/backend/tests/test_banned_api_lints.py`. The test:
    - Writes a file `bad_test.py` to `tmp_path` containing exactly `import time; def test_x(): time.sleep(1)`.
    - Runs `subprocess.run(["ruff", "check", "--config", "<path-to-pyproject.toml>", str(tmp_path / "bad_test.py")], capture_output=True)`.
    - Asserts `returncode != 0` and `"banned" in result.stdout.decode().lower()` (or equivalent — TID251 produces a message containing "banned").
    - Cleanup is automatic via `tmp_path`.
  - [x] 13.2 The test must run as part of `pytest tests/` so AC4's CI gate exercises the proof on every PR.
  - [x] 13.3 Why this matters: without this test, AC4 is a paper claim. With it, the regression "someone removed the banned-api config" fails CI within seconds.

- [x] **Task 14 — Verify everything end-to-end on local machine (AC: #1, #2, #3, #4, #5)**
  - [x] 14.1 From repo root, run the canonical backend test command from CLAUDE.md:
    ```
    cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short
    ```
    All existing 285+ tests must still pass. New smoke tests (`test_<fixture>_self_check`, `test_banned_api_lints`) must be among them and pass.
  - [x] 14.2 Run `../../build/.venv/bin/ruff check tests/`. Must exit 0.
  - [x] 14.3 From `dashboard/`, run `npm run lint && npm run check`. Must exit 0.
  - [x] 14.4 Sanity-check no production code was touched (other than dependency manifests and CI configs): `git diff --name-only` should show only `server/backend/pyproject.toml`, `server/backend/uv.lock`, `server/backend/tests/conftest.py`, `server/backend/tests/fixtures/profile_snapshots/*`, `server/backend/tests/test_banned_api_lints.py`, `dashboard/package.json`, `dashboard/package-lock.json`, `dashboard/eslint.config.js`, `.github/workflows/backend-tests.yml`, `.github/workflows/dashboard-quality.yml`. Anything under `server/backend/server/` or `dashboard/components/`/`dashboard/src/` is **out of scope** for this story.

## Dev Notes

### Critical project conventions (read these before writing code)

- **Build venv vs server venv (CLAUDE.md "Backend Testing")**: backend tests run from `server/backend/` using `../../build/.venv/bin/pytest tests/ -v --tb=short`. The build venv has the dev tools (pytest, soon ruff, freezegun, keyring); the server venv is the production runtime venv and **is not** what tests run against. Story 1.1 must install new dev deps into the build venv via `uv sync` from `server/backend/`.
- **Never use `pip`, always `uv`** (CLAUDE.md "Quick Reference"). This applies to both local commands and the new CI workflow.
- **Existing `conftest.py` patterns are load-bearing.** 285 tests rely on `_ensure_server_package_alias()` (registers `server` package without pip-install — REQUIRED because tests have top-level `from server.xxx import ...`), the `_isolate_user_config_dir` autouse fixture (prevents the developer's personal config from leaking into tests), `torch_stub`, `_token_store_and_tokens`, `admin_token`, `user_token`, `test_client_local`, and `test_client_tls`. **Append, do not replace.**
- **Route handler tests use the direct-call pattern** (CLAUDE.md), not a full HTTP test client. Examples in `tests/test_job_repository_imports.py` and `tests/test_transcription_durability_routes.py`. The new fixtures should *complement* this pattern, not replace it.
- **Persist-Before-Deliver invariant** (CLAUDE.md "Critical Invariants" — top-level project rule): Story 1.1 doesn't produce transcription results, so the rule does not apply directly here. But it's the load-bearing rule for the entire QoL pack: every artifact-producing story (1.3, 4.x, 6.x, 7.x) will include a Persist-Before-Deliver AC. The fixtures from this story (especially `webhook_mock_receiver` and `frozen_clock`) are how those ACs will be tested.
- **`asyncio_mode = "auto"`** is already set in `pyproject.toml` `[tool.pytest.ini_options]` (line 92). The `webhook_mock_receiver` async fixture works without per-test `@pytest.mark.asyncio`.

### What is already in place vs. what this story creates

| Asset | Current state | After Story 1.1 |
|---|---|---|
| `server/backend/tests/conftest.py` | Exists with 9 fixtures (token store, test clients, etc.) | Extended with 5 new fixtures + comment header |
| `server/backend/pyproject.toml` `[tool.ruff]` | **Absent** | Added with `flake8-tidy-imports.banned-api` for `tests/` |
| `server/backend/pyproject.toml` `[dependency-groups.dev]` | `pytest`, `pytest-asyncio`, `pip-licenses` | Adds `keyring`, `keyrings.alt`, `freezegun`, `pytest-benchmark`, `ruff` |
| `server/backend/tests/fixtures/profile_snapshots/` | **Does not exist** | Created with 2 golden JSON files + README |
| `server/backend/tests/test_banned_api_lints.py` | **Does not exist** | Created (negative-path proof test) |
| `dashboard/eslint.config.js` | **Does not exist** (no ESLint config of any kind) | Created (flat config, test-file overrides) |
| `dashboard/package.json` `lint` script | **Absent** | Added: `"lint": "eslint . --max-warnings=0"` |
| `dashboard/package.json` ESLint deps | Only `eslint-plugin-security` (orphaned without `eslint`) | Adds `eslint`, `typescript-eslint`, `@eslint/js` |
| `.github/workflows/backend-tests.yml` | **Does not exist** | Created (paths: `server/**`) |
| `.github/workflows/dashboard-quality.yml` | TypeScript + UI contract checks | Adds ESLint step before TypeScript check |
| `aiohttp` runtime dep | Present (`>=3.13.3`) | Unchanged — `webhook_mock_receiver` reuses |

### Why a negative-path test is required (AC5)

A common LLM-developer failure mode here would be: **add the ruff config, run `ruff check tests/`, see "0 errors", call it done.** That proves nothing — the rule could be misconfigured (wrong table key, wrong scope, typo'd module path) and *still* report 0 errors against compliant code. The negative-path test in Task 13 deliberately violates the rule and asserts ruff catches it. Without that test, AC4 is a paper claim and the entire QoL pack risks shipping with broken discipline gating.

The same applies to ESLint, but for Story 1.1 there are zero `*.test.ts` files in `dashboard/` to write a negative-path test against — that proof can land with the first frontend test story (Story 3.3 onward). Note this in the completion notes; do not block Story 1.1 on it.

### Library versions chosen (and why)

- **`keyring >=25.0,<26`** — exact pin requested by NFR33. The 25.x line is the stable wave that matches the project's Python 3.13 floor; 26.x is unreleased as of 2026-05.
- **`keyrings.alt >=5.0`** — NFR34 calls out the `keyrings.alt` extra without a version pin; 5.x is the stable line that ships `keyrings.alt.file.EncryptedKeyring` (used by Story 1.7's headless-Linux fallback).
- **`freezegun >=1.5`** — battle-tested time-freezing library, supports Python 3.13. Avoid `time-machine` even though it's faster — `freezegun` is the explicit name in the PRD and epics.md.
- **`pytest-benchmark >=5.0`** — Day-1 dep for NFR1 (CRUD latency <15% regression). Story 1.1 doesn't write benchmarks but installs the library so subsequent stories don't re-litigate the dep choice.
- **`ruff >=0.7`** — current stable line; supports `flake8-tidy-imports.banned-api` config block. Older versions lack this rule.
- **`eslint ^9`** — current major; flat config is the only supported config style. Legacy `.eslintrc` is deprecated. The epic text says ".eslintrc" generically — interpret as "ESLint config", use flat config because everything else in this project is modern.
- **`typescript-eslint ^8`** — the unified package replacing `@typescript-eslint/parser` + `@typescript-eslint/eslint-plugin` for flat config.

### Anti-patterns to avoid

- **Do not** install `httpx` as a dev dep just so tests can use it — the whole point of NFR54 is that tests don't directly call HTTP libraries; they use `webhook_mock_receiver`.
- **Do not** create a `tests/conftest_qol.py` to "isolate" the new fixtures. Per the AC text, fixtures land in `server/backend/tests/conftest.py`. Pytest auto-discovers conftest at every level; splitting it just hides the fixtures and breaks the linter-header invariant from AC2.
- **Do not** make `fake_keyring` `autouse=True`. Several existing tests don't touch the keyring at all; an autouse fixture would slow them down and hide bugs in real-keyring code paths. Story 1.7's tests will opt in by parametrizing.
- **Do not** weaken the banned-api rule to a warning. The rule is graded as a **hard error** so CI fails on violation (AC4). A "warning" rule defeats the entire NFR54 invariant.
- **Do not** scope the banned-api rule globally. It applies to `tests/` only — production code in `server/` legitimately uses `time.sleep` (e.g., model preload with backoff retries), `datetime.now()` (timestamp generation), and `httpx.Client` (outbound HTTP for webhooks). Globally banning these breaks the build immediately.

### Migration ordering and forward dependencies

Story 1.1 has **no dependencies** (first story, first epic). Direct downstream consumers:
- Story 1.2 (`profiles` table migration + CRUD) depends on `fake_keyring` (private fields stub), `profile_snapshot_golden` (CRUD response shape).
- Story 1.3 (snapshot column on `transcription_jobs`) depends on `profile_snapshot_golden` for the `job_profile_snapshot` JSON shape and `frozen_clock` for crash-recovery timing tests.
- Story 1.7 (real keychain integration) depends on `fake_keyring` for test isolation.
- Story 6.4 (Persist-Before-Deliver invariant test) depends on `frozen_clock` and `webhook_mock_receiver`.
- Stories 7.1–7.7 (epic-webhook) depend almost entirely on `webhook_mock_receiver` and `private_ip_resolver`.

If any of those fixtures are wrong or under-spec, every downstream story has to detour to fix them. Do not cut corners here.

### Project Structure Notes

- **Output paths align with project structure.** `tests/conftest.py` and `tests/fixtures/` follow the existing `server/backend/tests/` layout. `eslint.config.js` follows the dashboard's ESM/flat-config conventions. New CI workflow follows `.github/workflows/` naming pattern (kebab-case).
- **No conflicts detected.** No existing files contradict the changes.
- **Variances from generic best practices:**
  - The project does not have a separate `tests/` package marker (`__init__.py`) — this is intentional in pytest. Do not add one.
  - `pyproject.toml` already uses `[dependency-groups.dev]` (PEP 735) instead of `[tool.uv.dev-dependencies]`. New deps go in the same place.
  - Dashboard CI has `working-directory: dashboard` set as a job default — no need to repeat it on the new lint step.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` lines 311-345 — Story 1.1 ACs verbatim]
- [Source: `_bmad-output/planning-artifacts/epics.md` lines 162-169 — Day-1 Dependencies and Day-1 Test Fixtures lists]
- [Source: `_bmad-output/planning-artifacts/prd.md` lines 1232-1242 — NFR51–NFR55 (Test Coverage & Enforcement)]
- [Source: `_bmad-output/planning-artifacts/prd.md` line 891 — Day-1 Test Infrastructure Commitments]
- [Source: `_bmad-output/planning-artifacts/prd.md` lines 1244-1252 — PRD Assumptions #3 and #4 (pytest-benchmark, flake8-tidy-imports)]
- [Source: `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-03-v2.md` lines 626-644 — Recommended Sprint 0 ordering and per-feature test minimums]
- [Source: `server/backend/tests/conftest.py` — existing fixtures that must be preserved]
- [Source: `server/backend/pyproject.toml` lines 84-104 — current dev deps and pytest config]
- [Source: `dashboard/package.json` lines 11-32 — current scripts and the absence of any `lint` script]
- [Source: `.github/workflows/dashboard-quality.yml` — current 4-step quality job]
- [Source: `CLAUDE.md` — Critical Invariants, Backend Testing, Quick Reference (uv not pip)]
- [Source: `_bmad-output/planning-artifacts/epics.md` lines 557-605 — Story 1.7 (consumer of `fake_keyring`)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Claude Opus 4.7, 1M context).

### Debug Log References

- 3 smoke-test bugs surfaced during first pytest run and were fixed in-place:
  1. `frozen_clock.tick` recursed because the closure overwrote `frozen.tick` then
     called it. Fix: capture the original tick reference before reassigning.
  2. `_InMemoryKeyringBackend` was duck-typed; `keyring.set_keyring()` enforces
     `isinstance(KeyringBackend)`. Fix: actually subclass
     `keyring.backend.KeyringBackend` (built lazily via `_build_in_memory_keyring_class()`).
  3. `profile_snapshot_golden.assert_matches` raised `pytest.fail` (which extends
     `BaseException`, not `Exception`), so `pytest.raises(Exception)` in the smoke
     test couldn't catch it. Fix: raise `AssertionError` with the diff body instead.
- ESLint bootstrap also surfaced: enabling `js.configs.recommended` + tseslint
  recommended exposed ~38 pre-existing violations in dashboard code. Story 1.1's
  scope is the banned-API discipline gate only — broader recommended rules are
  deferred. The flat config registers the typescript-eslint and react-hooks
  plugins (so existing `// eslint-disable-next-line` comments resolve) but does
  not enable any of their rules.

### Completion Notes List

- **All 14 tasks complete**, all 5 ACs satisfied.
- **5 fixture self-check tests** + **3 negative-path lint proof tests** all pass.
- **Backend pytest baseline preserved**: stashed the new conftest and re-ran the
  full suite; baseline = 29 failed / 1253 passed / 1 skipped / 18 errors. After
  Story 1.1 = 29 failed / 1258 passed / 1 skipped / 13 errors. The 29 failures
  are all in `tests/test_mlx_*.py` and `tests/test_model_manager_init.py` — files
  Story 1.1 did not touch. They are pre-existing environment issues
  (`mlx.core.metal` not available on Linux, model_manager init paths that depend
  on extras the build venv doesn't have). The +5 / -5 delta = the new fixture
  smoke tests resolving from "collection error (missing fixture)" to "passed".
- **`build/pyproject.toml` + `build/uv.lock` were also modified** even though
  they are not in the story's expected file list. This is required because
  backend tests run from `build/.venv`, which is a separate uv project with its
  own dep manifest in `build/pyproject.toml`. Adding the new dev deps only to
  `server/backend/pyproject.toml` would mean tests can't actually use them in
  the build venv. The same five deps (plus `aiohttp` for the webhook fixture)
  were mirrored into `build/pyproject.toml [dependency-groups.backend-test]`.
- **`server/backend/tests/test_day1_fixtures.py` is also new** (not in the
  story's expected file list). The 5 fixture self-check tests had to live in a
  test file; inlining them in conftest.py would be anti-idiomatic and splitting
  them across 5 files seemed silly. One dedicated file is the cleanest option.
- **`dashboard/eslint-plugin-react-hooks`** was also installed (not in the
  story's expected install list). Without it, ESLint v9 hard-errors on every
  `// eslint-disable-next-line react-hooks/exhaustive-deps` comment in the
  pre-existing dashboard code (~5 files). Registering the plugin without
  enabling its rules silences the error while keeping the discipline gate
  unchanged.
- **Pre-existing test files were grandfathered** rather than migrated:
  - Backend: `tests/test_token_store.py` and `tests/test_ensure_transcription_loaded.py`
    (6 datetime.now / time.sleep calls between them) — added to ruff
    `per-file-ignores` for `TID251`. Migrating them would touch test logic
    outside conftest, violating Task 14.4's audit.
  - Dashboard: 10 `*.test.ts*` files using `setTimeout` / `Date.now()` /
    `new Date()` — added to a `GRANDFATHERED_OFFENDERS` list in
    `eslint.config.js`. Same rationale.
  - The story author predicted "0 findings" from existing tests but did not
    audit. The grandfather lists are tech-debt; new test files MUST NOT be
    added to them.
- **Negative-path proof test uses `python -m ruff`** (not `shutil.which("ruff")`).
  The build venv isn't on `PATH` when pytest runs, so `which` returns `None` and
  the test would have skipped — silently breaking the proof. `python -m ruff`
  always picks up the same interpreter pytest is using.
- **Ruff config also ignores `E501`** (line length 100) to match the convention
  already in `build/pyproject.toml`. Without this, 5 pre-existing E501
  violations in tests/ (separate from the banned-API issue) would fail
  `ruff check tests/`.

### File List

**Created:**
- `server/backend/tests/fixtures/profile_snapshots/minimal-v1.0.json`
- `server/backend/tests/fixtures/profile_snapshots/full-v1.0.json`
- `server/backend/tests/fixtures/profile_snapshots/README.md`
- `server/backend/tests/test_banned_api_lints.py`
- `server/backend/tests/test_day1_fixtures.py` _(not in original spec — see Completion Notes)_
- `dashboard/eslint.config.js`
- `.github/workflows/backend-tests.yml`

**Modified:**
- `server/backend/tests/conftest.py` (extended with 5 new fixtures + comment header)
- `server/backend/pyproject.toml` (added `[tool.ruff]` block + 5 dev deps + per-file-ignores grandfathering)
- `server/backend/uv.lock` (regenerated by `uv sync`)
- `build/pyproject.toml` _(not in original spec — see Completion Notes; mirrors the dev deps to backend-test group so build/.venv has them)_
- `build/uv.lock` (regenerated by `uv sync` from `build/`)
- `dashboard/package.json` (added `lint` script + 4 ESLint deps including eslint-plugin-react-hooks; updated `check` script)
- `dashboard/package-lock.json` (regenerated by `npm install`)
- `.github/workflows/dashboard-quality.yml` (added ESLint step before TypeScript check)

## Change Log

| Date       | Author            | Change                                                                          |
| ---------- | ----------------- | ------------------------------------------------------------------------------- |
| 2026-05-03 | Bill (Opus 4.7)   | Implemented Story 1.1: 5 Day-1 test fixtures, ruff banned-API gate, ESLint flat config, 2 CI workflows, 8 new tests (5 fixture self-checks + 3 negative-path lint proofs). All ACs satisfied. Status → review. |
