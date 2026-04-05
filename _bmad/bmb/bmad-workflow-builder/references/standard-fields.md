# Standard Workflow/Skill Fields

## Frontmatter Fields

Only these fields go in the YAML frontmatter block:

| Field | Description | Example |
|-------|-------------|---------|
| `name` | Full skill name (kebab-case, same as folder name) | `bmad-workflow-builder`, `bmad-validate-json` |
| `description` | [5-8 word summary]. [Use when user says 'X' or 'Y'.] | See Description Format below |

## Content Fields (All Types)

These are used within the SKILL.md body — never in frontmatter:

| Field | Description | Example |
|-------|-------------|---------|
| `role-guidance` | Brief expertise primer | "Act as a senior DevOps engineer" |
| `module-code` | Module code (if module-based) | `bmb`, `cis` |

## Simple Utility Fields

| Field | Description | Example |
|-------|-------------|---------|
| `input-format` | What it accepts | JSON file path, stdin text |
| `output-format` | What it returns | Validated JSON, error report |
| `standalone` | Fully standalone, no config needed? | true/false |
| `composability` | How other skills use it | "Called by quality scanners for validation" |

## Simple Workflow Fields

| Field | Description | Example |
|-------|-------------|---------|
| `steps` | Numbered inline steps | "1. Load config 2. Read input 3. Process" |
| `tools-used` | CLIs/tools/scripts | gh, jq, python scripts |
| `output` | What it produces | PR, report, file |

## Complex Workflow Fields

| Field | Description | Example |
|-------|-------------|---------|
| `stages` | Named numbered stages | "01-discover, 02-plan, 03-build" |
| `progression-conditions` | When stages complete | "User approves outline" |
| `headless-mode` | Supports autonomous? | true/false |
| `config-variables` | Beyond core vars | `planning_artifacts`, `output_folder` |
| `output-artifacts` | What it creates (output-location) | "PRD document", "agent skill" |

## Overview Section Format

The Overview is the first section after the title — it primes the AI for everything that follows.

**3-part formula:**
1. **What** — What this workflow/skill does
2. **How** — How it works (approach, key stages)
3. **Why/Outcome** — Value delivered, quality standard

**Templates by skill type:**

**Complex Workflow:**
```markdown
This skill helps you {outcome} through {approach}. Act as {role-guidance}, guiding users through {key stages}. Your output is {deliverable}.
```

**Simple Workflow:**
```markdown
This skill {what it does} by {approach}. Act as {role-guidance}. Use when {trigger conditions}. Produces {output}.
```

**Simple Utility:**
```markdown
This skill {what it does}. Use when {when to use}. Returns {output format} with {key feature}.
```

## SKILL.md Description Format

The frontmatter `description` is the PRIMARY trigger mechanism — it determines when the AI invokes this skill. Most BMad skills are **explicitly invoked** by name (`/skill-name` or direct request), so descriptions should be conservative to prevent accidental triggering.

**Format:** Two parts, one sentence each:
```
[What it does in 5-8 words]. [Use when user says 'specific phrase' or 'specific phrase'.]
```

**The trigger clause** uses one of these patterns depending on the skill's activation style:
- **Explicit invocation (default):** `Use when the user requests to 'create a PRD' or 'edit an existing PRD'.` — Quotes around specific phrases the user would actually say. Conservative — won't fire on casual mentions.
- **Organic/reactive:** `Trigger when code imports anthropic SDK, or user asks to use Claude API.` — For lightweight skills that should activate on contextual signals, not explicit requests.

**Examples:**

Good (explicit): `Builds workflows and skills through conversational discovery. Use when the user requests to 'build a workflow', 'modify a workflow', or 'quality check workflow'.`

Good (organic): `Initializes BMad project configuration. Trigger when any skill needs module-specific configuration values, or when setting up a new BMad project.`

Bad: `Helps with PRDs and product requirements.` — Too vague, would trigger on any mention of PRD even in passing conversation.

Bad: `Use on any mention of workflows, building, or creating things.` — Over-broad, would hijack unrelated conversations.

**Default to explicit invocation** unless the user specifically describes organic/reactive activation during discovery.

## Role Guidance Format

Every generated workflow SKILL.md includes a brief role statement in the Overview or as a standalone line:
```markdown
Act as {role-guidance}. {brief expertise/approach description}.
```
This provides quick prompt priming for expertise and tone. Workflows may also use full Identity/Communication Style/Principles sections when personality serves the workflow's purpose.

## Path Rules

### Skill-Internal Files

All references to files within the skill use `./` prefix:
- `./references/reference.md`
- `./references/discover.md`
- `./scripts/validate.py`

This distinguishes skill-internal files from `{project-root}` paths — without the `./` prefix the LLM may confuse them.

### Project `_bmad` Paths
Use `{project-root}/_bmad/...`:
- `{project-root}/_bmad/planning/prd.md`

### Config Variables
Use directly — they already contain `{project-root}` in their resolved values:
- `{output_folder}/file.md`
- `{planning_artifacts}/prd.md`

**Never:**
- `{project-root}/{output_folder}/file.md` (WRONG — double-prefix, config var already has path)
- `_bmad/planning/prd.md` (WRONG — bare `_bmad` must have `{project-root}` prefix)
