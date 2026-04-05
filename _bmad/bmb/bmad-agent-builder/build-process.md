---
name: build-process
description: Six-phase conversational discovery process for building BMad agents. Covers intent discovery, capabilities strategy, requirements gathering, drafting, building, and summary.
---

**Language:** Use `{communication_language}` for all output.

# Build Process

Build AI agents through conversational discovery. Your north star: **outcome-driven design**. Every capability prompt should describe what to achieve, not prescribe how. The agent's persona and identity context inform HOW — capability prompts just need the WHAT. Only add procedural detail where the LLM would genuinely fail without it.

## Phase 1: Discover Intent

Understand their vision before diving into specifics. Ask what they want to build and encourage detail.

### When given an existing agent

**Critical:** Treat the existing agent as a **description of intent**, not a specification to follow. Extract *who* this agent is and *what* it achieves. Do not inherit its verbosity, structure, or mechanical procedures — the old agent is reference material, not a template.

If the SKILL.md routing already asked the 3-way question (Analyze/Edit/Rebuild), proceed with that intent. Otherwise ask now:
- **Edit** — changing specific behavior while keeping the current approach
- **Rebuild** — rethinking from core outcomes and persona, full discovery using the old agent as context

For **Edit**: identify what to change, preserve what works, apply outcome-driven principles to the changed portions.

For **Rebuild**: read the old agent to understand its goals and personality, then proceed through full discovery as if building new.

### Discovery questions (don't skip these, even with existing input)

The best agents come from understanding the human's vision directly. Walk through these conversationally — adapt based on what the user has already shared:

- **Who IS this agent?** What personality should come through? What's their voice?
- **How should they make the user feel?** What's the interaction model — conversational companion, domain expert, silent background worker, creative collaborator?
- **What's the core outcome?** What does this agent help the user accomplish? What does success look like?
- **What capabilities serve that core outcome?** Not "what features sound cool" — what does the user actually need?
- **What's the one thing this agent must get right?** The non-negotiable.
- **If memory/sidecar:** What's worth remembering across sessions? What should the agent track over time?

The goal is to conversationally gather enough to cover Phase 2 and 3 naturally. Since users often brain-dump rich detail, adapt subsequent phases to what you already know.

## Phase 2: Capabilities Strategy

Early check: internal capabilities only, external skills, both, or unclear?

**If external skills involved:** Suggest `bmad-module-builder` to bundle agents + skills into a cohesive module.

**Script Opportunity Discovery** (active probing — do not skip):

Identify deterministic operations that should be scripts. Load `./references/script-opportunities-reference.md` for guidance. Confirm the script-vs-prompt plan with the user before proceeding.

## Phase 3: Gather Requirements

Gather through conversation: identity, capabilities, activation modes, memory needs, access boundaries. Refer to `./references/standard-fields.md` for conventions.

Key structural context:

- **Naming:** Standalone: `bmad-agent-{name}`. Module: `bmad-{modulecode}-agent-{name}`
- **Activation modes:** Interactive only, or Interactive + Headless (schedule/cron for background tasks)
- **Memory architecture:** Sidecar at `{project-root}/_bmad/memory/{skillName}-sidecar/`
- **Access boundaries:** Read/write/deny zones stored in memory

**If headless mode enabled, also gather:**
- Default wake behavior (`--headless` | `-H` with no specific task)
- Named tasks (`--headless:{task-name}` or `-H:{task-name}`)

**Path conventions (CRITICAL):**
- Memory: `{project-root}/_bmad/memory/{skillName}-sidecar/`
- Project artifacts: `{project-root}/_bmad/...`
- Skill-internal: `./references/`, `./scripts/`
- Config variables used directly — they already contain full paths (no `{project-root}` prefix)

## Phase 4: Draft & Refine

Think one level deeper. Present a draft outline. Point out vague areas. Iterate until ready.

**Pruning check (apply before building):**

For every planned instruction — especially in capability prompts — ask: **would the LLM do this correctly given just the agent's persona and the desired outcome?** If yes, cut it.

The agent's identity, communication style, and principles establish HOW the agent behaves. Capability prompts should describe WHAT to achieve. If you find yourself writing mechanical procedures in a capability prompt, the persona context should handle it instead.

Watch especially for:
- Step-by-step procedures in capabilities that the LLM would figure out from the outcome description
- Capability prompts that repeat identity/style guidance already in SKILL.md
- Multiple capability files that could be one (or zero — does this need a separate capability at all?)
- Templates or reference files that explain things the LLM already knows

## Phase 5: Build

**Load these before building:**
- `./references/standard-fields.md` — field definitions, description format, path rules
- `./references/skill-best-practices.md` — outcome-driven authoring, patterns, anti-patterns
- `./references/quality-dimensions.md` — build quality checklist

Build the agent using templates from `./assets/` and rules from `./references/template-substitution-rules.md`. Output to `{bmad_builder_output_folder}`.

**Capability prompts are outcome-driven:** Each `./references/{capability}.md` file should describe what the capability achieves and what "good" looks like — not prescribe mechanical steps. The agent's persona context (identity, communication style, principles in SKILL.md) informs how each capability is executed. Don't repeat that context in every capability prompt.

**Agent structure** (only create subfolders that are needed):
```
{skill-name}/
├── SKILL.md               # Persona, activation, capability routing
├── references/            # Progressive disclosure content
│   ├── {capability}.md    # Each internal capability prompt
│   ├── memory-system.md   # Memory discipline (if sidecar)
│   ├── init.md            # First-run onboarding (if sidecar)
│   ├── autonomous-wake.md # Headless activation (if headless)
│   └── save-memory.md     # Explicit memory save (if sidecar)
├── assets/                # Templates, starter files
└── scripts/               # Deterministic code with tests
```

| Location | Contains | LLM relationship |
|----------|----------|-----------------|
| **SKILL.md** | Persona, activation, routing | LLM identity and router |
| **`./references/`** | Capability prompts, reference data | Loaded on demand |
| **`./assets/`** | Templates, starter files | Copied/transformed into output |
| **`./scripts/`** | Python, shell scripts with tests | Invoked for deterministic operations |

**Activation guidance for built agents:**

Activation is a single flow regardless of mode. It should:
- Load config and resolve values (with defaults)
- Load sidecar `index.md` if the agent has memory
- If headless, route to `./references/autonomous-wake.md`
- If interactive, greet the user and continue from memory context or offer capabilities

**Lint gate** — after building, validate and auto-fix:

If subagents available, delegate lint-fix to a subagent. Otherwise run inline.

1. Run both lint scripts in parallel:
   ```bash
   python3 ./scripts/scan-path-standards.py {skill-path}
   python3 ./scripts/scan-scripts.py {skill-path}
   ```
2. Fix high/critical findings and re-run (up to 3 attempts per script)
3. Run unit tests if scripts exist in the built skill

## Phase 6: Summary

Present what was built: location, structure, first-run behavior, capabilities.

Run unit tests if scripts exist. Remind user to commit before quality analysis.

**Offer quality analysis:** Ask if they'd like a Quality Analysis to identify opportunities. If yes, load `quality-analysis.md` with the agent path.
