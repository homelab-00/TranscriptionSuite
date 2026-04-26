/**
 * updateManager — focused tests for the release-notes sanitizer and
 * the M6 single-shot failure-retry timer.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// electron must be mocked at module-resolution time because updateManager
// imports Notification + app for the notification path.
//
// `versionRef` is hoisted so it lives in the same execution slot as the
// mock factory, but stays mutable between tests. Issue #105 tests need to
// drive `app.getVersion()` to specific values to exercise the getStatus
// re-derivation; existing tests still see '1.0.0' as long as the ref is
// reset before each block that varies it.
const versionRef = vi.hoisted(() => ({ value: '1.0.0' }));

vi.mock('electron', () => ({
  Notification: class {
    show() {}
  },
  app: {
    getVersion: () => versionRef.value,
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

// ─── Issue #105: getStatus re-derives against running app.getVersion() ─────

// Top-level safety net: any test in any describe block that mutates
// `versionRef.value` cannot leak into the next test. The new describe
// below relies on per-test mutation, but this guard also defends future
// describe blocks that may add similar tests without their own afterEach.
afterEach(() => {
  versionRef.value = '1.0.0';
});

describe('UpdateManager.getStatus — re-derives app status against runtime version', () => {
  let manager: UpdateManager;
  let store: ReturnType<typeof makeFakeStore>;

  beforeEach(() => {
    store = makeFakeStore();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    manager = new UpdateManager(store as any);
  });

  afterEach(() => {
    manager.destroy();
  });

  it('returns null when no status has ever been persisted', () => {
    versionRef.value = '1.3.3';
    expect(manager.getStatus()).toBeNull();
  });

  it('flips updateAvailable to false when the running version matches persisted latest (Issue #105 upgrade race)', () => {
    // Simulate a persisted status from before the user upgraded: the prior
    // run was on 1.3.2 and recorded the GitHub release 1.3.3 as available.
    store.data['updates.lastStatus'] = {
      lastChecked: '2026-04-25T00:00:00.000Z',
      app: {
        current: '1.3.2',
        latest: '1.3.3',
        updateAvailable: true,
        error: null,
        releaseNotes: '## v1.3.3\n- example notes',
      },
      server: {
        current: '1.0.0',
        latest: '1.0.0',
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
    };
    versionRef.value = '1.3.3';

    const status = manager.getStatus();
    expect(status).not.toBeNull();
    expect(status!.app.current).toBe('1.3.3');
    expect(status!.app.updateAvailable).toBe(false);
    // `latest` stays so SettingsModal can still render "1.3.3 — up to date".
    expect(status!.app.latest).toBe('1.3.3');
    // releaseNotes / error pass through untouched — only the two derived
    // fields are recomputed.
    expect(status!.app.releaseNotes).toBe('## v1.3.3\n- example notes');
    expect(status!.app.error).toBeNull();
  });

  it('keeps updateAvailable true when persisted latest is genuinely newer than the running version', () => {
    store.data['updates.lastStatus'] = {
      lastChecked: '2026-04-25T00:00:00.000Z',
      app: {
        current: '1.3.3',
        latest: '1.4.0',
        updateAvailable: true,
        error: null,
        releaseNotes: null,
      },
      server: {
        current: null,
        latest: null,
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
    };
    versionRef.value = '1.3.3';

    const status = manager.getStatus();
    expect(status!.app.current).toBe('1.3.3');
    expect(status!.app.updateAvailable).toBe(true);
    expect(status!.app.latest).toBe('1.4.0');
  });

  it('flips updateAvailable to false when the running version is unparsable (pre-release)', () => {
    // parseSemVer is strict X.Y.Z — a pre-release tag in the running app
    // version returns null and must NOT default to "update available".
    store.data['updates.lastStatus'] = {
      lastChecked: '2026-04-25T00:00:00.000Z',
      app: {
        current: '1.3.3',
        latest: '1.3.3',
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
      server: {
        current: null,
        latest: null,
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
    };
    versionRef.value = '1.4.0-beta.1';

    const status = manager.getStatus();
    expect(status!.app.current).toBe('1.4.0-beta.1');
    expect(status!.app.updateAvailable).toBe(false);
  });

  it('flips updateAvailable to false when persisted latest is missing (older-shape pre-fix record)', () => {
    // Defend against a partially-shaped persisted record from a version
    // before this fix landed: only `current` and `updateAvailable: true`,
    // no `latest`. The re-derivation must not trust the stale boolean.
    store.data['updates.lastStatus'] = {
      lastChecked: '2026-04-25T00:00:00.000Z',
      app: {
        current: '1.3.2',
        // latest: null — pre-fix shape may have stored null/undefined here
        latest: null,
        updateAvailable: true,
        error: null,
        releaseNotes: null,
      },
      server: {
        current: null,
        latest: null,
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
    } as unknown as Record<string, unknown>;
    versionRef.value = '1.3.3';

    const status = manager.getStatus();
    expect(status!.app.current).toBe('1.3.3');
    expect(status!.app.updateAvailable).toBe(false);
  });

  it('passes the server slice through unchanged (server staleness is out of scope)', () => {
    store.data['updates.lastStatus'] = {
      lastChecked: '2026-04-25T00:00:00.000Z',
      app: {
        current: '1.3.2',
        latest: '1.3.3',
        updateAvailable: true,
        error: null,
        releaseNotes: null,
      },
      server: {
        current: '0.9.0',
        latest: '1.0.0',
        updateAvailable: true,
        error: 'cached error',
        releaseNotes: null,
      },
    };
    versionRef.value = '1.3.3';

    const status = manager.getStatus();
    expect(status!.server).toEqual({
      current: '0.9.0',
      latest: '1.0.0',
      updateAvailable: true,
      error: 'cached error',
      releaseNotes: null,
    });
  });
});
