---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Root Cause Analysis — Vulkan mode failure (Issue #48)'
session_goals: 'Identify fix strategies for image reference + sidecar pull issues'
selected_approach: 'ai-recommended'
techniques_used: ['constraint-mapping', 'chaos-engineering']
ideas_generated: ['fix-image-ref', 'remove-pull-never', 'podman-vulkan-out-of-scope']
session_active: false
workflow_completed: true
context_file: ''
---

## Session Overview

**Topic:** Root Cause Analysis — Vulkan mode failure (GitHub Issue #48)
**Goals:** Identify why Vulkan mode fails at startup and design a robust fix

### Root Causes Identified

1. **Wrong registry** — `ghcr.io/ggerganov/whisper.cpp` → should be `ghcr.io/ggml-org/whisper.cpp` (repo migrated)
2. **Wrong tag** — `main-server-vulkan` → should be `main-vulkan` (no server-specific variant exists; `main-vulkan` includes `whisper-server` binary)
3. **No sidecar pre-pull** — `pullImage()` only handles main server image; `--pull never` blocks Compose from pulling the sidecar

## Technique Execution Results

### Constraint Mapping

**Key Constraints Mapped:**

| Constraint | Real / Imagined | Impact on Fix |
|---|---|---|
| `--no-build` flag | Real — packaged app build context resolves wrong | Must keep |
| `--pull never` flag | Imagined — both registries are public, no auth needed | Safe to remove |
| Podman + Vulkan | Real but pre-existing — documented as unsupported | Out of scope |
| Main image re-pull risk | Imagined — `missing` policy skips already-local images | No risk |

**Breakthrough Finding:** Removing `--pull never` collapses Root Cause 3 entirely. Compose defaults to `pull_policy: missing` which auto-pulls only images not already present locally. The main server image (pre-pulled by `pullImage()`) is unaffected. The Vulkan sidecar gets pulled automatically on first `compose up`.

### Chaos Engineering (Stress Testing)

**Failure scenarios tested against the two-line fix:**

| Scenario | Risk Level | Verdict |
|---|---|---|
| User offline on first Vulkan start | Low | Same failure as before (image doesn't exist either way), clearer error message |
| ggml-org renames/deletes `main-vulkan` tag | Low | Rolling tag rebuilt on every upstream push to master; acceptable risk |
| Sidecar pull has no progress UI | Low | First-time pull is a one-off; subsequent starts skip it |
| Podman + Vulkan | N/A | Pre-existing limitation, documented, unaffected by fix |

**Verdict:** No new failure modes introduced. Fix is clean.

## Idea Organization and Prioritization

### The Fix (2 changes)

**Fix 1 — Correct image reference** (`docker-compose.vulkan.yml:13`)
```yaml
# Before:
image: ghcr.io/ggerganov/whisper.cpp:main-server-vulkan
# After:
image: ghcr.io/ggml-org/whisper.cpp:main-vulkan
```

**Fix 2 — Remove `--pull never`** (`dockerManager.ts:1235`)
```typescript
// Before:
upArgs.push('--no-build', '--pull', 'never');
// After:
upArgs.push('--no-build');
```

### Why This Works

- Fix 1 points to the correct registry (ggml-org, not ggerganov) and correct tag (main-vulkan, not main-server-vulkan)
- Fix 2 allows Compose to auto-pull missing sidecar images using default `missing` policy
- The main server image is unaffected because `pullImage()` already downloads it before `compose up`
- `--no-build` stays because the packaged app build context issue is real

### Out of Scope

- Podman + Vulkan support (pre-existing documented limitation)
- Tag pinning / version locking for upstream whisper.cpp image (acceptable risk with rolling tags)
- Sidecar pull progress UI (one-time pull, not worth the complexity)

## Session Summary

**Key Achievements:**
- Identified 3 root causes through codebase investigation and registry probing
- Mapped constraints to separate real from imagined blockers
- Collapsed a 3-cause problem into a 2-line fix
- Stress-tested the fix against 4 failure scenarios with no regressions found

**Techniques Used:** Constraint Mapping, Chaos Engineering
**Session Duration:** ~25 minutes
