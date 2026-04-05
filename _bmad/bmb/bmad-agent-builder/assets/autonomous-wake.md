---
name: autonomous-wake
description: Default autonomous wake behavior — runs when --headless or -H is passed with no specific task.
---

# Autonomous Wake

You're running autonomously. No one is here. No task was specified. Execute your default wake behavior and exit.

## Context

- Memory location: `_bmad/memory/{skillName}-sidecar/`
- Activation time: `{current-time}`

## Instructions

Execute your default wake behavior, write results to memory, and exit.

## Default Wake Behavior

{default-autonomous-behavior}

## Logging

Append to `_bmad/memory/{skillName}-sidecar/autonomous-log.md`:

```markdown
## {YYYY-MM-DD HH:MM} - Autonomous Wake

- Status: {completed|actions taken}
- {relevant-details}
```
