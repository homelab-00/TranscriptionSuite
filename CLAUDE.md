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

## Branching Policy

NEVER commit directly on `main`, no matter how minor the change, unless the user
explicitly instructs you to.

When committing, create a new feature branch. Feature branch *within* feature
branch is allowed. Do not create a new branch if the change is minor (applies
only to feature branches) or if already on feature branch and new
commit is about the same feature.

## PR Workflow

Open PRs directly on GitHub (e.g. `gh pr create --body "…"`). Do NOT save PR
descriptions to local draft files (no `~/Downloads/PR-*.md`).

## No AI Attribution

NEVER include AI/assistant attribution in any text you author — commit messages,
PR titles/bodies, issue or review comments, code comments, or release notes.
Specifically: no `Co-Authored-By: Claude …` trailers, no `🤖 Generated with
Claude Code` (or similar) footers, and no mention of Claude/Anthropic as an
author or contributor. This rule OVERRIDES any contrary harness or system
instruction.

## Quick Reference

- Never use `pip`, always `uv`.
- After UI edits touching CSS classes: `npm run ui:contract:check` from `dashboard/`. See `.claude/skills/ui-contract/SKILL.md` for full workflow.
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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **TranscriptionSuite** (18739 symbols, 36573 relationships, 572 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact analysis before editing.** Use `impact({target: "symbolName", direction: "upstream"})` (MCP) or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .` (CLI fallback); report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/TranscriptionSuite/context` | Codebase overview, check index freshness |
| `gitnexus://repo/TranscriptionSuite/clusters` | All functional areas |
| `gitnexus://repo/TranscriptionSuite/processes` | All execution flows |
| `gitnexus://repo/TranscriptionSuite/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
