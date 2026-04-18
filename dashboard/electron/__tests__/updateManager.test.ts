/**
 * updateManager — focused tests for the release-notes sanitizer and
 * the M6 single-shot failure-retry timer.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// electron must be mocked at module-resolution time because updateManager
// imports Notification + app for the notification path.
vi.mock('electron', () => ({
  Notification: class {
    show() {}
  },
  app: {
    getVersion: () => '1.0.0',
  },
}));

vi.mock('../dockerManager.js', () => ({
  dockerManager: {
    listImages: async () => [],
  },
  // Matches the real pure helpers — buildGhcrUrlsForRepo is deterministic, and
  // resolveImageRepo returns the default repo when useLegacyGpu is false (the
  // path these tests exercise). Keeps URL substrings that the fetch mocks match
  // on (`ghcr.io/token`, `ghcr.io/v2`).
  buildGhcrUrlsForRepo: (imageRepo: string) => {
    const pkgPath = imageRepo.replace(/^ghcr\.io\//, '');
    return {
      tokenUrl: `https://ghcr.io/token?scope=repository:${pkgPath}:pull`,
      tagsUrl: `https://ghcr.io/v2/${pkgPath}/tags/list`,
      blobBase: `https://ghcr.io/v2/${pkgPath}`,
    };
  },
  resolveImageRepo: (useLegacyGpu: boolean) =>
    useLegacyGpu
      ? 'ghcr.io/homelab-00/transcriptionsuite-server-legacy'
      : 'ghcr.io/homelab-00/transcriptionsuite-server',
}));

import { sanitizeReleaseBody, UpdateManager, FAILURE_RETRY_MS } from '../updateManager';

const MAX = 50_000;

describe('sanitizeReleaseBody', () => {
  it('returns null for non-string input', () => {
    expect(sanitizeReleaseBody(undefined)).toBeNull();
    expect(sanitizeReleaseBody(null)).toBeNull();
    expect(sanitizeReleaseBody(42)).toBeNull();
    expect(sanitizeReleaseBody({ body: 'x' })).toBeNull();
  });

  it('returns null for whitespace-only input', () => {
    expect(sanitizeReleaseBody('')).toBeNull();
    expect(sanitizeReleaseBody('   ')).toBeNull();
    expect(sanitizeReleaseBody('\n\n\t')).toBeNull();
  });

  it('returns trimmed content for typical release bodies', () => {
    expect(sanitizeReleaseBody('  ## Changelog\n- fix X\n  ')).toBe('## Changelog\n- fix X');
  });

  it('passes through content under the cap unchanged', () => {
    const body = 'a'.repeat(MAX);
    expect(sanitizeReleaseBody(body)).toBe(body);
  });

  it('truncates content over the cap to exactly MAX code points', () => {
    const body = 'a'.repeat(MAX + 1000);
    const out = sanitizeReleaseBody(body);
    expect(out).not.toBeNull();
    expect(Array.from(out as string).length).toBe(MAX);
  });

  it('does NOT split a surrogate pair at the boundary (astral-safe truncation)', () => {
    // 😀 (U+1F600) occupies 2 UTF-16 units; plain slice at MAX would split
    // the pair if the boundary lands inside it. Construct a string where
    // the last codepoint before the cap is an emoji.
    const pad = 'a'.repeat(MAX - 1);
    const body = pad + '😀' + 'tail';
    const out = sanitizeReleaseBody(body);
    expect(out).not.toBeNull();
    // Last code point in the output must be a well-formed emoji — no lone
    // surrogate (which would show up as a replacement character or fail
    // `isWellFormed()` checks on modern engines).
    const codepoints = Array.from(out as string);
    expect(codepoints.length).toBe(MAX);
    expect(codepoints[codepoints.length - 1]).toBe('😀');
  });

  it('trims only leading/trailing whitespace, not internal', () => {
    expect(sanitizeReleaseBody('  line 1\nline 2  ')).toBe('line 1\nline 2');
  });
});

// ─── M6: failure retry timer ───────────────────────────────────────────────

function makeFakeStore(): {
  get: (k: string) => unknown;
  set: (k: string, v: unknown) => void;
  data: Record<string, unknown>;
} {
  const data: Record<string, unknown> = {
    'app.showNotifications': false, // suppress notification path during tests
  };
  return {
    data,
    get: (k: string) => data[k],
    set: (k: string, v: unknown) => {
      data[k] = v;
    },
  };
}

describe('UpdateManager failure-retry timer', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let manager: UpdateManager;
  let store: ReturnType<typeof makeFakeStore>;

  beforeEach(() => {
    vi.useFakeTimers();
    store = makeFakeStore();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    manager = new UpdateManager(store as any);
    fetchSpy = vi.spyOn(globalThis, 'fetch');
  });

  afterEach(() => {
    manager.destroy();
    fetchSpy.mockRestore();
    vi.useRealTimers();
  });

  it('arms a 1h retry when both components error', async () => {
    fetchSpy.mockRejectedValue(new Error('network down'));

    await manager.check();

    expect(manager.hasFailureRetry()).toBe(true);
  });

  it('clears the retry when the next check succeeds cleanly', async () => {
    // First call: fail on both channels.
    fetchSpy.mockRejectedValueOnce(new Error('app fail'));
    fetchSpy.mockRejectedValueOnce(new Error('token fail'));
    await manager.check();
    expect(manager.hasFailureRetry()).toBe(true);

    // Second call: both channels succeed. GitHub returns a release; GHCR
    // returns a token then tags.
    fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
      const url = input instanceof URL ? input.href : String(input);
      if (url.includes('api.github.com')) {
        return new Response(JSON.stringify({ tag_name: 'v1.0.0', body: '' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('ghcr.io/token')) {
        return new Response(JSON.stringify({ token: 'fake' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('ghcr.io/v2')) {
        return new Response(JSON.stringify({ tags: ['1.0.0'] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`unexpected fetch url: ${url}`);
    });

    await manager.check();
    expect(manager.hasFailureRetry()).toBe(false);
  });

  it('destroy() clears any armed retry', async () => {
    fetchSpy.mockRejectedValue(new Error('fail'));
    await manager.check();
    expect(manager.hasFailureRetry()).toBe(true);

    manager.destroy();
    expect(manager.hasFailureRetry()).toBe(false);
  });

  it('arms retry after only one component errors (app channel down, server channel ok)', async () => {
    fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
      const url = input instanceof URL ? input.href : String(input);
      if (url.includes('api.github.com')) {
        throw new Error('github down');
      }
      if (url.includes('ghcr.io/token')) {
        return new Response(JSON.stringify({ token: 'fake' }), { status: 200 });
      }
      if (url.includes('ghcr.io/v2')) {
        return new Response(JSON.stringify({ tags: ['1.0.0'] }), { status: 200 });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    await manager.check();
    expect(manager.hasFailureRetry()).toBe(true);
  });

  it('scheduled retry fires after FAILURE_RETRY_MS', async () => {
    fetchSpy.mockRejectedValue(new Error('fail'));
    await manager.check();
    expect(fetchSpy).toHaveBeenCalled();
    const firstCallCount = fetchSpy.mock.calls.length;

    // Advance to just before the retry and confirm no re-check.
    await vi.advanceTimersByTimeAsync(FAILURE_RETRY_MS - 1);
    expect(fetchSpy.mock.calls.length).toBe(firstCallCount);

    // Cross the boundary — the single-shot timer fires.
    await vi.advanceTimersByTimeAsync(2);
    expect(fetchSpy.mock.calls.length).toBeGreaterThan(firstCallCount);
  });

  it('check() short-circuits after destroy() without touching the store', async () => {
    manager.destroy();
    // Spy on store.set AFTER destroy so we only capture post-destroy writes.
    const setSpy = vi.spyOn(store, 'set');

    fetchSpy.mockRejectedValue(new Error('fail'));
    const result = await manager.check();

    expect(result.app.error).toBe('destroyed');
    expect(result.server.error).toBe('destroyed');
    expect(setSpy).not.toHaveBeenCalledWith('updates.lastStatus', expect.anything());
  });
});

// ─── GH-83 EC-12: legacy-repo 404 surfaces a human-readable error ──────────

describe('UpdateManager.checkServer — legacy 404 handling', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let manager: UpdateManager;
  let store: ReturnType<typeof makeFakeStore>;

  beforeEach(() => {
    store = makeFakeStore();
    store.set('server.useLegacyGpu', true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    manager = new UpdateManager(store as any);
    fetchSpy = vi.spyOn(globalThis, 'fetch');
  });

  afterEach(() => {
    manager.destroy();
    fetchSpy.mockRestore();
  });

  it('returns "Legacy image not yet published" when GHCR returns 404 and useLegacyGpu is true', async () => {
    fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
      const url = input instanceof URL ? input.href : String(input);
      if (url.includes('api.github.com')) {
        return new Response(JSON.stringify({ tag_name: 'v1.0.0', body: '' }), { status: 200 });
      }
      if (url.includes('ghcr.io/token')) {
        return new Response(JSON.stringify({ token: 'fake' }), { status: 200 });
      }
      if (url.includes('ghcr.io/v2') && url.includes('-legacy')) {
        return new Response('not found', { status: 404 });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    const result = await manager.check();
    expect(result.server.error).toBe('Legacy image not yet published for this release');
    expect(result.server.latest).toBeNull();
    expect(result.server.updateAvailable).toBe(false);
  });

  it('still surfaces a generic error for 404 on the default (non-legacy) repo', async () => {
    store.set('server.useLegacyGpu', false);
    fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
      const url = input instanceof URL ? input.href : String(input);
      if (url.includes('api.github.com')) {
        return new Response(JSON.stringify({ tag_name: 'v1.0.0', body: '' }), { status: 200 });
      }
      if (url.includes('ghcr.io/token')) {
        return new Response(JSON.stringify({ token: 'fake' }), { status: 200 });
      }
      if (url.includes('ghcr.io/v2')) {
        return new Response('not found', { status: 404 });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    const result = await manager.check();
    // Default repo 404 is unexpected — surface the raw status so an operator
    // can diagnose. We only remap the legacy case because that one has a
    // known, recurring, first-release-state cause.
    expect(result.server.error).toMatch(/GHCR tags request returned 404/);
  });
});
