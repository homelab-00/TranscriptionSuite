---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Legacy-GPU GHCR image 403/unauthorized — fix path + prevention of publish-gap failures'
session_goals: 'Immediate fix options for issues #99/#83 AND systemic prevention so this class of bug (code-merged feature depending on a manually-published artifact) cannot silently ship broken again'
selected_approach: 'ai-recommended'
techniques_used: ['Five Whys (Phase 1 only, terminated early by user)']
ideas_generated: [confirmed_root_cause, 6_noteworthy_findings]
context_file: ''
session_outcome: 'RCA confirmed (GHCR first-push private-by-default). User elected to act on findings rather than continue to full solutions brainstorm.'
early_termination: true
issues_referenced: ['#99', '#83']
evidence_captured:
  - 'GH-99 body + 2 images (403 error, dashboard state)'
  - 'GH-83 body + 1 follow-up image + log.log (CUDA sm_61 incompatibility)'
  - 'Anonymous GHCR probe: legacy package returns UNAUTHORIZED at token step'
  - 'Public GH package page for -legacy returns HTTP 404'
  - 'Owner profile packages tab lists only transcriptionsuite-server (no -legacy)'
  - 'release.yml does not push Docker images'
  - 'docs/deployment-guide.md:148 confirms manual-only publish for legacy variant'
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-04-24

## Session Overview

**Topic:** Legacy-GPU GHCR image 403/unauthorized — fix path + prevention of publish-gap failures

**Goals:**
- Generate a wide pool of options for the **immediate fix** (unblock users on v1.3.3)
- Generate a wide pool of options for **systemic prevention** (no silent publish gap between merge and user-facing image availability)
- Surface at least one idea addressing the **secondary UX bug** (401 at token step never surfaces the "not-published" panel)
- Aim for 100+ ideas spanning: ops, CI, dashboard UX, docs, release process, alternative distribution, community workflows, edge cases

## Investigation Summary

### Issue #83 (opened 2026-04-18, nate2014jatc, enhancement+cuda labels)
GTX 1070 (CUDA capability 6.1, Pascal `sm_61`) incompatible with shipped PyTorch (supports `sm_70..sm_120`). Log:
```
Found GPU0 NVIDIA GeForce GTX 1070 which is of cuda capability 6.1.
Minimum and Maximum cuda capability supported by this version of PyTorch is (7.0) - (12.0)
```

### Resolution attempt (commit 09899d6, 2026-04-18)
Added full legacy-GPU path: second Dockerfile build target (cu126 wheels, `PYTORCH_VARIANT=cu126`), separate GHCR repo `transcriptionsuite-server-legacy`, dashboard toggle, IPC plumbing, docs. Release v1.3.3 (2026-04-19) advertises the feature.

### Issue #99 (opened 2026-04-23, fox365, bug label — duplicate of #83)
Error when pulling legacy image via dashboard:
```
failed to resolve reference "ghcr.io/homelab-00/transcriptionsuite-server-legacy:v1.3.3":
unexpected status from HEAD request to
https://ghcr.io/v2/homelab-00/transcriptionsuite-server-legacy/manifests/v1.3.3: 403 Forbidden
```
User correctly hypothesized package visibility is Private.

### Root cause (verified today via 6-step probe chain)
The `transcriptionsuite-server-legacy` package on GHCR is **not publicly pullable**. Either:
- **(A)** Pushed successfully but visibility left at GHCR default (private), or
- **(B)** Never pushed after the feature merge (no CI automation; manual-only per `deployment-guide.md:148`).

Both produce identical 403/unauthorized outcomes for end users.

### Secondary bug
Dashboard's `listRemoteTags()` at `dockerManager.ts:2669-2699` maps only **HTTP 404 on the tags/list endpoint** to the `not-published` UI banner. The real failure mode is **HTTP 401 at the token endpoint** (two steps earlier), which falls through to the generic `error` state. Net effect: users see stale tag chips from the default repo and no explanatory banner.

### Session Setup

Investigation complete. Moving to ideation. The Goldilocks framing is:
1. **Immediate (hours)**: how to unblock fox365, nate2014jatc, and anyone else stuck on legacy GPU
2. **Short-term (this release cycle)**: close the UX bug + add guard rails
3. **Structural (next release)**: eliminate publish-gap as a class of failure

## Technique Execution — Phase 1: Five Whys (terminated early by user)

**Why #1 — Why does the pull fail?**

*Hypothesis proposed*: The GHCR package `transcriptionsuite-server-legacy` is not publicly readable — either because it was pushed with GHCR's default visibility (Private) and never flipped to Public, OR because it was never pushed at all.

*User confirmation*: **Option [A] — pushed successfully but visibility left at GHCR default (Private).**

**Root cause locked**: GHCR first-push visibility is Private by default. The v1.3.3 push of `transcriptionsuite-server-legacy` inherited that default, and no step in the release process flipped it to Public.

*Whys 2–5 deferred.* User elected to act on findings rather than continue descending the ladder.

## Additional Findings (from investigation, shared pre-termination)

### #1 — Latent dashboard bug: `not-published` banner never fires for 401
`dockerManager.ts:2669-2699` maps a 404 on `/v2/<pkg>/tags/list` to `status: 'not-published'`, rendering the amber banner at `ServerView.tsx:1567`. But a private GHCR package fails earlier — **401 at the token endpoint** — which falls through to generic `status: 'error'`. The guard rail misses the real failure mode by one error code.

**Proposed patch**: In `listRemoteTags()`, when the token response returns 401 AND `readUseLegacyGpuFromStore() === true`, return `{ status: 'not-published', tags: [] }` instead of `{ status: 'error', tags: [] }`.

### #2 — Stale tag chips leak across legacy toggle
Image `img99-1.png` shows the legacy toggle ON with v1.3.3–v1.3.0 chips still displayed. These are from the default repo (either pre-toggle remote fetch or local images). Gives false confidence pulling will succeed.

**Proposed patch**: Clear `remoteTags`, `localTags`, and `localDates` on toggle flip in `useDocker.ts`, or force a refetch in the legacy-error branch.

### #3 — v1.3.3 release notes advertise an unreachable feature
Release notes claim "New Docker image for legacy Nvidia GPUs" — but the image was 0% reachable externally. A pre-release anonymous `docker pull` smoke check from a clean machine would have caught it.

**Proposed process change**: Add a "publish smoke test" step to the release checklist — run `docker pull <new-image>:<tag>` from a Docker context with no credentials (`docker logout ghcr.io`).

### #4 — `docker-build-push.sh` silently succeeds on private-default
The script exits 0 on a successful push without probing resultant visibility or warning about GHCR's first-push-private default.

**Proposed patch**: After `docker push` success, print:
```
⚠ First-time push to a NEW GHCR package? Default visibility is PRIVATE.
  Flip to Public at: https://github.com/users/homelab-00/packages/container/<name>/settings
  (Look for "Danger Zone" → "Change visibility")
```
Optionally, call `gh api /user/packages/container/<name>` to detect first-push and emit the warning only when needed (requires `read:packages`).

### #5 — Label drift on issues #83/#99
- **#83**: `enhancement` + `cuda`. After v1.3.3 shipped, the blocker shifted from "add cu126 support" to "unreachable image". Keeping `cuda` label misleads future triage.
- **#99**: `bug`. Duplicate of #83 but both OPEN.

**Proposed cleanup**: Add `infra/ghcr` label to #83, remove `cuda` (or keep both), close #99 as duplicate after the fix ships.

### #6 — User-facing close message
After flipping visibility:
> "Flipped `transcriptionsuite-server-legacy` to Public on GHCR. Please retry the Fetch Fresh Image step. If tags still look stale, restart the dashboard once — a mid-session toggle doesn't always refresh the tag list."

## Session Outcome & Next Actions

**Termination reason**: User confirmed root cause and chose to act on captured findings rather than run the full 3-phase brainstorm. Session produced no Phase 2/3 ideas (SCAMPER, Pre-mortem not executed).

### Immediate action (minutes, zero code)
1. Navigate to https://github.com/users/homelab-00/packages/container/transcriptionsuite-server-legacy/settings
2. Scroll to "Danger Zone" → "Change visibility" → **Public**
3. Verify: `curl -sI https://ghcr.io/v2/homelab-00/transcriptionsuite-server-legacy/manifests/v1.3.3` no longer needs auth
4. Comment on #99 and #83 with retry instructions; close #99 as duplicate of #83

### Short-term code patches (this release cycle)
- Finding #1 patch: map token-401 → `not-published` when legacy toggle is ON
- Finding #2 patch: clear remote tag state on toggle flip
- Finding #4 patch: add post-push warning in `docker-build-push.sh`

### Structural / process (next release)
- Finding #3: publish smoke test in release checklist
- Finding #5: label cleanup on #83; close #99

### If a full solutions brainstorm is wanted later
Re-invoke `/bmad-brainstorming` and reference this session file. The Phase 2 (SCAMPER) + Phase 3 (Pre-mortem) techniques remain on the shelf.
