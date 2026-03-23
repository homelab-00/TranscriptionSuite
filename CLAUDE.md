# Project Rules

Read `docs/project-context.md` for the full project context: tech stack versions,
coding patterns, testing infrastructure, and critical gotchas.

## Quick Reference

- Never use `pip`, always `uv`.
- After UI edits touching CSS classes: `npm run ui:contract:check` from `dashboard/`. See `.claude/skills/ui-contract/SKILL.md` for full workflow.
- When modifying files in `.doc-freshness.yaml`: run `node build/scripts/check-doc-freshness.mjs` (suggestions only).
- Target platforms: Linux KDE Wayland (primary), Windows 11, macOS. Document what doesn't work.
- Read `docs/README_DEV.md` for architecture overview.
