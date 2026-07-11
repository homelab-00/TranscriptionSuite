# Auto-Update Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dashboard update-checks default-on/weekly, show a Update/Dismiss toast on detection, and auto-download the release build that matches the running app's variant (critically, macOS metal-vs-standard DMG).

**Architecture:** Additive, brownfield changes over the existing `electron-updater` stack. A new pure helper (`appVariant.ts`) supplies variant identity; a new orchestrator (`macVariantUpdater.ts`) downloads/verifies/reveals the correct macOS DMG. `UpdateManager` gains an `EventEmitter` so `main.ts` can push a new `updates:updateAvailable` IPC event that a new renderer hook (`useUpdateToast`) turns into a `sonner` toast. Linux/Windows keep the existing electron-updater path unchanged. Per-version toast/banner dismissal uses a new `updates.dismissedAppVersion` config key (NOT the existing `updates.lastNotified`, which `maybeNotify` already owns).

**Tech Stack:** Electron 40 main process (TypeScript, ESM `.js` import specifiers), electron-store, `sonner` toasts, React 19 renderer, Vitest + @testing-library/react.

**Prerequisites for every test command below:**
- Run all Vitest commands from `dashboard/` under **Node 22** (`cd dashboard && nvm use`) — tests crash with `ERR_REQUIRE_ESM` on Node 20 (project memory: `gotcha_vitest_requires_node22`).
- Electron tests: `npx vitest run electron/__tests__/<file>`. Renderer tests: `npx vitest run <path>`.
- Before editing each existing symbol, run `gitnexus_impact({target, direction:"upstream"})` and report blast radius (CLAUDE.md). Run `npx gitnexus analyze` once, foreground, before starting (index is stale) — never concurrently from parallel agents (memory: `gotcha_gitnexus_augment_sigbus`).

---

## Design deviations from the spec (read first)

1. **Dismissal key.** Spec said reuse `updates.lastNotified.appLatest`. Planning found `maybeNotify()` (updateManager.ts:502-537) already writes that key on every OS-notification fire, which would make the banner vanish after the first check. So dismissal uses a **new** key `updates.dismissedAppVersion`. `lastNotified` is left untouched.
2. **Suppress-until-newer** is implemented as an **exact string mismatch** (`latest !== dismissedAppVersion`). Because `status.app.latest` always reflects the newest available version (computed via semver in `getStatus`), a newer release naturally has a different string and re-shows; no renderer-side semver dependency is needed.
3. **OS notification kept.** `maybeNotify` (native OS notification, gated on `app.showNotifications`) is left as-is; the in-app toast is an additive, independent surface.

---

## File Structure

| File | New/Mod | Responsibility |
|------|---------|----------------|
| `dashboard/electron/appVariant.ts` | new | Pure: detect running variant, resolve DMG asset name, build/validate asset URL, parse sha512 from `latest-mac.yml` |
| `dashboard/electron/__tests__/appVariant.test.ts` | new | Unit tests for the above |
| `dashboard/electron/mlxServerManager.ts` | mod | Reuse `appVariant` for metal detection / `_metalDmgName` (behavior-preserving) |
| `dashboard/electron/updateMigration.ts` | new | Pure one-shot force-on migration |
| `dashboard/electron/__tests__/updateMigration.test.ts` | new | Unit tests for the migration |
| `dashboard/electron/updateManager.ts` | mod | Extend `EventEmitter`; emit `updateAvailable` on fresh detection |
| `dashboard/electron/__tests__/updateManager.test.ts` | mod | Add emit tests |
| `dashboard/electron/macVariantUpdater.ts` | new | Download + verify + reveal the matching macOS DMG (dependency-injected) |
| `dashboard/electron/__tests__/macVariantUpdater.test.ts` | new | Unit tests (mocked fetch/fs/reveal) |
| `dashboard/electron/main.ts` | mod | Flip defaults + new keys; run migration; forward `updateAvailable`; route `updates:download` to Mac path |
| `dashboard/electron/preload.ts` | mod | Expose `updates.onUpdateAvailable`; add type decl |
| `dashboard/src/types/electron.d.ts` | mod | Types for `onUpdateAvailable` + payload |
| `dashboard/src/config/store.ts` | mod | Flip renderer DEFAULT_CONFIG |
| `dashboard/components/views/SettingsModal.tsx` | mod | Flip placeholder defaults |
| `dashboard/src/hooks/useUpdateToast.ts` | new | Fire the Update/Dismiss sonner toast on push event |
| `dashboard/src/hooks/__tests__/useUpdateToast.test.tsx` | new | Unit tests for the hook |
| `dashboard/App.tsx` | mod | Mount `useUpdateToast()` |
| `dashboard/components/ui/UpdateBanner.tsx` | mod | Respect `updates.dismissedAppVersion` |
| `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` | mod | Thread new arg through call sites + new cases |

---

## Task 1: `appVariant.ts` — variant identity helpers (pure)

**Files:**
- Create: `dashboard/electron/appVariant.ts`
- Test: `dashboard/electron/__tests__/appVariant.test.ts`

- [ ] **Step 1: Write the failing test**

Create `dashboard/electron/__tests__/appVariant.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  resolveMacDmgAssetName,
  buildAssetDownloadUrl,
  isTrustedAssetUrl,
  sha512FromLatestYml,
} from '../appVariant.js';

describe('resolveMacDmgAssetName', () => {
  it('names the metal DMG for the metal variant', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-metal')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('names the standard arm64 DMG', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-standard-arm64')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac.dmg',
    );
  });
  it('names the standard x64 DMG', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-standard-x64')).toBe(
      'TranscriptionSuite-1.3.7-x64-mac.dmg',
    );
  });
  it('strips a leading v from the version', () => {
    expect(resolveMacDmgAssetName('v1.3.7', 'mac-metal')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('throws for non-mac variants', () => {
    expect(() => resolveMacDmgAssetName('1.3.7', 'linux')).toThrow();
  });
});

describe('buildAssetDownloadUrl', () => {
  it('builds a tagged release asset URL', () => {
    expect(
      buildAssetDownloadUrl('1.3.7', 'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg'),
    ).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('strips a leading v from version', () => {
    expect(buildAssetDownloadUrl('v1.3.7', 'latest-mac.yml')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/latest-mac.yml',
    );
  });
});

describe('isTrustedAssetUrl', () => {
  it('accepts a well-formed asset URL', () => {
    expect(
      isTrustedAssetUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/TranscriptionSuite-1.3.7-arm64-mac.dmg',
      ),
    ).toBe(true);
  });
  it('rejects a non-github origin', () => {
    expect(
      isTrustedAssetUrl('https://evil.example/homelab-00/TranscriptionSuite/releases/download/v1.3.7/x.dmg'),
    ).toBe(false);
  });
  it('rejects userinfo bypass', () => {
    expect(
      isTrustedAssetUrl('https://github.com@evil.example/homelab-00/TranscriptionSuite/releases/download/v1.3.7/x.dmg'),
    ).toBe(false);
  });
  it('rejects percent-encoded path traversal', () => {
    expect(
      isTrustedAssetUrl('https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/%2e%2e/secret'),
    ).toBe(false);
  });
  it('rejects the wrong repo', () => {
    expect(
      isTrustedAssetUrl('https://github.com/homelab-00/OtherRepo/releases/download/v1.3.7/x.dmg'),
    ).toBe(false);
  });
});

describe('sha512FromLatestYml', () => {
  const yml = [
    'version: 1.3.7',
    'files:',
    '  - url: TranscriptionSuite-1.3.7-arm64-mac.dmg',
    '    sha512: AAAAsha512forArm64==',
    '    size: 111',
    '  - url: TranscriptionSuite-1.3.7-x64-mac.dmg',
    '    sha512: BBBBsha512forX64==',
    '    size: 222',
    'path: TranscriptionSuite-1.3.7-arm64-mac.dmg',
    'sha512: AAAAsha512forArm64==',
  ].join('\n');
  it('returns the sha512 for the named asset', () => {
    expect(sha512FromLatestYml(yml, 'TranscriptionSuite-1.3.7-x64-mac.dmg')).toBe(
      'BBBBsha512forX64==',
    );
  });
  it('returns null when the asset is absent', () => {
    expect(sha512FromLatestYml(yml, 'not-present.dmg')).toBeNull();
  });
  it('returns null on unparsable yaml', () => {
    expect(sha512FromLatestYml(': : not yaml : :', 'x.dmg')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npx vitest run electron/__tests__/appVariant.test.ts`
Expected: FAIL — `Cannot find module '../appVariant.js'`.

- [ ] **Step 3: Write the implementation**

Create `dashboard/electron/appVariant.ts`:

```ts
/**
 * appVariant — pure helpers identifying which build of the dashboard is
 * running and mapping that to the matching GitHub release asset.
 *
 * The desktop app varies only by platform, except on macOS where a "metal"
 * DMG (bundles the MLX Python backend under resources/backend) is shipped
 * alongside the standard DMG. The updater must fetch the SAME variant.
 *
 * Detection mirrors the probe previously embedded in mlxServerManager
 * (packaged app + resources/backend existence). Kept side-effect-light and
 * Electron-decoupled (detectAppVariant takes its inputs) so it is unit-testable.
 */
import * as path from 'node:path';
import * as fs from 'node:fs';
import yaml from 'js-yaml';

export type AppVariant =
  | 'mac-metal'
  | 'mac-standard-arm64'
  | 'mac-standard-x64'
  | 'linux'
  | 'windows';

const PRODUCT_NAME = 'TranscriptionSuite';
const REPO_PATH = 'homelab-00/TranscriptionSuite';

export interface VariantProbe {
  platform: NodeJS.Platform;
  arch: string;
  isPackaged: boolean;
  resourcesPath: string | undefined;
}

/**
 * Determine the running app variant. On macOS, "metal" is inferred from the
 * bundled backend directory (resources/backend) exactly like mlxServerManager's
 * diagnostic. In dev (isPackaged=false) resourcesPath points at Electron's own
 * resources, so metal is never claimed unless packaged.
 */
export function detectAppVariant(probe: VariantProbe): AppVariant {
  if (probe.platform === 'win32') return 'windows';
  if (probe.platform === 'linux') return 'linux';
  // darwin
  const hasBundledBackend =
    probe.isPackaged &&
    !!probe.resourcesPath &&
    fs.existsSync(path.join(probe.resourcesPath, 'backend'));
  if (hasBundledBackend && probe.arch === 'arm64') return 'mac-metal';
  return probe.arch === 'arm64' ? 'mac-standard-arm64' : 'mac-standard-x64';
}

function stripV(version: string): string {
  return version.replace(/^v/i, '');
}

/** Resolve the release DMG filename for a macOS variant + version. */
export function resolveMacDmgAssetName(version: string, variant: AppVariant): string {
  const v = stripV(version);
  switch (variant) {
    case 'mac-metal':
      return `${PRODUCT_NAME}-${v}-arm64-mac-metal.dmg`;
    case 'mac-standard-arm64':
      return `${PRODUCT_NAME}-${v}-arm64-mac.dmg`;
    case 'mac-standard-x64':
      return `${PRODUCT_NAME}-${v}-x64-mac.dmg`;
    default:
      throw new Error(`resolveMacDmgAssetName: not a macOS variant: ${variant}`);
  }
}

/** Construct the GitHub release asset download URL. */
export function buildAssetDownloadUrl(version: string, assetName: string): string {
  const v = stripV(version);
  return `https://github.com/${REPO_PATH}/releases/download/v${v}/${assetName}`;
}

const ASSET_PATH_RE =
  /^\/homelab-00\/TranscriptionSuite\/releases\/download\/v[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;

/**
 * Allow-list guard for asset URLs, mirroring releaseUrl.isTrustedReleaseUrl:
 * origin must be github.com, no userinfo, no percent-encoded path segments,
 * and the path must be a release-download under this repo.
 */
export function isTrustedAssetUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    if (parsed.origin !== 'https://github.com') return false;
    if (parsed.username !== '' || parsed.password !== '') return false;
    if (parsed.pathname.includes('%')) return false;
    return ASSET_PATH_RE.test(parsed.pathname);
  } catch {
    return false;
  }
}

interface LatestYml {
  files?: Array<{ url?: string; sha512?: string }>;
}

/**
 * Extract the base64 sha512 for a given asset filename from a parsed
 * electron-builder latest-mac.yml. Returns null on parse error or miss
 * (caller treats a null as "verification unavailable" and proceeds).
 */
export function sha512FromLatestYml(ymlText: string, assetName: string): string | null {
  try {
    const doc = yaml.load(ymlText) as LatestYml | null;
    const files = doc?.files ?? [];
    const entry = files.find((f) => f.url === assetName);
    return entry?.sha512 ?? null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npx vitest run electron/__tests__/appVariant.test.ts`
Expected: PASS (all cases green).

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/appVariant.ts dashboard/electron/__tests__/appVariant.test.ts
git commit -m "feat(update): add appVariant helpers for variant-matched release assets"
```

---

## Task 2: Refactor `mlxServerManager` metal detection onto `appVariant`

Behavior-preserving: replace the inline `_metalDmgName()` string build with `resolveMacDmgAssetName`, keeping the existing fallback for an unresolvable version.

**Files:**
- Modify: `dashboard/electron/mlxServerManager.ts:518-533`
- Test: `dashboard/electron/__tests__/mlxServerManager.test.ts` (must stay green)

- [ ] **Step 1: Run impact analysis**

Run: `gitnexus_impact({target: "_metalDmgName", direction: "upstream"})`
Report the blast radius. Expected: internal to `mlxServerManager` (only referenced by the diagnostic message builder). Proceed only if not HIGH/CRITICAL.

- [ ] **Step 2: Run the existing test to establish the green baseline**

Run: `cd dashboard && npx vitest run electron/__tests__/mlxServerManager.test.ts`
Expected: PASS.

- [ ] **Step 3: Modify `_metalDmgName` to delegate**

In `dashboard/electron/mlxServerManager.ts`, add to the imports near the top (mirror existing `import * as path` style):

```ts
import { resolveMacDmgAssetName } from './appVariant.js';
```

Replace the body of `_metalDmgName()` (currently at lines 525-533):

```ts
  private _metalDmgName(): string {
    let version = '<version>';
    try {
      version = app.getVersion();
    } catch {
      // Keep the actionable "-metal" suffix even without a resolvable version.
    }
    return `TranscriptionSuite-${version}-arm64-mac-metal.dmg`;
  }
```

with:

```ts
  private _metalDmgName(): string {
    try {
      return resolveMacDmgAssetName(app.getVersion(), 'mac-metal');
    } catch {
      // app.getVersion() can throw on the damaged bundle this diagnostic
      // exists to report; keep the actionable "-metal" suffix regardless.
      return 'TranscriptionSuite-<version>-arm64-mac-metal.dmg';
    }
  }
```

- [ ] **Step 4: Run the test to verify it still passes**

Run: `cd dashboard && npx vitest run electron/__tests__/mlxServerManager.test.ts`
Expected: PASS (no behavior change).

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/mlxServerManager.ts
git commit -m "refactor(update): derive metal DMG name via appVariant helper"
```

---

## Task 3: Requirement (i) — default-on/weekly + force-on migration

**Files:**
- Create: `dashboard/electron/updateMigration.ts`
- Test: `dashboard/electron/__tests__/updateMigration.test.ts`
- Modify: `dashboard/electron/main.ts` (defaults block ~490-515; boot ~2254)
- Modify: `dashboard/src/config/store.ts:134-135`
- Modify: `dashboard/components/views/SettingsModal.tsx:196-197`

- [ ] **Step 1: Write the failing migration test**

Create `dashboard/electron/__tests__/updateMigration.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { forceEnableWeeklyUpdatesOnce } from '../updateMigration.js';

function makeStore(initial: Record<string, unknown> = {}) {
  const data = new Map<string, unknown>(Object.entries(initial));
  return {
    get: (k: string) => data.get(k),
    set: (k: string, v: unknown) => {
      data.set(k, v);
    },
    _data: data,
  };
}

describe('forceEnableWeeklyUpdatesOnce', () => {
  it('force-enables weekly checks on first run and sets the flag', () => {
    const store = makeStore({ 'app.updateChecksEnabled': false, 'app.updateCheckIntervalMode': '24h' });
    const ran = forceEnableWeeklyUpdatesOnce(store);
    expect(ran).toBe(true);
    expect(store._data.get('app.updateChecksEnabled')).toBe(true);
    expect(store._data.get('app.updateCheckIntervalMode')).toBe('7d');
    expect(store._data.get('updates.forceOnMigrationDone')).toBe(true);
  });

  it('overrides a user who had explicitly disabled checks (force-on semantics)', () => {
    const store = makeStore({ 'app.updateChecksEnabled': false });
    forceEnableWeeklyUpdatesOnce(store);
    expect(store._data.get('app.updateChecksEnabled')).toBe(true);
  });

  it('is a no-op after it has run once (user choice persists thereafter)', () => {
    const store = makeStore({ 'updates.forceOnMigrationDone': true, 'app.updateChecksEnabled': false });
    const ran = forceEnableWeeklyUpdatesOnce(store);
    expect(ran).toBe(false);
    // The migration must NOT re-enable a user who disabled it post-migration.
    expect(store._data.get('app.updateChecksEnabled')).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npx vitest run electron/__tests__/updateMigration.test.ts`
Expected: FAIL — `Cannot find module '../updateMigration.js'`.

- [ ] **Step 3: Write the migration**

Create `dashboard/electron/updateMigration.ts`:

```ts
/**
 * updateMigration — one-shot "force-on" migration for the default-on weekly
 * update-checks rollout. electron-store defaults only fill ABSENT keys, so a
 * user who explicitly disabled checks keeps that value; the product decision
 * is to force weekly checks ON for everyone exactly once, after which the
 * user's own toggle is respected permanently. The `forceOnMigrationDone`
 * boolean sentinel is required because config.get never returns undefined for
 * a defaulted key, so key-absence is not a usable trigger.
 */
export interface MigratableStore {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
}

/**
 * Returns true if the migration ran this call, false if it was already done.
 */
export function forceEnableWeeklyUpdatesOnce(store: MigratableStore): boolean {
  if (store.get('updates.forceOnMigrationDone') === true) return false;
  store.set('app.updateChecksEnabled', true);
  store.set('app.updateCheckIntervalMode', '7d');
  store.set('updates.forceOnMigrationDone', true);
  return true;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npx vitest run electron/__tests__/updateMigration.test.ts`
Expected: PASS.

- [ ] **Step 5: Flip the electron-store defaults and add the new keys**

In `dashboard/electron/main.ts`, in the `new Store({ defaults: {...} })` block, change lines 490-491 and add two keys after line 515. Before:

```ts
    'app.updateChecksEnabled': false,
    'app.updateCheckIntervalMode': '24h',
    'app.updateCheckCustomHours': 24,
```

After:

```ts
    'app.updateChecksEnabled': true,
    'app.updateCheckIntervalMode': '7d',
    'app.updateCheckCustomHours': 24,
```

And, immediately after the existing `'updates.bannerSnoozedUntil': 0,` line (515), add:

```ts
    'updates.forceOnMigrationDone': false,
    'updates.dismissedAppVersion': '',
```

- [ ] **Step 6: Wire the migration into boot (before `updateManager.start()`)**

In `dashboard/electron/main.ts`, add to the update-manager imports (near line 34):

```ts
import { forceEnableWeeklyUpdatesOnce } from './updateMigration.js';
```

Locate `updateManager.start();` (line 2254) and insert immediately before it:

```ts
  // One-shot force-on migration for the default-on weekly rollout. Runs once;
  // afterward the user's own enable/disable choice persists.
  if (forceEnableWeeklyUpdatesOnce(store)) {
    console.log('[UpdateMigration] forced weekly update checks ON (one-time).');
  }
  updateManager.start();
```

- [ ] **Step 7: Flip the renderer DEFAULT_CONFIG**

In `dashboard/src/config/store.ts`, change lines 134-135. Before:

```ts
    updateChecksEnabled: false,
    updateCheckIntervalMode: '24h',
```

After:

```ts
    updateChecksEnabled: true,
    updateCheckIntervalMode: '7d',
```

- [ ] **Step 8: Flip the SettingsModal placeholder defaults**

In `dashboard/components/views/SettingsModal.tsx`, change lines 196-197. Before:

```ts
    updateChecksEnabled: false,
    updateCheckIntervalMode: '24h',
```

After:

```ts
    updateChecksEnabled: true,
    updateCheckIntervalMode: '7d',
```

- [ ] **Step 9: Typecheck + commit**

Run: `cd dashboard && npx tsc -p electron/tsconfig.json --noEmit && npx tsc --noEmit`
Expected: no errors.

```bash
git add dashboard/electron/updateMigration.ts dashboard/electron/__tests__/updateMigration.test.ts dashboard/electron/main.ts dashboard/src/config/store.ts dashboard/components/views/SettingsModal.tsx
git commit -m "feat(update): default-on weekly checks + one-shot force-on migration"
```

---

## Task 4: `UpdateManager` emits `updateAvailable` on fresh detection

**Files:**
- Modify: `dashboard/electron/updateManager.ts` (class decl ~162; ctor ~168; check tail ~261)
- Test: `dashboard/electron/__tests__/updateManager.test.ts`

- [ ] **Step 1: Run impact analysis**

Run: `gitnexus_impact({target: "UpdateManager", direction: "upstream"})`
Report blast radius (expected: `main.ts` construction + tests). Do not proceed on HIGH/CRITICAL without warning the user.

- [ ] **Step 2: Write the failing test**

Add to `dashboard/electron/__tests__/updateManager.test.ts` (follow the file's existing store-mock + `vi.mock('electron')` conventions; if it constructs `new UpdateManager(fakeStore)`, reuse that harness). Add a new `describe`:

```ts
import { EventEmitter } from 'node:events';

describe('UpdateManager updateAvailable event', () => {
  it('emits updateAvailable when a check finds a newer app version', async () => {
    // Arrange: build a manager whose check() resolves an app update.
    // Reuse the file's existing helper to construct a manager whose
    // performCheck path yields app.updateAvailable=true, latest='1.4.0'.
    const { manager } = buildManagerWithAppUpdate('1.4.0', 'Release notes here');
    const events: Array<{ version: string; releaseNotes: string | null }> = [];
    (manager as unknown as EventEmitter).on('updateAvailable', (p) => events.push(p));

    await manager.check();

    expect(events).toHaveLength(1);
    expect(events[0].version).toBe('1.4.0');
    expect(events[0].releaseNotes).toBe('Release notes here');
  });

  it('does not emit when no app update is available', async () => {
    const { manager } = buildManagerWithoutAppUpdate();
    const events: unknown[] = [];
    (manager as unknown as EventEmitter).on('updateAvailable', (p) => events.push(p));

    await manager.check();

    expect(events).toHaveLength(0);
  });
});
```

> **Implementation note for the engineer:** `updateManager.test.ts` already mocks the network/version resolution used by `check()`. Add the two small factory helpers `buildManagerWithAppUpdate(latest, notes)` and `buildManagerWithoutAppUpdate()` next to the existing setup, reusing whatever mock the file uses to make `check()` resolve an `app` status with `updateAvailable`/`latest`/`releaseNotes`. If the file already exercises `check()` returning an available update (it tests `maybeNotify`/status), copy that exact arrangement.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd dashboard && npx vitest run electron/__tests__/updateManager.test.ts`
Expected: FAIL — `manager.on is not a function` (UpdateManager is not yet an EventEmitter) or no event emitted.

- [ ] **Step 4: Make `UpdateManager` an EventEmitter and emit**

In `dashboard/electron/updateManager.ts`, add the import near the top:

```ts
import { EventEmitter } from 'node:events';
```

Change the class declaration (line 162) from:

```ts
export class UpdateManager {
  private store: AnyStore;
```

to:

```ts
export class UpdateManager extends EventEmitter {
  private store: AnyStore;
```

Change the constructor (lines 168-170) from:

```ts
  constructor(store: AnyStore) {
    this.store = store;
  }
```

to:

```ts
  constructor(store: AnyStore) {
    super();
    this.store = store;
  }
```

In `check()`, immediately after the `this.maybeNotify(status);` line (line 261), add:

```ts
    // Push a one-shot signal so the renderer can raise the update toast.
    // Fires whenever the completed check reports an available app update;
    // per-version de-dup lives in the renderer (updates.dismissedAppVersion)
    // and sonner's stable toast id, so repeat fires are harmless.
    if (status.app.updateAvailable && status.app.latest) {
      this.emit('updateAvailable', {
        version: status.app.latest,
        releaseNotes: status.app.releaseNotes ?? null,
      });
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd dashboard && npx vitest run electron/__tests__/updateManager.test.ts`
Expected: PASS (including the file's pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add dashboard/electron/updateManager.ts dashboard/electron/__tests__/updateManager.test.ts
git commit -m "feat(update): emit updateAvailable event from UpdateManager on fresh detection"
```

---

## Task 5: `macVariantUpdater.ts` — download + verify + reveal the matching DMG

Dependency-injected so it unit-tests without Electron. Reports progress via the `InstallerStatus` shape so the existing banner UI renders it.

**Files:**
- Create: `dashboard/electron/macVariantUpdater.ts`
- Test: `dashboard/electron/__tests__/macVariantUpdater.test.ts`

- [ ] **Step 1: Write the failing test**

Create `dashboard/electron/__tests__/macVariantUpdater.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as os from 'node:os';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { downloadMacVariantDmg } from '../macVariantUpdater.js';
import type { InstallerStatus } from '../updateManager.js';

const DMG_BYTES = Buffer.from('fake-dmg-contents');
const DMG_SHA512 = createHash('sha512').update(DMG_BYTES).digest('base64');

let tmpDir: string;
beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'macvariant-'));
});
afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function bodyFrom(buf: Buffer): AsyncIterable<Uint8Array> {
  return (async function* () {
    yield new Uint8Array(buf);
  })();
}

function fakeFetch(map: Record<string, { ok: boolean; body?: Buffer; text?: string }>) {
  return vi.fn(async (url: string) => {
    const hit = map[url];
    if (!hit) return { ok: false, status: 404, headers: new Map(), body: null } as unknown as Response;
    return {
      ok: hit.ok,
      status: hit.ok ? 200 : 500,
      headers: { get: (k: string) => (k === 'content-length' ? String(hit.body?.length ?? 0) : null) },
      body: hit.body ? bodyFrom(hit.body) : null,
      text: async () => hit.text ?? '',
    } as unknown as Response;
  });
}

describe('downloadMacVariantDmg', () => {
  it('downloads, verifies a standard DMG against latest-mac.yml, and reveals it', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const ymlUrl = 'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/latest-mac.yml';
    const yml = `version: 1.4.0\nfiles:\n  - url: ${asset}\n    sha512: ${DMG_SHA512}\n    size: ${DMG_BYTES.length}\npath: ${asset}\nsha512: ${DMG_SHA512}\n`;
    const statuses: InstallerStatus[] = [];
    const revealed: string[] = [];

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: (s) => statuses.push(s),
      revealFile: async (p) => {
        revealed.push(p);
      },
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({
        [dmgUrl]: { ok: true, body: DMG_BYTES },
        [ymlUrl]: { ok: true, text: yml },
      }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(true);
    expect(revealed).toHaveLength(1);
    expect(path.basename(revealed[0])).toBe(asset);
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(true);
    expect(statuses.some((s) => s.state === 'downloading')).toBe(true);
  });

  it('deletes the file and errors on sha512 mismatch (standard variant)', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const ymlUrl = 'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/latest-mac.yml';
    const yml = `version: 1.4.0\nfiles:\n  - url: ${asset}\n    sha512: WRONGsha==\n    size: ${DMG_BYTES.length}\n`;

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({
        [dmgUrl]: { ok: true, body: DMG_BYTES },
        [ymlUrl]: { ok: true, text: yml },
      }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('checksum-mismatch');
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(false);
  });

  it('skips verification for the metal variant (no feed) and still reveals', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac-metal.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const revealed: string[] = [];

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-metal',
      onStatus: () => {},
      revealFile: async (p) => {
        revealed.push(p);
      },
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({ [dmgUrl]: { ok: true, body: DMG_BYTES } }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(true);
    expect(revealed).toHaveLength(1);
  });

  it('returns a manual-download fallback when the download request fails', async () => {
    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({}) as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe('manual-download-required');
      expect(result.downloadUrl).toContain('/releases/');
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npx vitest run electron/__tests__/macVariantUpdater.test.ts`
Expected: FAIL — `Cannot find module '../macVariantUpdater.js'`.

- [ ] **Step 3: Write the implementation**

Create `dashboard/electron/macVariantUpdater.ts`:

```ts
/**
 * macVariantUpdater — download-and-reveal update path for macOS.
 *
 * macOS builds are unsigned (electron-updater cannot silently install), and the
 * Metal DMG is published outside electron-builder (no latest-mac.yml feed). So
 * on macOS the "Update" action downloads the release DMG that matches the
 * running variant (metal <-> standard), verifies STANDARD variants against
 * latest-mac.yml (best-effort; skipped for metal), and reveals it in Finder for
 * a manual drag-install. No quitAndInstall.
 *
 * Dependency-injected (fetch/reveal/downloads-dir) for unit-testability.
 */
import * as path from 'node:path';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import type { InstallerStatus } from './updateManager.js';
import {
  type AppVariant,
  resolveMacDmgAssetName,
  buildAssetDownloadUrl,
  isTrustedAssetUrl,
  sha512FromLatestYml,
} from './appVariant.js';
import { buildReleaseUrl } from './releaseUrl.js';

export interface MacVariantDeps {
  variant: AppVariant;
  onStatus: (status: InstallerStatus) => void;
  revealFile: (filePath: string) => Promise<void>;
  getDownloadsDir: () => string;
  fetchImpl?: typeof fetch;
}

export type MacVariantResult =
  | { ok: true; path: string }
  | { ok: false; reason: 'checksum-mismatch' }
  | { ok: false; reason: 'manual-download-required'; downloadUrl: string };

/**
 * Download the matching DMG for `targetVersion`, verify (standard only),
 * reveal it, and report progress via onStatus. On any network/validation
 * failure returns a manual-download fallback carrying the release-page URL.
 */
export async function downloadMacVariantDmg(
  targetVersion: string,
  deps: MacVariantDeps,
): Promise<MacVariantResult> {
  const doFetch = deps.fetchImpl ?? fetch;
  const assetName = resolveMacDmgAssetName(targetVersion, deps.variant);
  const url = buildAssetDownloadUrl(targetVersion, assetName);
  const releaseUrl = buildReleaseUrl(targetVersion);

  if (!isTrustedAssetUrl(url)) {
    console.warn('[macVariantUpdater] refusing untrusted asset url:', url);
    deps.onStatus({ state: 'error', message: 'Untrusted download URL' });
    return { ok: false, reason: 'manual-download-required', downloadUrl: releaseUrl };
  }

  const destPath = path.join(deps.getDownloadsDir(), assetName);

  try {
    deps.onStatus({
      state: 'downloading',
      version: targetVersion,
      percent: 0,
      bytesPerSecond: 0,
      transferred: 0,
      total: 0,
    });

    const res = await doFetch(url);
    if (!res.ok || !res.body) {
      throw new Error(`download failed: HTTP ${res.status}`);
    }
    const total = Number(res.headers.get('content-length') ?? 0);
    const hash = createHash('sha512');
    let transferred = 0;

    // res.body is a web ReadableStream in Node/Electron; it is async-iterable.
    const source = (async function* () {
      for await (const chunk of res.body as AsyncIterable<Uint8Array>) {
        const buf = Buffer.from(chunk);
        transferred += buf.length;
        hash.update(buf);
        deps.onStatus({
          state: 'downloading',
          version: targetVersion,
          percent: total > 0 ? (transferred / total) * 100 : 0,
          bytesPerSecond: 0,
          transferred,
          total,
        });
        yield buf;
      }
    })();

    await pipeline(source, fs.createWriteStream(destPath));
    const actualSha512 = hash.digest('base64');

    // Verify STANDARD variants against latest-mac.yml (best-effort). Metal has
    // no feed entry, so verification is skipped (user decision).
    if (deps.variant !== 'mac-metal') {
      deps.onStatus({ state: 'verifying', version: targetVersion });
      const expected = await fetchExpectedSha512(doFetch, targetVersion, assetName);
      if (expected && expected !== actualSha512) {
        fs.rmSync(destPath, { force: true });
        console.error(`[macVariantUpdater] sha512 mismatch for ${assetName}`);
        deps.onStatus({ state: 'error', message: 'Checksum verification failed' });
        return { ok: false, reason: 'checksum-mismatch' };
      }
      if (!expected) {
        console.warn(
          `[macVariantUpdater] no sha512 in latest-mac.yml for ${assetName}; proceeding unverified`,
        );
      }
    }

    await deps.revealFile(destPath);
    deps.onStatus({ state: 'idle' });
    return { ok: true, path: destPath };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[macVariantUpdater] download failed:', message);
    fs.rmSync(destPath, { force: true });
    deps.onStatus({ state: 'error', message });
    return { ok: false, reason: 'manual-download-required', downloadUrl: releaseUrl };
  }
}

async function fetchExpectedSha512(
  doFetch: typeof fetch,
  version: string,
  assetName: string,
): Promise<string | null> {
  try {
    const ymlUrl = buildAssetDownloadUrl(version, 'latest-mac.yml');
    if (!isTrustedAssetUrl(ymlUrl)) return null;
    const res = await doFetch(ymlUrl);
    if (!res.ok) return null;
    return sha512FromLatestYml(await res.text(), assetName);
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npx vitest run electron/__tests__/macVariantUpdater.test.ts`
Expected: PASS (all four cases).

- [ ] **Step 5: Commit**

```bash
git add dashboard/electron/macVariantUpdater.ts dashboard/electron/__tests__/macVariantUpdater.test.ts
git commit -m "feat(update): macOS variant-matched DMG download/verify/reveal path"
```

---

## Task 6: Wire `main.ts` — forward push + route macOS download

Glue task (main.ts is integration wiring; the testable logic lives in Tasks 4/5). Verification is typecheck + the already-green module tests.

**Files:**
- Modify: `dashboard/electron/main.ts` (installer-status forward ~686-692; updates:download ~1550-1567)

- [ ] **Step 1: Run impact analysis on the download handler**

Run: `gitnexus_impact({target: "resolveStrategyForUpdater", direction: "upstream"})` and note callers (`updates:download`, `updateInstaller` platformStrategy). Confirm not HIGH/CRITICAL.

- [ ] **Step 2: Add imports**

In `dashboard/electron/main.ts`, near the update imports (line 34-35), add:

```ts
import { detectAppVariant } from './appVariant.js';
import { downloadMacVariantDmg } from './macVariantUpdater.js';
```

- [ ] **Step 3: Extract a broadcast helper and forward the new event**

Replace the existing installer-status forwarder (lines 686-692):

```ts
updateInstaller.on('status', (status) => {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('updates:installerStatus', status);
    }
  }
});
```

with:

```ts
function broadcastInstallerStatus(status: Parameters<typeof updateInstaller.getStatus>[never] extends never
  ? import('./updateManager.js').InstallerStatus
  : never): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('updates:installerStatus', status);
    }
  }
}

updateInstaller.on('status', (status) => broadcastInstallerStatus(status));

// Push a one-shot update-available signal to every window; the renderer's
// useUpdateToast hook turns it into the Update/Dismiss toast.
updateManager.on('updateAvailable', (payload) => {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('updates:updateAvailable', payload);
    }
  }
});
```

> If the `Parameters<...>` type gymnastics above trips the compiler, simplify by importing the type directly: `import type { InstallerStatus } from './updateManager.js';` at the top and typing the helper as `function broadcastInstallerStatus(status: InstallerStatus): void`.

- [ ] **Step 4: Route the macOS branch in `updates:download`**

In the `updates:download` handler, replace the manual-download branch (lines 1565-1567):

```ts
  if (strategy.strategy === 'manual-download') {
    return updateInstaller.startDownload();
  }
```

with:

```ts
  if (strategy.strategy === 'manual-download') {
    // macOS: download the variant-matched DMG and reveal it (unsigned → no
    // silent install). Linux read-only-AppImage keeps the existing
    // manual-download-required broadcast (banner routes to the release page).
    if (process.platform === 'darwin' && strategy.version) {
      const result = await downloadMacVariantDmg(strategy.version, {
        variant: detectAppVariant({
          platform: process.platform,
          arch: process.arch,
          isPackaged: app.isPackaged,
          resourcesPath: process.resourcesPath,
        }),
        onStatus: (status) => broadcastInstallerStatus(status),
        revealFile: async (p) => {
          shell.showItemInFolder(p);
          await shell.openPath(p);
        },
        getDownloadsDir: () => app.getPath('downloads'),
      });
      if (result.ok) return { ok: true as const };
      if (result.reason === 'checksum-mismatch') {
        return { ok: false as const, reason: 'error' as const, message: 'Checksum verification failed' };
      }
      return {
        ok: false as const,
        reason: 'manual-download-required' as const,
        downloadUrl: result.downloadUrl,
      };
    }
    return updateInstaller.startDownload();
  }
```

- [ ] **Step 5: Typecheck + re-run the module tests**

Run: `cd dashboard && npx tsc -p electron/tsconfig.json --noEmit`
Expected: no errors.
Run: `cd dashboard && npx vitest run electron/__tests__/updateManager.test.ts electron/__tests__/macVariantUpdater.test.ts electron/__tests__/appVariant.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/electron/main.ts
git commit -m "feat(update): forward updateAvailable push and route macOS variant download"
```

---

## Task 7: Expose `onUpdateAvailable` in preload + types

**Files:**
- Modify: `dashboard/electron/preload.ts` (runtime object ~698; type block ~332)
- Modify: `dashboard/src/types/electron.d.ts` (updates block)

- [ ] **Step 1: Add the runtime subscription in preload**

In `dashboard/electron/preload.ts`, inside the runtime `updates: { ... }` object, after the `onInstallReady` member (ends line 698), add:

```ts
    onUpdateAvailable: (
      callback: (payload: { version: string; releaseNotes: string | null }) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        payload: { version: string; releaseNotes: string | null },
      ) => callback(payload);
      ipcRenderer.on('updates:updateAvailable', handler);
      return () => ipcRenderer.removeListener('updates:updateAvailable', handler);
    },
```

- [ ] **Step 2: Add the type in preload's interface block**

In `dashboard/electron/preload.ts`, in the `updates: { ... }` **type** block, after the `onInstallReady` declaration (line 332), add:

```ts
    /** Fires when a completed check detects a newer app version. */
    onUpdateAvailable: (
      callback: (payload: { version: string; releaseNotes: string | null }) => void,
    ) => () => void;
```

- [ ] **Step 3: Add the type in `electron.d.ts`**

In `dashboard/src/types/electron.d.ts`, in the `updates` interface (after the `onInstallReady` member), add the identical declaration:

```ts
    /** Fires when a completed check detects a newer app version. */
    onUpdateAvailable: (
      callback: (payload: { version: string; releaseNotes: string | null }) => void,
    ) => () => void;
```

- [ ] **Step 4: Typecheck + commit**

Run: `cd dashboard && npx tsc -p electron/tsconfig.json --noEmit && npx tsc --noEmit`
Expected: no errors.

```bash
git add dashboard/electron/preload.ts dashboard/src/types/electron.d.ts
git commit -m "feat(update): expose updates.onUpdateAvailable over the preload bridge"
```

---

## Task 8: `useUpdateToast` hook + mount

**Files:**
- Create: `dashboard/src/hooks/useUpdateToast.ts`
- Test: `dashboard/src/hooks/__tests__/useUpdateToast.test.tsx`
- Modify: `dashboard/App.tsx` (import block ~20-37; body ~116)

- [ ] **Step 1: Write the failing test**

Create `dashboard/src/hooks/__tests__/useUpdateToast.test.tsx` (mirrors `useWatcherFilesBridge.test.tsx` + the UpdateBanner sonner/config mock conventions):

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// --- sonner mock: capture the options so we can invoke action/cancel ---
const toastCalls: Array<{ message: string; options: any }> = [];
const dismissed: string[] = [];
vi.mock('sonner', () => ({
  toast: Object.assign(
    (message: string, options: any) => {
      toastCalls.push({ message, options });
      return options?.id ?? 'toast-id';
    },
    { dismiss: (id: string) => dismissed.push(id) },
  ),
}));

// --- config store mock ---
const configStore = new Map<string, unknown>();
const setConfigMock = vi.fn(async (k: string, v: unknown) => {
  configStore.set(k, v);
});
const getConfigMock = vi.fn(async (k: string) => configStore.get(k));
vi.mock('../../config/store', () => ({
  getConfig: (k: string) => getConfigMock(k),
  setConfig: (k: string, v: unknown) => setConfigMock(k, v),
}));

import { useUpdateToast } from '../useUpdateToast';

let listener: ((p: { version: string; releaseNotes: string | null }) => void) | null = null;
const unsubscribe = vi.fn();
const downloadMock = vi.fn(async () => ({ ok: true }));

function installStub() {
  (window as any).electronAPI = {
    updates: {
      onUpdateAvailable: vi.fn((cb: any) => {
        listener = cb;
        return unsubscribe;
      }),
      download: downloadMock,
      openReleasePage: vi.fn(async () => ({ ok: true })),
    },
  };
}

beforeEach(() => {
  toastCalls.length = 0;
  dismissed.length = 0;
  configStore.clear();
  listener = null;
  vi.clearAllMocks();
  installStub();
});
afterEach(() => {
  delete (window as any).electronAPI;
});

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('useUpdateToast', () => {
  it('subscribes on mount and unsubscribes on unmount', () => {
    const { unmount } = renderHook(() => useUpdateToast());
    expect((window as any).electronAPI.updates.onUpdateAvailable).toHaveBeenCalledTimes(1);
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('shows an Update/Dismiss toast when a new version is pushed', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => {
      listener?.({ version: '1.4.0', releaseNotes: null });
    });
    await flush();
    expect(toastCalls).toHaveLength(1);
    expect(toastCalls[0].options.action.label).toBe('Update');
    expect(toastCalls[0].options.cancel.label).toBe('Dismiss');
    expect(toastCalls[0].options.duration).toBe(Infinity);
  });

  it('Update triggers download()', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.action.onClick();
    });
    expect(downloadMock).toHaveBeenCalledTimes(1);
  });

  it('Dismiss persists updates.dismissedAppVersion', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.cancel.onClick();
    });
    expect(setConfigMock).toHaveBeenCalledWith('updates.dismissedAppVersion', '1.4.0');
  });

  it('does not re-show a version the user already dismissed', async () => {
    configStore.set('updates.dismissedAppVersion', '1.4.0');
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    expect(toastCalls).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npx vitest run src/hooks/__tests__/useUpdateToast.test.tsx`
Expected: FAIL — `Cannot find module '../useUpdateToast'`.

- [ ] **Step 3: Write the hook**

Create `dashboard/src/hooks/useUpdateToast.ts`:

```ts
import { useEffect } from 'react';
import { toast } from 'sonner';
import { getConfig, setConfig } from '../config/store';

/**
 * Singleton hook (mount once at app root). Subscribes to the main-process
 * `updates:updateAvailable` push and raises a persistent Update/Dismiss toast.
 *
 * - Update  → api.updates.download() (per-platform routing lives in main;
 *             on Linux read-only AppImage it returns manual-download-required,
 *             which we route to the release page).
 * - Dismiss → persists updates.dismissedAppVersion so this version is
 *             suppressed until a newer one appears.
 * Per-version de-dup: the toast uses a stable id and is skipped when the
 * pushed version equals the stored dismissedAppVersion.
 */
export function useUpdateToast(): void {
  useEffect(() => {
    const api = window.electronAPI;
    if (!api?.updates?.onUpdateAvailable) return;

    const unsubscribe = api.updates.onUpdateAvailable(({ version }) => {
      void (async () => {
        const dismissed = await getConfig<string>('updates.dismissedAppVersion');
        if (dismissed && dismissed === version) return;

        const toastId = `update-available-${version}`;
        toast(`Version ${version} is available`, {
          id: toastId,
          duration: Infinity,
          action: {
            label: 'Update',
            onClick: () => {
              toast.dismiss(toastId);
              void (async () => {
                const r = await api.updates.download();
                if (
                  r &&
                  !r.ok &&
                  r.reason === 'manual-download-required' &&
                  'downloadUrl' in r
                ) {
                  await api.updates.openReleasePage(r.downloadUrl);
                }
              })();
            },
          },
          cancel: {
            label: 'Dismiss',
            onClick: () => {
              toast.dismiss(toastId);
              void setConfig('updates.dismissedAppVersion', version);
            },
          },
        });
      })();
    });

    return () => {
      unsubscribe();
    };
  }, []);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npx vitest run src/hooks/__tests__/useUpdateToast.test.tsx`
Expected: PASS (all five cases).

- [ ] **Step 5: Mount in App.tsx**

In `dashboard/App.tsx`, add to the import block (near line 20-37):

```ts
import { useUpdateToast } from './src/hooks/useUpdateToast';
```

In the `AppInner` body, alongside the other singleton hooks (immediately after `useWatcherFilesBridge();`, line 116), add:

```ts
  // Raises the Update/Dismiss toast when main pushes updates:updateAvailable.
  useUpdateToast();
```

- [ ] **Step 6: Typecheck + commit**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

```bash
git add dashboard/src/hooks/useUpdateToast.ts dashboard/src/hooks/__tests__/useUpdateToast.test.tsx dashboard/App.tsx
git commit -m "feat(update): Update/Dismiss detection toast via useUpdateToast hook"
```

---

## Task 9: `UpdateBanner` respects `updates.dismissedAppVersion`

Keep the existing 4h time-snooze (`bannerSnoozedUntil`) AND add the per-version gate; both must hold for the banner's `available` state.

**Files:**
- Modify: `dashboard/components/ui/UpdateBanner.tsx` (deriveBannerState signature ~210; `availableFromPoll` ~223; state ~279; mount effect ~347; deriveBannerState call ~567)
- Modify: `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` (all `deriveBannerState(...)` call sites)

- [ ] **Step 1: Run impact analysis**

Run: `gitnexus_impact({target: "deriveBannerState", direction: "upstream"})`
Report blast radius. Expected: the component + ~20 test call sites in `UpdateBanner.test.tsx`. This is the highest-churn edit — warn the user if it flags HIGH.

- [ ] **Step 2: Write/adjust the failing tests**

In `dashboard/components/ui/__tests__/UpdateBanner.test.tsx`:
1. Update **every** existing `deriveBannerState(installer, updateStatus, isBusy, now, snoozedUntil)` call to pass a trailing `null` (new `dismissedVersion` arg) — the file has ~20 call sites; a find/replace of `snoozedUntil)` → `snoozedUntil, null)` inside `deriveBannerState(...)` calls is the mechanical fix. Verify each edited line is actually a `deriveBannerState` call.
2. Add these new cases in the `deriveBannerState` describe block:

```ts
it('hides the available state when latest matches the dismissed version', () => {
  const status = availableStatus('1.4.0'); // helper that yields app.updateAvailable + latest '1.4.0'
  const state = deriveBannerState(
    { state: 'idle' },
    status,
    false,
    Date.now(),
    0,
    '1.4.0', // dismissedVersion
  );
  expect(state.kind).not.toBe('available');
});

it('shows the available state when a newer version than the dismissed one appears', () => {
  const status = availableStatus('1.5.0');
  const state = deriveBannerState({ state: 'idle' }, status, false, Date.now(), 0, '1.4.0');
  expect(state.kind).toBe('available');
});

it('shows the available state when nothing has been dismissed', () => {
  const status = availableStatus('1.4.0');
  const state = deriveBannerState({ state: 'idle' }, status, false, Date.now(), 0, null);
  expect(state.kind).toBe('available');
});
```

> Reuse the file's existing helper for building an "available" `UpdateStatus`; if it is inlined, add a small `availableStatus(latest)` factory near the top of the describe block that returns `{ lastChecked: '...', app: { current: '1.3.0', latest, updateAvailable: true, releaseNotes: null, error: null }, server: {...} }` matching the shape the file already uses. Match `state.kind` to whatever discriminant the file asserts on (it may be `state.kind` or a string — copy the existing assertions' style).

- [ ] **Step 3: Run tests to verify the new cases fail**

Run: `cd dashboard && npx vitest run components/ui/__tests__/UpdateBanner.test.tsx`
Expected: FAIL on the three new cases (arg not yet used); the `null`-threaded existing cases should still pass.

- [ ] **Step 4: Thread `dismissedVersion` through `deriveBannerState`**

In `dashboard/components/ui/UpdateBanner.tsx`, add the parameter to the exported `deriveBannerState` signature (line ~210), e.g.:

```ts
export function deriveBannerState(
  installer: InstallerStatus,
  updateStatus: UpdateStatus | null,
  isBusy: boolean,
  now: number,
  snoozedUntil: number,
  dismissedVersion: string | null,
): BannerState {
```

In the `availableFromPoll` computation (line ~223), AND-in the per-version gate. Find the existing condition (it computes availability from `updateStatus.app.updateAvailable` + snooze) and add `&& latestVersion !== dismissedVersion`, where `latestVersion` is the `updateStatus?.app?.latest` value the function already reads. Example — if the current line is:

```ts
  const availableFromPoll =
    !snoozed && updateAvailable && latestVersion != null && latestVersion !== '';
```

change it to:

```ts
  const availableFromPoll =
    !snoozed &&
    updateAvailable &&
    latestVersion != null &&
    latestVersion !== '' &&
    latestVersion !== dismissedVersion;
```

> If the local variable names differ (`updateAvailable`/`latestVersion`), adapt to the file's actual names — the semantic change is "also require latest !== dismissedVersion". Exact-match is correct for suppress-until-newer (see plan design note 2).

- [ ] **Step 5: Load and pass `dismissedVersion` in the component**

In the component body, add state next to the existing snooze state (line ~279):

```ts
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
```

In the mount effect, after the existing `getConfig<number>('updates.bannerSnoozedUntil')` block (line ~347-355), add a sibling read using the identical cancelled-guard idiom:

```ts
    getConfig<string>('updates.dismissedAppVersion')
      .then((v) => {
        if (cancelled) return;
        setDismissedVersion(typeof v === 'string' && v ? v : null);
      })
      .catch((err) => console.error('Failed to read dismissed update version:', err));
```

Thread it into the `deriveBannerState(...)` call (line ~567):

```ts
  const bannerState = deriveBannerState(
    installerStatus,
    updateStatus,
    isBusy,
    now,
    snoozedUntil,
    dismissedVersion,
  );
```

> Match the exact argument names/order the file currently passes; only the new trailing `dismissedVersion` is added.

- [ ] **Step 6: Run tests to verify all pass**

Run: `cd dashboard && npx vitest run components/ui/__tests__/UpdateBanner.test.tsx`
Expected: PASS (existing + three new cases).

- [ ] **Step 7: Commit**

```bash
git add dashboard/components/ui/UpdateBanner.tsx dashboard/components/ui/__tests__/UpdateBanner.test.tsx
git commit -m "feat(update): banner respects per-version dismissal (updates.dismissedAppVersion)"
```

---

## Task 10: Full verification (typecheck, lint, tests, UI contract)

**Files:** none (verification only)

- [ ] **Step 1: Typecheck main + renderer**

Run: `cd dashboard && npx tsc -p electron/tsconfig.json --noEmit && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 2: Lint**

Run: `cd dashboard && npx eslint electron/appVariant.ts electron/macVariantUpdater.ts electron/updateMigration.ts electron/updateManager.ts electron/main.ts electron/preload.ts src/hooks/useUpdateToast.ts components/ui/UpdateBanner.tsx`
Expected: clean (fix any `no-explicit-any`/`no-console` findings per project rules).

- [ ] **Step 3: Run the FULL vitest suite (not per-file subsets)**

Run: `cd dashboard && npx vitest run`
Expected: PASS. (Project memory `project_sensevoice_phase2_diarization`: per-task subsets have missed route-level regressions — run the whole suite.)

- [ ] **Step 4: UI contract (SettingsModal/UpdateBanner/toast touched CSS classes?)**

Only class-affecting changes here are minimal (no new className literals were added in this plan), but run the read-only check to be safe:

Run: `cd dashboard && npm run ui:contract:check`
Expected: PASS. If it fails, follow `.claude/skills/ui-contract/SKILL.md` update sequence (extract → build → validate --update-baseline → check), bumping `meta.spec_version` first (memory: `gotcha_ui_contract_spec_version_bump`).

- [ ] **Step 5: Detect changed scope before final commit**

Run: `gitnexus_detect_changes()` (CLAUDE.md requirement). Confirm only the expected symbols/flows changed.

- [ ] **Step 6: Final commit (if anything adjusted during verification)**

```bash
git add -A
git commit -m "chore(update): verification fixes (lint/typecheck/contract)"
```

---

## Self-Review

**Spec coverage:**
- (i) default-on weekly + force-on migration → Task 3 (defaults in 3 sites + `updateMigration.ts` + boot wiring). ✅
- (ii) toast with Update/Dismiss, push-triggered, per-version dismiss, banner aligned → Tasks 4 (emit), 6 (forward), 7 (preload), 8 (hook), 9 (banner). ✅
- (iii) same-variant download; Linux/Win unchanged; macOS matched-DMG download+verify+reveal → Tasks 1 (identity), 5 (downloader), 6 (routing). ✅
- macOS verify standard/best-effort metal → Task 5 (`fetchExpectedSha512` + metal skip). ✅
- Update click downloads immediately → Task 8 (onClick → download, no modal). ✅

**Placeholder scan:** No TBD/TODO. The two "adapt to the file's actual variable names" notes (Task 4 test factories, Task 9 `availableFromPoll`/`state.kind`) are explicit adaptation instructions with the exact semantic change spelled out, not deferred work — acceptable because the target files' internal identifiers can't be quoted verbatim without over-reading, and the change is unambiguous.

**Type consistency:** `AppVariant`, `InstallerStatus`, `MacVariantResult`, and the `{version, releaseNotes}` push payload are used identically across Tasks 1/4/5/6/7/8. `updates.dismissedAppVersion` (string) and `updates.forceOnMigrationDone` (boolean) are used consistently in Tasks 3/5/8/9. Event name `updateAvailable` (emit, Task 4) ↔ `updateManager.on('updateAvailable')` (forward, Task 6) ↔ IPC channel `updates:updateAvailable` (Tasks 6/7) are aligned.

**Out of scope (unchanged):** server Docker image update path; Apple signing/notarization; the dormant `manifest.json` sha256 pipeline.
