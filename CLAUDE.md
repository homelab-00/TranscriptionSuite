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

## Quick Reference

- Never use `pip`, always `uv`.
- After UI edits touching CSS classes: `npm run ui:contract:check` from `dashboard/`. See `.claude/skills/ui-contract/SKILL.md` for full workflow.
- When modifying files in `.doc-freshness.yaml`: run `node build/scripts/check-doc-freshness.mjs` (suggestions only).
- Target platforms: Linux KDE Wayland (primary), Windows 11, macOS. Document what doesn't work.
- Read `docs/README_DEV.md` for architecture overview.
