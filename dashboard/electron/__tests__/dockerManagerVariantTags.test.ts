// @vitest-environment node

/**
 * Image variant selector — per-variant GHCR tag listing.
 *
 * Covers `IMAGE_VARIANT_REPOS` (the variant → repo map the Docker Image
 * card's selector is built on) and `listVariantTags` (the parallel four-repo
 * tag probe that powers per-version variant availability). Failure isolation
 * matters most here: one unpublished/private/unreachable variant must never
 * blank out the availability data of the others.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// Mock `electron` before importing dockerManager — the module imports `app`
// at the top level and needs a usable path for `getPath('userData')`.
const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-variant-tags-test-'));

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
  VULKAN_WSL2_IMAGE_REPO,
  VULKAN_LINUX_IMAGE_REPO,
  IMAGE_VARIANT_REPOS,
  listVariantTags,
} from '../dockerManager.js';

function mockFetch(
  impl: (url: string | URL | Request) => Promise<Response>,
): ReturnType<typeof vi.fn> {
  const fn = vi.fn(impl);
  vi.stubGlobal('fetch', fn);
  return fn;
}

function tagsResponse(tags: string[]): Response {
  return new Response(JSON.stringify({ tags }), { status: 200 });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('[P1] IMAGE_VARIANT_REPOS', () => {
  it('maps each variant to its canonical GHCR repo', () => {
    expect(IMAGE_VARIANT_REPOS).toEqual({
      cuda: IMAGE_REPO,
      'cuda-legacy': LEGACY_IMAGE_REPO,
      'vulkan-wsl2': VULKAN_WSL2_IMAGE_REPO,
      'vulkan-linux': VULKAN_LINUX_IMAGE_REPO,
    });
  });

  it('vulkan-linux repo follows the shared naming scheme', () => {
    expect(VULKAN_LINUX_IMAGE_REPO).toBe(
      'ghcr.io/homelab-00/transcriptionsuite-server-vulkan-linux',
    );
  });

  it('all four repos are distinct — variant tag lists can never mix', () => {
    expect(new Set(Object.values(IMAGE_VARIANT_REPOS)).size).toBe(4);
  });
});

describe('[P1] listVariantTags', () => {
  it('returns per-variant tag lists keyed by variant', async () => {
    // Dispatch by repo suffix. The default repo path is a prefix of the
    // other three, so suffixed repos must be matched first.
    mockFetch(async (url) => {
      const s = String(url);
      if (s.includes('/token')) {
        return new Response(JSON.stringify({ token: 'fake-bearer' }), { status: 200 });
      }
      if (s.includes('transcriptionsuite-server-legacy/')) {
        return tagsResponse(['v1.3.7', 'v1.3.3']);
      }
      if (s.includes('transcriptionsuite-server-vulkan-wsl2/')) {
        return tagsResponse(['v1.3.7', 'v1.3.6']);
      }
      if (s.includes('transcriptionsuite-server-vulkan-linux/')) {
        return tagsResponse(['v1.3.7']);
      }
      return tagsResponse(['v1.3.7', 'v1.3.6', 'v1.3.5']);
    });

    const result = await listVariantTags();
    expect(result.cuda).toEqual(['v1.3.7', 'v1.3.6', 'v1.3.5']);
    expect(result['cuda-legacy']).toEqual(['v1.3.7', 'v1.3.3']);
    expect(result['vulkan-wsl2']).toEqual(['v1.3.7', 'v1.3.6']);
    expect(result['vulkan-linux']).toEqual(['v1.3.7']);
  });

  it('filters non-version tags (latest, sha-…) like listRemoteTags does', async () => {
    mockFetch(async (url) => {
      const s = String(url);
      if (s.includes('/token')) {
        return new Response(JSON.stringify({ token: 'fake-bearer' }), { status: 200 });
      }
      return tagsResponse(['latest', 'v1.3.7', 'sha-deadbeef', 'v1.3.7rc1']);
    });

    const result = await listVariantTags();
    expect(result.cuda).toEqual(['v1.3.7', 'v1.3.7rc1']);
  });

  it('isolates failures per variant — one 404 never blanks the others', async () => {
    mockFetch(async (url) => {
      const s = String(url);
      if (s.includes('/token')) {
        // Private-package simulation: token 401 for vulkan-linux only.
        if (s.includes('transcriptionsuite-server-vulkan-linux')) {
          return new Response('Unauthorized', { status: 401 });
        }
        return new Response(JSON.stringify({ token: 'fake-bearer' }), { status: 200 });
      }
      if (s.includes('transcriptionsuite-server-vulkan-wsl2/')) {
        return new Response('Not Found', { status: 404 });
      }
      return tagsResponse(['v1.3.7']);
    });

    const result = await listVariantTags();
    expect(result.cuda).toEqual(['v1.3.7']);
    expect(result['cuda-legacy']).toEqual(['v1.3.7']);
    expect(result['vulkan-wsl2']).toEqual([]);
    expect(result['vulkan-linux']).toEqual([]);
  });

  it('resolves with all-empty lists instead of rejecting when fetch throws', async () => {
    mockFetch(async () => {
      throw new Error('network down');
    });

    const result = await listVariantTags();
    expect(result).toEqual({
      cuda: [],
      'cuda-legacy': [],
      'vulkan-wsl2': [],
      'vulkan-linux': [],
    });
  });
});
