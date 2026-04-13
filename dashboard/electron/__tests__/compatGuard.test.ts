// @vitest-environment node

/**
 * compatGuard — manifest fetch + semver compat guard tests.
 *
 * Drives every I/O matrix row from
 *   _bmad-output/implementation-artifacts/spec-in-app-update-m4-compat-guard.md
 * via stubbed `fetch` responses (three endpoints: releases/latest, manifest
 * asset, admin/status) and a fake electron-store.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type Store from 'electron-store';

import { CompatGuard, type Manifest } from '../compatGuard.js';

// ─── Fakes ──────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyStore = Store<any>;

interface FakeStoreHandle {
  store: AnyStore;
  data: Record<string, unknown>;
  getSpy: ReturnType<typeof vi.fn>;
  setSpy: ReturnType<typeof vi.fn>;
}

function makeStore(overrides: Record<string, unknown> = {}): FakeStoreHandle {
  const defaults: Record<string, unknown> = {
    'connection.useRemote': false,
    'connection.remoteProfile': 'tailscale',
    'connection.remoteHost': '',
    'connection.lanHost': '',
    'connection.localHost': 'localhost',
    'connection.port': 9786,
    'connection.useHttps': false,
    'connection.authToken': '',
    'server.host': 'localhost',
    'server.port': 9786,
    'server.https': false,
  };
  const data: Record<string, unknown> = { ...defaults, ...overrides };
  const getSpy = vi.fn((key: string) => data[key]);
  const setSpy = vi.fn((key: string, value: unknown) => {
    data[key] = value;
  });
  const store = { get: getSpy, set: setSpy } as unknown as AnyStore;
  return { store, data, getSpy, setSpy };
}

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

function malformedJsonResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => {
      throw new SyntaxError('bad json');
    },
  } as unknown as Response;
}

const STABLE_MANIFEST: Manifest = {
  version: '1.3.3',
  compatibleServerRange: '>=1.0.0 <2.0.0',
  sha256: { 'TranscriptionSuite.AppImage': 'a'.repeat(64) },
  releaseType: 'stable',
};

const MANIFEST_URL =
  'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.3/manifest.json';

function releasesPayloadWithManifest(url = MANIFEST_URL) {
  return {
    tag_name: 'v1.3.3',
    assets: [
      { name: 'TranscriptionSuite.AppImage', browser_download_url: 'https://…' },
      { name: 'manifest.json', browser_download_url: url },
    ],
  };
}

function silentLogger() {
  return {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
}

// ─── Tests ──────────────────────────────────────────────────────────────

describe('CompatGuard', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
  });

  function buildGuard(storeOverrides: Record<string, unknown> = {}) {
    const { store, data, setSpy } = makeStore(storeOverrides);
    const guard = new CompatGuard({
      store,
      fetchImpl: fetchMock as unknown as typeof fetch,
      logger: silentLogger(),
    });
    return { guard, store, data, setSpy };
  }

  it('returns compatible when semver range is satisfied (local Docker)', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();

    expect(result).toEqual({
      result: 'compatible',
      manifest: STABLE_MANIFEST,
      serverVersion: '1.4.2',
    });
    expect(setSpy).toHaveBeenCalledWith('updates.lastManifest', STABLE_MANIFEST);
  });

  it('returns incompatible with deployment=local when server is behind range', async () => {
    const strictManifest: Manifest = { ...STABLE_MANIFEST, compatibleServerRange: '>=99.0.0' };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(strictManifest))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();

    expect(result).toEqual({
      result: 'incompatible',
      manifest: strictManifest,
      serverVersion: '1.4.2',
      compatibleRange: '>=99.0.0',
      deployment: 'local',
    });
    expect(setSpy).toHaveBeenCalledWith('updates.lastManifest', strictManifest);
  });

  it('returns incompatible with deployment=remote when useRemote=true', async () => {
    const strictManifest: Manifest = { ...STABLE_MANIFEST, compatibleServerRange: '>=99.0.0' };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(strictManifest))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard } = buildGuard({
      'connection.useRemote': true,
      'connection.remoteHost': 'example.ts.net',
    });
    const result = await guard.check();

    expect(result).toMatchObject({ result: 'incompatible', deployment: 'remote' });
  });

  it('returns unknown/no-manifest when asset is missing from release', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        assets: [{ name: 'TranscriptionSuite.AppImage', browser_download_url: 'https://…' }],
      }),
    );

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();

    expect(result).toEqual({ result: 'unknown', reason: 'no-manifest' });
    expect(setSpy).not.toHaveBeenCalled();
    // Only ONE network call — releases/latest — should fire when no manifest
    // asset is listed.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns unknown/manifest-fetch-failed when releases/latest returns 5xx', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, { ok: false, status: 503 }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();

    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-fetch-failed');
      expect(result.detail).toContain('503');
    }
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('returns unknown/manifest-fetch-failed when releases/latest fetch throws', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ENETUNREACH'));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('manifest-fetch-failed');
  });

  it('returns unknown/manifest-fetch-failed when the manifest asset fetch fails', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse({}, { ok: false, status: 404 }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-fetch-failed');
      expect(result.detail).toContain('404');
    }
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('returns unknown/manifest-parse-error when JSON body is malformed', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(malformedJsonResponse());

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('manifest-parse-error');
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('returns unknown/manifest-parse-error when shape is wrong (missing fields)', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse({ version: '1.3.3' })); // missing everything else

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-parse-error');
      expect(result.detail).toBe('shape-mismatch');
    }
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('returns unknown/server-version-unavailable when admin/status 5xx (and still persists manifest)', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({}, { ok: false, status: 503 }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('server-version-unavailable');
    expect(setSpy).toHaveBeenCalledWith('updates.lastManifest', STABLE_MANIFEST);
  });

  it('returns unknown/server-version-unavailable when admin/status omits .version', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running' })); // no version field

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('server-version-unavailable');
  });

  it('returns unknown/server-version-unavailable when .version is not valid semver', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: 'x.y' }));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('server-version-unavailable');
      expect(result.detail).toContain('x.y');
    }
  });

  it('returns unknown/invalid-range when compatibleServerRange is garbage', async () => {
    const brokenManifest: Manifest = { ...STABLE_MANIFEST, compatibleServerRange: 'not-a-range' };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(brokenManifest))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('invalid-range');
      expect(result.detail).toBe('not-a-range');
    }
    expect(setSpy).toHaveBeenCalledWith('updates.lastManifest', brokenManifest);
  });

  it('single-flights concurrent check() calls (one pair of fetches)', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard } = buildGuard();
    const [a, b] = await Promise.all([guard.check(), guard.check()]);
    expect(a).toEqual(b);
    // Three HTTP calls total (releases/latest + manifest asset + admin/status) —
    // NOT six. A second `check()` while the first is in flight shares the
    // same in-flight Promise.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('sends Authorization header when connection.authToken is set', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard } = buildGuard({ 'connection.authToken': 'secret-token' });
    await guard.check();

    const adminCall = fetchMock.mock.calls[2];
    expect(adminCall[0]).toContain('/api/admin/status');
    expect(adminCall[1]?.headers).toMatchObject({ Authorization: 'Bearer secret-token' });
  });

  it('does not persist manifest after destroy() mid-fetch', async () => {
    // Resolve fetches but destroy between manifest-parse and server-probe.
    // The spec requires: no persistence after destroy. We verify by destroying
    // before doCheck reaches the persist line — the simplest way is to destroy
    // immediately after the manifest fetch resolves but before the server fetch.
    // We simulate by making the third fetch never resolve and destroying after
    // the first two have completed. But since the persist happens between those
    // two steps, a simpler approach: throw from the manifest fetch's .json() in
    // a way that lets us observe destroy timing. Instead we test the simpler
    // "destroy flips the flag" invariant: after destroy(), the run returns
    // unknown/manifest-fetch-failed with detail=destroyed, and does not persist.
    let destroyNow = () => {};
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockImplementationOnce(async () => {
        destroyNow();
        return jsonResponse(STABLE_MANIFEST);
      });

    const { guard, setSpy } = buildGuard();
    destroyNow = () => guard.destroy();
    const result = await guard.check();
    expect(result).toEqual({
      result: 'unknown',
      reason: 'manifest-fetch-failed',
      detail: 'destroyed',
    });
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('getLastManifest returns persisted manifest from store', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse({ status: 'running', version: '1.4.2' }));

    const { guard } = buildGuard();
    await guard.check();
    expect(guard.getLastManifest()).toEqual(STABLE_MANIFEST);
  });

  it('getLastManifest returns null when store has no manifest', () => {
    const { guard } = buildGuard();
    expect(guard.getLastManifest()).toBeNull();
  });

  it('getLastManifest returns null when stored value has wrong shape', () => {
    const { guard } = buildGuard({ 'updates.lastManifest': { version: 'x' } });
    expect(guard.getLastManifest()).toBeNull();
  });

  // ─── Post-review hardening patches ────────────────────────────────────

  it('isManifest rejects sha256 entries whose value is not 64-char lowercase hex', async () => {
    const bad = { ...STABLE_MANIFEST, sha256: { 'file.AppImage': 'NOT-HEX' } };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(bad));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-parse-error');
      expect(result.detail).toBe('shape-mismatch');
    }
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('isManifest rejects sha256 with zero entries (empty object)', async () => {
    const bad = { ...STABLE_MANIFEST, sha256: {} };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(bad));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('manifest-parse-error');
  });

  it('isManifest rejects sha256 with more than 32 entries (DoS defense)', async () => {
    const sha256: Record<string, string> = {};
    for (let i = 0; i < 33; i++) sha256[`bin-${i}`] = 'a'.repeat(64);
    const bad = { ...STABLE_MANIFEST, sha256 };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(bad));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('manifest-parse-error');
  });

  it('isManifest rejects manifest.version that is not valid semver', async () => {
    const bad = { ...STABLE_MANIFEST, version: 'not-semver' };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(bad));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('manifest-parse-error');
  });

  it('rejects manifest asset URLs outside the github host allow-list', async () => {
    const evil = releasesPayloadWithManifest('https://evil.example.com/manifest.json');
    fetchMock.mockResolvedValueOnce(jsonResponse(evil));

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-fetch-failed');
      expect(result.detail).toBe('asset-url-rejected');
    }
    // Only the releases/latest fetch should have fired.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('aborts when manifest asset content-length exceeds 1 MB', async () => {
    const giantResp = {
      ok: true,
      status: 200,
      headers: { get: (name: string) => (name === 'content-length' ? '2000000' : null) },
      json: async () => STABLE_MANIFEST,
    } as unknown as Response;

    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(giantResp);

    const { guard, setSpy } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') {
      expect(result.reason).toBe('manifest-fetch-failed');
      expect(result.detail).toBe('oversized');
    }
    expect(setSpy).not.toHaveBeenCalled();
  });

  it('tolerates releases payload where assets is not an array', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ assets: { not: 'an-array' } }));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result).toEqual({ result: 'unknown', reason: 'no-manifest' });
  });

  it('tolerates admin/status body that is null', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(releasesPayloadWithManifest()))
      .mockResolvedValueOnce(jsonResponse(STABLE_MANIFEST))
      .mockResolvedValueOnce(jsonResponse(null));

    const { guard } = buildGuard();
    const result = await guard.check();
    expect(result.result).toBe('unknown');
    if (result.result === 'unknown') expect(result.reason).toBe('server-version-unavailable');
  });

  it('check() after destroy() returns unknown/destroyed without issuing any fetch', async () => {
    const { guard } = buildGuard();
    guard.destroy();
    const result = await guard.check();
    expect(result).toEqual({
      result: 'unknown',
      reason: 'manifest-fetch-failed',
      detail: 'destroyed',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('getLastManifest returns null when store.get throws', () => {
    const throwingStore = {
      get: vi.fn(() => {
        throw new Error('store corrupted');
      }),
      set: vi.fn(),
    } as unknown as AnyStore;
    const guard = new CompatGuard({
      store: throwingStore,
      fetchImpl: fetchMock as unknown as typeof fetch,
      logger: silentLogger(),
    });
    expect(guard.getLastManifest()).toBeNull();
  });
});
