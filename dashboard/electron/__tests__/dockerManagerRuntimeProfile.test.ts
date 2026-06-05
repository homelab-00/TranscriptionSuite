// @vitest-environment node

/**
 * Runtime-profile desync fix — the persisted `server.runtimeProfile` is the
 * source of truth at container-start time.
 *
 * Background: each renderer start surface (App / SessionView / ServerView)
 * hydrates its own copy of the runtime profile once on mount and can drift
 * stale. A container could therefore launch under a profile the user had
 * already changed away from (observed: started under Vulkan, switched to GPU,
 * never restarted → kept running CPU-only). `startContainer` now re-reads the
 * persisted value and prefers it over the renderer-supplied request.
 *
 * Full `startContainer` is hard to unit-test without a Docker runtime, so these
 * cover the two pure pieces it funnels through: `readRuntimeProfileFromStore`
 * (disk read + validation) and `resolveEffectiveRuntimeProfile` (the precedence
 * rule).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// Mock `electron` before importing dockerManager — the module imports `app`
// at the top level and needs a usable path for `getPath('userData')`.
const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-runtime-profile-test-'));

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (_name: string) => userDataRoot,
    setPath: vi.fn(),
  },
}));

// Mock electron-store (imported transitively by config readers)
vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

import {
  readRuntimeProfileFromStore,
  resolveEffectiveRuntimeProfile,
  type RuntimeProfile,
} from '../dockerManager.js';

const STORE_FILE = path.join(userDataRoot, 'dashboard-config.json');

function writeStore(contents: Record<string, unknown>): void {
  fs.writeFileSync(STORE_FILE, JSON.stringify(contents), 'utf8');
}

beforeEach(() => {
  try {
    fs.unlinkSync(STORE_FILE);
  } catch {
    // fine
  }
});

afterEach(() => {
  try {
    fs.unlinkSync(STORE_FILE);
  } catch {
    // fine
  }
});

describe('[P1] runtime-profile desync — readRuntimeProfileFromStore', () => {
  it('returns null when the store file is absent', () => {
    expect(readRuntimeProfileFromStore()).toBeNull();
  });

  it('returns null when the store is present but the key is unset', () => {
    writeStore({ 'connection.port': 9786 });
    expect(readRuntimeProfileFromStore()).toBeNull();
  });

  it.each<RuntimeProfile>(['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'])(
    'returns "%s" when persisted as a valid profile',
    (profile) => {
      writeStore({ 'server.runtimeProfile': profile });
      expect(readRuntimeProfileFromStore()).toBe(profile);
    },
  );

  it('returns null for an unknown/invalid profile string', () => {
    writeStore({ 'server.runtimeProfile': 'tpu' });
    expect(readRuntimeProfileFromStore()).toBeNull();
  });

  it('returns null for a non-string value (strict type guard)', () => {
    writeStore({ 'server.runtimeProfile': 1 });
    expect(readRuntimeProfileFromStore()).toBeNull();
  });

  it('returns null when the store file is malformed JSON', () => {
    fs.writeFileSync(STORE_FILE, '{not json', 'utf8');
    expect(readRuntimeProfileFromStore()).toBeNull();
  });
});

describe('[P1] runtime-profile desync — resolveEffectiveRuntimeProfile', () => {
  it('prefers the persisted value over a stale renderer request', () => {
    // The exact reported bug: renderer still holds mount-time "vulkan", but the
    // user switched to "gpu" (persisted). The persisted value must win.
    expect(resolveEffectiveRuntimeProfile('vulkan', 'gpu')).toBe('gpu');
  });

  it('falls back to the renderer request when nothing is persisted (first run)', () => {
    expect(resolveEffectiveRuntimeProfile('gpu', null)).toBe('gpu');
  });

  it('is a no-op when persisted and requested already agree', () => {
    expect(resolveEffectiveRuntimeProfile('gpu', 'gpu')).toBe('gpu');
    expect(resolveEffectiveRuntimeProfile('cpu', 'cpu')).toBe('cpu');
  });

  it('end-to-end: persisted gpu beats requested vulkan via the store reader', () => {
    writeStore({ 'server.runtimeProfile': 'gpu' });
    const requested: RuntimeProfile = 'vulkan';
    expect(resolveEffectiveRuntimeProfile(requested, readRuntimeProfileFromStore())).toBe('gpu');
  });
});
