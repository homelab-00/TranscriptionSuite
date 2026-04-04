# Memory System for {displayName}

**Memory location:** `_bmad/memory/{skillName}-sidecar/`

## Core Principle

Tokens are expensive. Only remember what matters. Condense everything to its essence.

## File Structure

### `index.md` — Primary Source

**Load on activation.** Contains:
- Essential context (what we're working on)
- Active work items
- User preferences (condensed)
- Quick reference to other files if needed

**Update:** When essential context changes (immediately for critical data).

### `access-boundaries.md` — Access Control (Required for all agents)

**Load on activation.** Contains:
- **Read access** — Folders/patterns this agent can read from
- **Write access** — Folders/patterns this agent can write to
- **Deny zones** — Explicitly forbidden folders/patterns
- **Created by** — Agent builder at creation time, confirmed/adjusted during init

**Template structure:**
```markdown
# Access Boundaries for {displayName}

## Read Access
- {folder-path-or-pattern}
- {another-folder-or-pattern}

## Write Access
- {folder-path-or-pattern}
- {another-folder-or-pattern}

## Deny Zones
- {explicitly-forbidden-path}
```

**Critical:** On every activation, load these boundaries first. Before any file operation (read/write), verify the path is within allowed boundaries. If uncertain, ask user.

{if-standalone}
- **User-configured paths** — Additional paths set during init (journal location, etc.) are appended here
{/if-standalone}

### `patterns.md` — Learned Patterns

**Load when needed.** Contains:
- User's quirks and preferences discovered over time
- Recurring patterns or issues
- Conventions learned

**Format:** Append-only, summarized regularly. Prune outdated entries.

### `chronology.md` — Timeline

**Load when needed.** Contains:
- Session summaries
- Significant events
- Progress over time

**Format:** Append-only. Prune regularly; keep only significant events.

## Memory Persistence Strategy

### Write-Through (Immediate Persistence)

Persist immediately when:
1. **User data changes** — preferences, configurations
2. **Work products created** — entries, documents, code, artifacts
3. **State transitions** — tasks completed, status changes
4. **User requests save** — explicit `[SM] - Save Memory` capability

### Checkpoint (Periodic Persistence)

Update periodically after:
- N interactions (default: every 5-10 significant exchanges)
- Session milestones (completing a capability/task)
- When file grows beyond target size

### Save Triggers

**After these events, always update memory:**
- {save-trigger-1}
- {save-trigger-2}
- {save-trigger-3}

**Memory is updated via the `[SM] - Save Memory` capability which:**
1. Reads current index.md
2. Updates with current session context
3. Writes condensed, current version
4. Checkpoints patterns.md and chronology.md if needed

## Write Discipline

Persist only what matters, condensed to minimum tokens. Route to the appropriate file based on content type (see File Structure above). Update `index.md` when other files change.

## Memory Maintenance

Periodically condense, prune, and consolidate memory files to keep them lean.

## First Run

If sidecar doesn't exist, load `init.md` to create the structure.
