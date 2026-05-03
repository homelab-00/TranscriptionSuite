---
title: 'GH-99 — GHCR publish-gap defenses (tokenizer/UI/CLI/docs)'
type: 'bugfix'
created: '2026-04-24'
status: 'in-review'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-24-2212-issue-99-83-rca.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** v1.3.3 shipped the legacy-GPU dashboard toggle, but the `transcriptionsuite-server-legacy` GHCR package defaulted to Private on first push, producing a user-facing 403 that the dashboard misrouted to the generic `error` state instead of the dedicated "not-published" banner. Three defensive gaps let this ship silently: (a) `listRemoteTags()` maps only token-endpoint 404 → `not-published`, never 401; (b) `useDocker` never clears cached default-repo tag chips when the legacy toggle flips, so a Private-package 401 leaves stale tags visible; (c) `docker-build-push.sh` exits 0 without reminding the publisher about GHCR's first-push-private default; (d) no release checklist step validates the pushed package is anonymously pullable.

**Approach:** Land four small, independent patches that make this class of failure loud instead of silent. Each patch defends one layer of the publish→pull pipeline. No behavioral change in the happy path.

## Boundaries & Constraints

**Always:**
- Preserve the existing `RemoteTagsResult` discriminated union shape — callers already branch on `status`.
- Token-401 is treated as `not-published` **only when the legacy toggle is ON**. The default repo is known-public; a 401 there is a genuine registry fault and must stay mapped to `error`.
- Toggle-flip clearing runs on both directions (on→off and off→on) so neither variant shows stale chips from the other.
- `docker-build-push.sh` remains idempotent and non-interactive — the warning is informational only, never blocks the script.

**Ask First:**
- Changing the GHCR URL shape, adding new exports to the public `dockerManager` surface, or widening `RemoteTagsResult` with a new variant.

**Never:**
- Calling the GitHub API from `docker-build-push.sh` (no new auth scope, keeps the script portable).
- Adding a GH Actions workflow to publish the legacy image (explicitly out of scope per `deployment-guide.md:148`).
- Touching `resolveImageRepo`, `buildGhcrUrlsForRepo`, or repo constants — those are covered by existing tests and unchanged by this work.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Default repo, public package, tags present | `useLegacyGpu=false`, token 200, tags 200 | `{ status: 'ok', tags: [...] }` | N/A |
| Legacy repo, package Private, anonymous pull | `useLegacyGpu=true`, token 401 | `{ status: 'not-published', tags: [] }` | Banner renders in `ServerView` |
| Legacy repo, package not yet pushed | `useLegacyGpu=true`, token 200, tags 404 | `{ status: 'not-published', tags: [] }` | Banner renders (existing behavior) |
| Default repo, unexpected 401 from token | `useLegacyGpu=false`, token 401 | `{ status: 'error', tags: [] }` | Generic error surface (unchanged) |
| Toggle flip default→legacy | User confirms dialog; `setUseLegacyGpu(true)` resolves | `remoteTags=[]`, `remoteTagsStatus=null` immediately, then refetch | Refetch errors follow normal paths |
| First push of a brand-new GHCR package | `docker-build-push.sh` exits 0 after push | Warning block printed with Settings URL + smoke-check hint | N/A (stdout only) |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts:2669-2699` -- `listRemoteTags()`; add 401 branch gated on `readUseLegacyGpuFromStore()`. Export the function for unit testing.
- `dashboard/src/hooks/useDocker.ts:145-276` -- add `clearRemoteTags` action; export via `UseDockerReturn`.
- `dashboard/components/views/ServerView.tsx:2580-2612` -- legacy toggle confirm handler; call `docker.clearRemoteTags()` then `docker.refreshRemoteTags()` after successful `setUseLegacyGpu` IPC.
- `dashboard/electron/preload.ts` (or equivalent) -- expose nothing new (this is a pure-renderer addition).
- `dashboard/electron/__tests__/dockerManagerLegacyGpu.test.ts` -- add tests for 401 mapping (legacy ON vs OFF).
- `build/docker-build-push.sh:322-343` -- append the post-push visibility warning + smoke-check hint.
- `docs/deployment-guide.md:133-149` -- add "Publish smoke test" subsection after the manual-push block.

## Tasks & Acceptance

**Execution:**
- [ ] `dashboard/electron/dockerManager.ts` -- export `listRemoteTags`; in the token-response branch, when `!tokenResp.ok && tokenResp.status === 401 && readUseLegacyGpuFromStore()` return `{ status: 'not-published', tags: [] }`. Update the comment above the function to document the new branch.
- [ ] `dashboard/electron/__tests__/dockerManagerLegacyGpu.test.ts` -- add three tests using `vi.stubGlobal('fetch', ...)`: (a) legacy ON + token 401 → `not-published`; (b) legacy OFF + token 401 → `error`; (c) legacy ON + token 200 + tags 404 → `not-published` (regression guard).
- [ ] `dashboard/src/hooks/useDocker.ts` -- add `clearRemoteTags` useCallback that sets `remoteTags=[]` and `remoteTagsStatus=null`; expose it on `UseDockerReturn` and the returned object.
- [ ] `dashboard/components/views/ServerView.tsx` -- inside the legacy toggle confirm handler, call `docker.clearRemoteTags?.()` before the IPC and `docker.refreshRemoteTags?.()` after the IPC resolves successfully. The optional-chaining lets tests using the existing mock shape continue to pass.
- [ ] `build/docker-build-push.sh` -- after the "Tags pushed" block, print a yellow warning box for every push with the settings URL (`https://github.com/users/homelab-00/packages/container/<pkg-basename>/settings`), a one-line explanation that GHCR defaults first-push visibility to Private, and the anonymous-pull smoke check (`docker logout ghcr.io && docker pull <image>:<tag>`). Derive `<pkg-basename>` from `IMAGE_NAME`.
- [ ] `docs/deployment-guide.md` -- after the "Build & push it manually" block, add a "**Post-push smoke check**" note with the `docker logout` + `docker pull` commands and a one-line explanation of why this step catches the private-default failure mode.

**Acceptance Criteria:**
- Given a user with `useLegacyGpu=true` and a Private legacy package, when the dashboard fetches remote tags, then the "not-published" banner renders (not the generic error state) and no stale chips remain from the default repo.
- Given a user flipping the legacy toggle, when the confirm promise resolves, then `remoteTags` is cleared immediately and a fresh fetch is issued against the new variant's repo.
- Given the maintainer runs `docker-build-push.sh --variant legacy --build vX.Y.Z`, when the push succeeds, then stdout includes a yellow warning block with the package settings URL and an anonymous-pull smoke-check command.
- Given the full dashboard test suite runs, when the patches land, then all existing tests still pass and three new 401-mapping tests pass.

## Design Notes

**Why gate 401→not-published on the legacy toggle.** The default repo has been public since v1.0.0; a 401 there means something broke in GHCR (outage, auth change, network tampering) and must remain surfaced as `error`. The legacy repo is newer and has a known failure mode (Private default), so 401 there almost always means "visibility not flipped yet" — same UX as 404 at the tags endpoint.

**Why clear tags synchronously on toggle flip.** The IPC roundtrip + refetch takes ~1–2s. During that window the old repo's chips stay visible and the user may click one — pulling a tag that doesn't exist in the new repo. Clearing first prevents that misclick.

**Why docker-build-push.sh doesn't call `gh api`.** Would require a new auth scope (`read:packages`) and fails opaquely on offline pushes. The static warning is always-correct and zero-dependency.

**Example warning block** (goes into `docker-build-push.sh`):

```
⚠ First-time push to a NEW GHCR package? GHCR defaults visibility to PRIVATE.
  If this is the first push of ghcr.io/homelab-00/<pkg>, anonymous pulls will 403.
  Flip to Public at: https://github.com/users/homelab-00/packages/container/<pkg>/settings
  Verify anonymously: docker logout ghcr.io && docker pull <image>:<tag>
```

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: no new TypeScript errors.
- `cd dashboard && npx vitest run electron/__tests__/dockerManagerLegacyGpu.test.ts` -- expected: all tests green, three new cases added.
- `cd dashboard && npx vitest run components/__tests__/ServerView.test.tsx` -- expected: still passing (optional chaining on `clearRemoteTags`).
- `bash -n build/docker-build-push.sh` -- expected: no shell syntax errors.
- `shellcheck build/docker-build-push.sh` -- expected: no new warnings.

**Manual checks:**
- Run `./build/docker-build-push.sh --help` — confirm it still exits 0 and prints usage.
- Render the warning block mentally against `DEFAULT_IMAGE_NAME` and `LEGACY_IMAGE_NAME` — the package basename substitution must produce a valid GitHub settings URL.
