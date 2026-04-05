# Standard Agent Fields

## Frontmatter Fields

Only these fields go in the YAML frontmatter block:

| Field | Description | Example |
|-------|-------------|---------|
| `name` | Full skill name (kebab-case, same as folder name) | `bmad-agent-tech-writer`, `bmad-cis-agent-lila` |
| `description` | [What it does]. [Use when user says 'X' or 'Y'.] | See Description Format below |

## Content Fields

These are used within the SKILL.md body — never in frontmatter:

| Field | Description | Example |
|-------|-------------|---------|
| `displayName` | Friendly name (title heading, greetings) | `Paige`, `Lila`, `Floyd` |
| `title` | Role title | `Tech Writer`, `Holodeck Operator` |
| `icon` | Single emoji | `🔥`, `🌟` |
| `role` | Functional role | `Technical Documentation Specialist` |
| `sidecar` | Memory folder (optional) | `{skillName}-sidecar/` |

## Overview Section Format

The Overview is the first section after the title — it primes the AI for everything that follows.

**3-part formula:**
1. **What** — What this agent does
2. **How** — How it works (role, approach, modes)
3. **Why/Outcome** — Value delivered, quality standard

**Templates by agent type:**

**Companion agents:**
```markdown
This skill provides a {role} who helps users {primary outcome}. Act as {displayName} — {key quality}. With {key features}, {displayName} {primary value proposition}.
```

**Workflow agents:**
```markdown
This skill helps you {outcome} through {approach}. Act as {role}, guiding users through {key stages/phases}. Your output is {deliverable}.
```

**Utility agents:**
```markdown
This skill {what it does}. Use when {when to use}. Returns {output format} with {key feature}.
```

## SKILL.md Description Format

```
{description of what the agent does}. Use when the user asks to talk to {displayName}, requests the {title}, or {when to use}.
```

## Path Rules

### Skill-Internal Files

All references to files within the skill use `./` relative paths:
- `./references/memory-system.md`
- `./references/some-guide.md`
- `./scripts/calculate-metrics.py`

This distinguishes skill-internal files from `{project-root}` paths — without the `./` prefix the LLM may confuse them.

### Memory Files (sidecar)

Always use `{project-root}` prefix: `{project-root}/_bmad/memory/{skillName}-sidecar/`

The sidecar `index.md` is the single entry point to the agent's memory system — it tells the agent what else to load (boundaries, logs, references, etc.). Load it once on activation; don't duplicate load instructions for individual memory files.

### Config Variables

Use directly — they already contain `{project-root}` in their resolved values:
- `{output_folder}/file.md`
- Correct: `{bmad_builder_output_folder}/agent.md`
- Wrong: `{project-root}/{bmad_builder_output_folder}/agent.md` (double-prefix)

