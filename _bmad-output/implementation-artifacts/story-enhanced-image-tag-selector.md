# Story: Enhanced Docker Image Tag Selector

Status: review

## Story

As a **TranscriptionSuite user**,
I want the Docker image tag selector to show the latest available versions from the registry with clear download status and release-candidate indicators,
so that I can easily pick the right server version without needing to know the full image path or manually check GHCR.

## Acceptance Criteria

1. **Default selection** is the most recent tag that does NOT contain the string `rc` (case-insensitive). If no non-RC tags exist, fall back to the most recent tag overall.

2. **Display format** shows only the version tag (e.g. `v1.3.0`) — the `ghcr.io/homelab-00/transcriptionsuite-server:` prefix is stripped from all dropdown options.

3. **Dropdown shows the 5 most recent tags** fetched from the GitHub Container Registry (GHCR), regardless of whether they are downloaded locally. Tags are sorted by semantic version (descending).

4. **Downloaded indicator**: Each option that exists as a local Docker image shows a `✓` badge on the right side (using the existing `optionMeta.badge` system in `CustomSelect`).

5. **RC (release candidate) styling**: Tags containing `rc` (case-insensitive) in their name are visually dimmed (`optionMeta.dim = true`) and display a `beta` badge.

6. **Older local images**: If the user has locally downloaded images that fall outside the top 5 remote tags, these are appended to the dropdown below the top-5 section (still showing the `✓` badge).

7. **Graceful degradation**: If the GHCR registry fetch fails (network error, rate limit, timeout), the dropdown falls back to the current behavior — listing only locally available images with "Most Recent (auto)" as default.

8. **No new UI box** — the feature stays within the existing "1. Docker Image" GlassCard, replacing the current `CustomSelect` options/logic.

## Tasks / Subtasks

- [x] **Task 1: Add GHCR tag fetching to Electron main process** (AC: 3, 7)
  - [x] 1.1 Add `listRemoteTags()` function to `dashboard/electron/dockerManager.ts`
  - [x] 1.2 Use the OCI Distribution API: `GET https://ghcr.io/v2/homelab-00/transcriptionsuite-server/tags/list`
  - [x] 1.3 Parse response, filter to tags matching `v\d+\.\d+\.\d+(rc\d*)?` pattern
  - [x] 1.4 Sort by semver descending, return top N (configurable, default 5)
  - [x] 1.5 Handle errors gracefully (return empty array on failure)
  - [x] 1.6 Add 5-second timeout to prevent blocking the UI

- [x] **Task 2: Expose via IPC bridge** (AC: 3)
  - [x] 2.1 Add `listRemoteTags` handler to `dashboard/electron/main.ts` IPC handlers
  - [x] 2.2 Add `listRemoteTags` to `preload.ts` electronAPI.docker bridge
  - [x] 2.3 Add TypeScript type to the Docker API interface in `dashboard/src/types/` or inline

- [x] **Task 3: Add remote tags to useDocker hook** (AC: 3, 7)
  - [x] 3.1 Add `remoteTags: string[]` state to `useDocker.ts`
  - [x] 3.2 Fetch remote tags once on mount (not on polling interval — tags change rarely)
  - [x] 3.3 Add `refreshRemoteTags()` to the hook return value
  - [x] 3.4 Expose `remoteTags` and `remoteTagsError` in `UseDockerReturn`

- [x] **Task 4: Implement version parsing utility** (AC: 1, 3, 5)
  - [x] 4.1 Create `parseVersionTag(tag: string)` → `{ major, minor, patch, isRC, raw }` or `null`
  - [x] 4.2 Create `compareVersionTags(a, b)` for descending semver sort (RC < non-RC at same version)
  - [x] 4.3 Place in a small utility (e.g. `dashboard/src/services/versionUtils.ts`)

- [x] **Task 5: Build merged dropdown options in ServerView** (AC: 1–6)
  - [x] 5.1 Replace the current `imageOptions` logic (lines 931–955 of ServerView.tsx)
  - [x] 5.2 Build merged list: top 5 remote tags + any older local-only tags
  - [x] 5.3 For each option, compute `optionMeta`:
    - If downloaded locally → `badge: '✓'`
    - If RC tag → `dim: true` + `badge: 'beta'` (or `'beta ✓'` if also downloaded)
  - [x] 5.4 Default selection = most recent non-RC tag
  - [x] 5.5 Display only version string (strip `ghcr.io/.../server:` prefix)
  - [x] 5.6 When user selects a tag, resolve back to full image name for Docker commands
  - [x] 5.7 Keep the `resolvedImage` / `selectedTagForActions` / `selectedTagForStart` logic working

- [x] **Task 6: Update "Fetch Fresh Image" button behavior** (AC: 3, 4)
  - [x] 6.1 If the selected tag is not downloaded, the "Fetch Fresh Image" button should pull it
  - [x] 6.2 After successful pull, refresh local images so the `✓` badge appears
  - [x] 6.3 "Scan Local Images" button should also trigger remote tag refresh

- [x] **Task 7: Fallback behavior when offline** (AC: 7)
  - [x] 7.1 If `remoteTags` is empty (fetch failed), show only local images
  - [x] 7.2 Keep "Most Recent (auto)" as default in fallback mode (current behavior)
  - [x] 7.3 No error toast — just silent fallback (the dropdown still works)

## Dev Notes

### Architecture & Data Flow

```
GHCR Registry API ──→ dockerManager.listRemoteTags()
                          ↓ (IPC)
                      useDocker.remoteTags[]
                          ↓
                      ServerView: merge(remoteTags, docker.images)
                          ↓
                      CustomSelect(options, optionMeta)
```

### Critical Existing Components

| File | What | Lines |
|------|------|-------|
| `dashboard/electron/dockerManager.ts` | Docker CLI wrapper, `IMAGE_REPO` constant (line 43), `listImages()` (lines 873–1041) | Add `listRemoteTags()` here |
| `dashboard/src/hooks/useDocker.ts` | Docker state hook, image polling, pull operations | Add `remoteTags` state |
| `dashboard/src/hooks/DockerContext.tsx` | Context provider (single instance pattern) | No changes needed |
| `dashboard/components/views/ServerView.tsx` | Image selector UI (lines 931–955 logic, lines 1386–1395 dropdown) | Main UI changes |
| `dashboard/components/ui/CustomSelect.tsx` | Dropdown with `optionMeta` support (`dim`, `badge`) | **No changes needed** |
| `dashboard/electron/preload.ts` | IPC bridge — expose `listRemoteTags` | Add bridge method |

### CustomSelect optionMeta — Already Supports What We Need

`CustomSelect` (lines 5–10, 77–108 of CustomSelect.tsx) already supports:
- `dim: true` → reduces opacity to 40% (line 85) — perfect for RC tags
- `badge: string` → shows right-aligned monospace badge (lines 99–101) — perfect for `✓` and `beta`

No changes to CustomSelect are required.

### GHCR OCI Distribution API

The GitHub Container Registry implements the OCI Distribution Spec. For **public** packages:

```
GET https://ghcr.io/v2/homelab-00/transcriptionsuite-server/tags/list
```

Response:
```json
{
  "name": "homelab-00/transcriptionsuite-server",
  "tags": ["v1.0.0", "v1.0.1", "v1.1.0", "v1.2.0rc", "v1.2.0", "latest"]
}
```

- No authentication required for public packages
- Rate-limited but generous for read-only tag listing
- Use `https` from Node.js `net` module or built-in `fetch` (Electron 28+ has native fetch in main process)
- Filter out `latest`, `main`, `sha-*` tags — only keep `v\d+.\d+.\d+` pattern

### Version Tag Format

The user confirmed tags always follow:
- **Stable**: `v1.2.3` (three digits, no fourth)
- **RC**: `v1.2.3rc` (lowercase `rc` appended, no separator)
- No other suffixes or formats

Sorting: `v1.3.0` > `v1.2.3` > `v1.2.3rc` > `v1.2.2`

### Dropdown Option Construction (pseudocode)

```typescript
// 1. Fetch remote tags (top 5 by semver)
const remoteTags = docker.remoteTags.slice(0, 5); // already sorted desc

// 2. Get local image tags
const localTags = new Set(docker.images.map(i => i.tag));

// 3. Find older local-only tags not in remote top 5
const remoteSet = new Set(remoteTags);
const olderLocalTags = docker.images
  .filter(i => !remoteSet.has(i.tag))
  .map(i => i.tag);

// 4. Build display list: remote first, then older local
const displayTags = [...remoteTags, ...olderLocalTags];

// 5. Build optionMeta
const meta: Record<string, OptionMeta> = {};
for (const tag of displayTags) {
  const isRC = /rc/i.test(tag);
  const isLocal = localTags.has(tag);
  meta[tag] = {
    dim: isRC,
    badge: [isRC && 'beta', isLocal && '✓'].filter(Boolean).join(' '),
  };
}

// 6. Default = first non-RC tag
const defaultTag = displayTags.find(t => !/rc/i.test(t)) || displayTags[0];
```

### Mapping Display Tags Back to Full Image Names

The dropdown shows `v1.3.0` but Docker commands need `ghcr.io/homelab-00/transcriptionsuite-server:v1.3.0`. Use the `IMAGE_REPO` constant:

```typescript
const resolvedImage = `${IMAGE_REPO}:${selectedTag}`;
```

Import or duplicate the `IMAGE_REPO` constant. It's currently in `dockerManager.ts` (line 43). For the renderer side, either:
- Hardcode it (it never changes)
- Expose it via IPC as a getter
- Export from a shared constants file

### Electron Main Process Fetch

Since this runs in the Electron **main process** (Node.js), use `net.fetch` (Electron's native fetch) or Node's built-in `fetch` (Node 18+). Do NOT use `node-fetch` or `axios` — avoid new dependencies.

```typescript
async function listRemoteTags(): Promise<string[]> {
  try {
    const resp = await fetch(
      `https://ghcr.io/v2/homelab-00/transcriptionsuite-server/tags/list`,
      { signal: AbortSignal.timeout(5000) }
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return (data.tags ?? [])
      .filter((t: string) => /^v\d+\.\d+\.\d+(rc\d*)?$/.test(t))
      .sort(compareVersionTags)
      .slice(0, 20); // return more than 5 so ServerView can slice
  } catch {
    return [];
  }
}
```

### Project Structure Notes

- Version utility goes in `dashboard/src/services/versionUtils.ts` — consistent with existing `modelCapabilities.ts` and `apiClient.ts` in that directory
- No new UI components needed — `CustomSelect` handles everything
- No backend (Python/FastAPI) changes — this is purely a dashboard feature

### Testing

- **Unit test** `versionUtils.ts`: parse, compare, sort, RC detection
- **Unit test** `listRemoteTags`: mock fetch, verify filtering and sorting
- **Manual test**: Check dropdown with mix of local/remote tags, offline mode, RC tags

### References

- [Source: dashboard/components/ui/CustomSelect.tsx] — optionMeta interface (lines 5–10)
- [Source: dashboard/components/views/ServerView.tsx] — current image logic (lines 931–955), UI (lines 1386–1395)
- [Source: dashboard/electron/dockerManager.ts] — IMAGE_REPO constant (line 43), listImages() (lines 873–1041)
- [Source: dashboard/src/hooks/useDocker.ts] — images state (lines 127–130), refreshImages (lines 207–212), pullImage (lines 273–288)
- [Source: docs/project-context.md] — coding patterns, testing infrastructure
- [OCI Distribution Spec — Tags List](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6 (1M context)

### Debug Log References
- ServerView test mock needed `remoteTags`, `remoteTagsError`, `refreshRemoteTags` fields to match updated `UseDockerReturn` interface

### Completion Notes List
- Created `versionUtils.ts` with `parseVersionTag()`, `compareVersionTags()`, `sortVersionTagsDesc()` — 14 unit tests all passing
- Added `listRemoteTags()` to `dockerManager.ts` using OCI Distribution API with 5s `AbortSignal.timeout`; inline semver comparator to avoid cross-process import
- Wired IPC: `docker:listRemoteTags` handler in `main.ts`, bridge in `preload.ts`, type in `electron.d.ts`
- Extended `useDocker` hook with `remoteTags`, `remoteTagsError`, `refreshRemoteTags()` — fetches once on mount, not on polling interval
- Replaced `ServerView` image selection with merged dropdown: top 5 remote tags + older local-only tags, `optionMeta` badges (`✓` for downloaded, `beta` + dim for RC), default = most recent non-RC
- Tags display as short versions (e.g. `v1.3.0`), resolved to full image name via `IMAGE_REPO` constant for Docker commands
- "Scan Local Images" button now also triggers `refreshRemoteTags()`
- Fallback: when `remoteTags` is empty (offline/fetch failed), shows only local images with "Most Recent (auto)" default — no error toast
- All 371 tests pass, 0 TypeScript errors

### Change Log
- 2026-04-06: Implemented all 7 tasks for Enhanced Docker Image Tag Selector story

### File List
- `dashboard/src/services/versionUtils.ts` (new) — version tag parsing and comparison utilities
- `dashboard/src/services/versionUtils.test.ts` (new) — 14 unit tests for version utils
- `dashboard/electron/dockerManager.ts` (modified) — added `listRemoteTags()` function and export
- `dashboard/electron/main.ts` (modified) — added `docker:listRemoteTags` IPC handler
- `dashboard/electron/preload.ts` (modified) — added `listRemoteTags` to ElectronAPI interface and bridge
- `dashboard/src/types/electron.d.ts` (modified) — added `listRemoteTags` to docker API type
- `dashboard/src/hooks/useDocker.ts` (modified) — added `remoteTags`, `remoteTagsError`, `refreshRemoteTags` state and fetch
- `dashboard/components/views/ServerView.tsx` (modified) — replaced image selector with merged remote+local dropdown with optionMeta
- `dashboard/components/__tests__/ServerView.test.tsx` (modified) — added missing mock fields for new hook properties
