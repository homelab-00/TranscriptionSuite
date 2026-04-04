# Quality Dimensions — Quick Reference

Seven dimensions to keep in mind when building agent skills. The quality scanners check these automatically during quality analysis — this is a mental checklist for the build phase.

## 1. Outcome-Driven Design

Describe what each capability achieves, not how to do it step by step. The agent's persona context (identity, communication style, principles) informs HOW — capability prompts just need the WHAT.

- **The test:** Would removing this instruction cause the agent to produce a worse outcome? If the agent would do it anyway given its persona and the desired outcome, the instruction is noise.
- **Pruning:** If a capability prompt teaches the LLM something it already knows — or repeats guidance already in the agent's identity/style — cut it.
- **When procedure IS value:** Exact script invocations, specific file paths, API calls, security-critical operations. These need low freedom.

## 2. Informed Autonomy

The executing agent needs enough context to make judgment calls when situations don't match the script. The Overview section establishes this: domain framing, theory of mind, design rationale.

- Simple agents with 1-2 capabilities need minimal context
- Agents with memory, autonomous mode, or complex capabilities need domain understanding, user perspective, and rationale for non-obvious choices
- When in doubt, explain *why* — an agent that understands the mission improvises better than one following blind steps

## 3. Intelligence Placement

Scripts handle plumbing (fetch, transform, validate). Prompts handle judgment (interpret, classify, decide).

**Test:** If a script contains an `if` that decides what content *means*, intelligence has leaked.

**Reverse test:** If a prompt validates structure, counts items, parses known formats, compares against schemas, or checks file existence — determinism has leaked into the LLM. That work belongs in a script.

## 4. Progressive Disclosure

SKILL.md stays focused. Detail goes where it belongs.

- Capability instructions → `./references/`
- Reference data, schemas, large tables → `./references/`
- Templates, starter files → `./assets/`
- Memory discipline → `./references/memory-system.md`
- Multi-capability SKILL.md under ~250 lines: fine as-is
- Single-purpose up to ~500 lines: acceptable if focused

## 5. Description Format

Two parts: `[5-8 word summary]. [Use when user says 'X' or 'Y'.]`

Default to conservative triggering. See `./references/standard-fields.md` for full format.

## 6. Path Construction

Only use `{project-root}` for `_bmad` paths. Config variables used directly — they already contain `{project-root}`.

See `./references/standard-fields.md` for correct/incorrect patterns.

## 7. Token Efficiency

Remove genuine waste (repetition, defensive padding, meta-explanation). Preserve context that enables judgment (persona voice, domain framing, theory of mind, design rationale). These are different things — never trade effectiveness for efficiency. A capability that works correctly but uses extra tokens is always better than one that's lean but fails edge cases.
