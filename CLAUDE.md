# Project Rules

Read `docs/project-context.md` for the full project context: tech stack versions,
coding patterns, testing infrastructure, and critical gotchas.

## Critical Invariants

**AVOID DATA LOSS AT ALL COSTS.** Transcription results are irreplaceable — the user may
have recorded a once-in-a-lifetime lecture, interview, or meeting. Every code path that
produces a transcription result MUST persist it to durable storage (database or disk)
BEFORE attempting to deliver it to the client. Never let a delivery failure (WebSocket
disconnect, serialization error, client timeout) cause a completed transcription to be
silently discarded. When in doubt, save first, deliver second.

**CREDIT CODE SOURCES.** When writing code that is copied from, ported from, or substantially
inspired by another project's code, add an attribution comment at the implementation site.
Format: `# Adapted from <ProjectName> (<URL>) — <brief description of what was borrowed>`.
This applies to open-source projects (e.g. Scriberr, whisper.cpp), Stack Overflow answers,
blog posts, and academic papers. Do not add credits for general programming patterns or
standard library usage — only when the specific logic or structure came from an identifiable
external source.

## Backend Testing

Run backend tests from `server/backend/` using the **build venv**, not the server venv:

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

**Route handler tests** use the direct-call pattern (not a full HTTP test client):
- Import the route module: `from server.api.routes import transcription`
- Import and monkeypatch the repository module: `importlib.import_module("server.database.job_repository")`
- Patch `get_client_name` on the route module: `monkeypatch.setattr(transcription, "get_client_name", lambda _: "test-client")`
- Call handlers directly: `asyncio.run(transcription.get_transcription_result(job_id, object()))`
- Assert on the returned `JSONResponse`, or catch `HTTPException` with `pytest.raises`

See `tests/test_job_repository_imports.py` and `tests/test_transcription_durability_routes.py` for canonical examples.

## Project Documentation

`docs/index.md` is the master documentation index for this project. Use it as the entry
point when planning new features, creating PRDs, or onboarding to an unfamiliar area:

- **Architecture:** `docs/architecture-server.md` (backend), `docs/architecture-dashboard.md` (frontend)
- **Integration:** `docs/integration-architecture.md` (how server and dashboard communicate)
- **API surface:** `docs/api-contracts-server.md` (all REST + WebSocket endpoints)
- **Data layer:** `docs/data-models-server.md` (database schema, durability system)
- **Source map:** `docs/source-tree-analysis.md` (annotated directory tree, 212 source files)
- **Dev setup:** `docs/development-guide.md` and `docs/deployment-guide.md`
- **AI rules:** `docs/project-context.md` (90 rules — read before implementing code)

When creating a brownfield PRD or planning a feature, point the planning workflow to
`docs/index.md` so it has full project context.

## Quick Reference

- Never use `pip`, always `uv`.
- After UI edits touching CSS classes: `npm run ui:contract:check` from `dashboard/`. See `.claude/skills/ui-contract/SKILL.md` for full workflow.
- When modifying files in `.doc-freshness.yaml`: run `node build/scripts/check-doc-freshness.mjs` (suggestions only).
- Target platforms: Linux KDE Wayland (primary), Windows 11, macOS. Document what doesn't work.
- Read `docs/README_DEV.md` for architecture overview.
- When writing commit messages, use the following style below. Make sure to not break up long lines by splitting them with newlines.

feat/fix/chore/etc(impacted area e.g. tests, stt, dashboard, ui, server, etc): summary of all changes

* feat/fix/chore/etc(impacted area): change 1
* detail 1 (optional, if change if large enough)
* detail 2 (optional, if change if large enough)
...

* feat/fix/chore/etc(impacted area): change 2
* detail 1 (optional, if change if large enough)
* detail 2 (optional, if change if large enough)
...

...
