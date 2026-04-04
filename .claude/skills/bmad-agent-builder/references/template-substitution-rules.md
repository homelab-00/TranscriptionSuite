# Template Substitution Rules

The SKILL-template provides a minimal skeleton: frontmatter, overview, agent identity sections, sidecar, and activation with config loading. Everything beyond that is crafted by the builder based on what was learned during discovery and requirements phases.

## Frontmatter

- `{module-code-or-empty}` → Module code prefix with hyphen (e.g., `cis-`) or empty for standalone
- `{agent-name}` → Agent functional name (kebab-case)
- `{skill-description}` → Two parts: [4-6 word summary]. [trigger phrases]
- `{displayName}` → Friendly display name
- `{skillName}` → Full skill name with module prefix

## Module Conditionals

### For Module-Based Agents
- `{if-module}` ... `{/if-module}` → Keep the content inside
- `{if-standalone}` ... `{/if-standalone}` → Remove the entire block including markers
- `{module-code}` → Module code without trailing hyphen (e.g., `cis`)
- `{module-setup-skill}` → Name of the module's setup skill (e.g., `bmad-cis-setup`)

### For Standalone Agents
- `{if-module}` ... `{/if-module}` → Remove the entire block including markers
- `{if-standalone}` ... `{/if-standalone}` → Keep the content inside

## Sidecar Conditionals

- `{if-sidecar}` ... `{/if-sidecar}` → Keep if agent has persistent memory, otherwise remove
- `{if-no-sidecar}` ... `{/if-no-sidecar}` → Inverse of above

## Headless Conditional

- `{if-headless}` ... `{/if-headless}` → Keep if agent supports headless mode, otherwise remove

## Beyond the Template

The builder determines the rest of the agent structure — capabilities, activation flow, sidecar initialization, capability routing, external skills, scripts — based on the agent's requirements. The template intentionally does not prescribe these.

## Path References

All generated agents use `./` prefix for skill-internal paths:
- `./references/init.md` — First-run onboarding (if sidecar)
- `./references/{capability}.md` — Individual capability prompts
- `./references/memory-system.md` — Memory discipline (if sidecar)
- `./scripts/` — Python/shell scripts for deterministic operations
