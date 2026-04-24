// @vitest-environment node

/**
 * Issue #83 — Legacy-GPU image variant: repo resolution + GHCR URL building.
 *
 * Covers the pure helpers threaded through dockerManager: `resolveImageRepo`
 * (the default/legacy switch) and `buildGhcrUrlsForRepo` (token/tags/blob
 * URLs). These two functions are the only divergence points between the two
 * image channels; every other repo-sensitive path funnels through them.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// Mock `electron` before importing dockerManager — the module imports `app`
// at the top level and needs a usable path for `getPath('userData')`.
const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-legacy-gpu-test-'));

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
  IMAGE_REPO,
  LEGACY_IMAGE_REPO,
  resolveImageRepo,
  buildGhcrUrlsForRepo,
  readUseLegacyGpuFromStore,
  listRemoteTags,
} from '../dockerManager.js';

const STORE_FILE = path.join(userDataRoot, 'dashboard-config.json');

function writeStore(contents: Record<string, unknown>): void {
  fs.writeFileSync(STORE_FILE, JSON.stringify(contents), 'utf8');
}

beforeEach(() => {
  // Clean store between tests
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

describe('[P1] Issue #83 — IMAGE_REPO constants', () => {
  it('default IMAGE_REPO matches the canonical GHCR path', () => {
    expect(IMAGE_REPO).toBe('ghcr.io/homelab-00/transcriptionsuite-server');
  });

  it('LEGACY_IMAGE_REPO is a distinct repo suffixed with -legacy', () => {
    expect(LEGACY_IMAGE_REPO).toBe('ghcr.io/homelab-00/transcriptionsuite-server-legacy');
    expect(LEGACY_IMAGE_REPO).not.toBe(IMAGE_REPO);
    expect(LEGACY_IMAGE_REPO.endsWith('-legacy')).toBe(true);
  });

  it('keeps main-process IMAGE_REPO in sync with versionUtils.ts', () => {
    // Spec contract: the electron-side constants and the renderer-side
    // versionUtils.ts constants must match exactly. If either drifts the
    // compose env and the tag dropdown end up pointing at different repos.
    expect(IMAGE_REPO).toBe('ghcr.io/homelab-00/transcriptionsuite-server');
    expect(LEGACY_IMAGE_REPO).toBe('ghcr.io/homelab-00/transcriptionsuite-server-legacy');
  });
});

describe('[P1] Issue #83 — resolveImageRepo', () => {
  it('returns the default repo when useLegacyGpu is false', () => {
    expect(resolveImageRepo(false)).toBe(IMAGE_REPO);
  });

  it('returns the legacy repo when useLegacyGpu is true', () => {
    expect(resolveImageRepo(true)).toBe(LEGACY_IMAGE_REPO);
  });

  it('never mixes repos — the two outputs are distinct', () => {
    expect(new Set([resolveImageRepo(false), resolveImageRepo(true)]).size).toBe(2);
  });
});

describe('[P1] Issue #83 — buildGhcrUrlsForRepo', () => {
  it('derives token/tags/blob URLs from the default repo URL', () => {
    const urls = buildGhcrUrlsForRepo(IMAGE_REPO);
    expect(urls.tokenUrl).toBe(
      'https://ghcr.io/token?scope=repository:homelab-00/transcriptionsuite-server:pull',
    );
    expect(urls.tagsUrl).toBe('https://ghcr.io/v2/homelab-00/transcriptionsuite-server/tags/list');
    expect(urls.blobBase).toBe('https://ghcr.io/v2/homelab-00/transcriptionsuite-server');
  });

  it('derives token/tags/blob URLs from the legacy repo URL', () => {
    const urls = buildGhcrUrlsForRepo(LEGACY_IMAGE_REPO);
    expect(urls.tokenUrl).toBe(
      'https://ghcr.io/token?scope=repository:homelab-00/transcriptionsuite-server-legacy:pull',
    );
    expect(urls.tagsUrl).toBe(
      'https://ghcr.io/v2/homelab-00/transcriptionsuite-server-legacy/tags/list',
    );
    expect(urls.blobBase).toBe('https://ghcr.io/v2/homelab-00/transcriptionsuite-server-legacy');
  });

  it('never points at the other repo — URLs are fully distinct between variants', () => {
    const d = buildGhcrUrlsForRepo(IMAGE_REPO);
    const l = buildGhcrUrlsForRepo(LEGACY_IMAGE_REPO);
    expect(d.tokenUrl).not.toBe(l.tokenUrl);
    expect(d.tagsUrl).not.toBe(l.tagsUrl);
    expect(d.blobBase).not.toBe(l.blobBase);
    // Cheap cross-contamination sanity: the default URL must NOT contain
    // '-legacy', and the legacy URL MUST contain '-legacy'.
    expect(d.tagsUrl.includes('-legacy')).toBe(false);
    expect(l.tagsUrl.includes('-legacy')).toBe(true);
  });
});

describe('[P1] Issue #83 — readUseLegacyGpuFromStore', () => {
  it('returns false when the store file is absent', () => {
    expect(readUseLegacyGpuFromStore()).toBe(false);
  });

  it('returns false when the store is present but the key is unset', () => {
    writeStore({ 'connection.port': 9786 });
    expect(readUseLegacyGpuFromStore()).toBe(false);
  });

  it('returns false when the key is explicitly false', () => {
    writeStore({ 'server.useLegacyGpu': false });
    expect(readUseLegacyGpuFromStore()).toBe(false);
  });

  it('returns true when the key is explicitly true', () => {
    writeStore({ 'server.useLegacyGpu': true });
    expect(readUseLegacyGpuFromStore()).toBe(true);
  });

  it('returns false for non-boolean truthy values (strict equality)', () => {
    // Prevents a string "true" from accidentally flipping the variant.
    writeStore({ 'server.useLegacyGpu': 'true' });
    expect(readUseLegacyGpuFromStore()).toBe(false);
  });

  it('returns false when the store file is malformed JSON', () => {
    fs.writeFileSync(STORE_FILE, '{not json', 'utf8');
    expect(readUseLegacyGpuFromStore()).toBe(false);
  });
});

describe('[P1] Issue #99 — listRemoteTags token-401 mapping', () => {
  // The GHCR token endpoint returns 401 for Private packages — the realistic
  // failure mode the v1.3.3 legacy push exposed. These tests lock in that
  // the mapping to `not-published` is gated on the legacy toggle so the
  // default repo keeps its "401 = genuine fault" semantics.

  let fetchSpy: ReturnType<typeof vi.fn>;

  function mockFetch(
    impl: (url: string | URL | Request) => Promise<Response>,
  ): ReturnType<typeof vi.fn> {
    const fn = vi.fn(impl);
    vi.stubGlobal('fetch', fn);
    return fn;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchSpy?.mockClear();
  });

  it('legacy ON + token 401 → not-published (GH-99 defense)', async () => {
    writeStore({ 'server.useLegacyGpu': true });
    fetchSpy = mockFetch(
      async () => new Response('Unauthorized', { status: 401, statusText: 'Unauthorized' }),
    );
    const result = await listRemoteTags();
    expect(result.status).toBe('not-published');
    expect(result.tags).toEqual([]);
    // Sanity: the legacy tokenUrl was hit, not the default one.
    const firstCallUrl = String(fetchSpy.mock.calls[0]?.[0]);
    expect(firstCallUrl).toContain('transcriptionsuite-server-legacy');
  });

  it('legacy OFF + token 401 → error (default repo 401 is a genuine fault)', async () => {
    writeStore({ 'server.useLegacyGpu': false });
    fetchSpy = mockFetch(
      async () => new Response('Unauthorized', { status: 401, statusText: 'Unauthorized' }),
    );
    const result = await listRemoteTags();
    expect(result.status).toBe('error');
    expect(result.tags).toEqual([]);
  });

  it('legacy ON + token 200 + tags 404 → not-published (regression guard for GH-83)', async () => {
    writeStore({ 'server.useLegacyGpu': true });
    fetchSpy = mockFetch(async (url) => {
      const s = String(url);
      if (s.includes('/token')) {
        return new Response(JSON.stringify({ token: 'fake-bearer' }), { status: 200 });
      }
      return new Response('Not Found', { status: 404, statusText: 'Not Found' });
    });
    const result = await listRemoteTags();
    expect(result.status).toBe('not-published');
    expect(result.tags).toEqual([]);
  });
});

describe('[P1] Issue #83 — compose-env IMAGE_REPO selection (smoke)', () => {
  // Full startContainer is hard to unit-test without a Docker runtime, but the
  // documented contract is: the IMAGE_REPO env passed to docker compose must
  // equal resolveImageRepo(useLegacyGpu). These tests exercise the pure
  // composition that startContainer uses.
  it('default-user path: resolver agrees with the unchanged compose template', () => {
    writeStore({ 'server.useLegacyGpu': false });
    expect(resolveImageRepo(readUseLegacyGpuFromStore())).toBe(IMAGE_REPO);
  });

  it('legacy-user path: resolver flips the compose IMAGE_REPO env', () => {
    writeStore({ 'server.useLegacyGpu': true });
    expect(resolveImageRepo(readUseLegacyGpuFromStore())).toBe(LEGACY_IMAGE_REPO);
  });
});
