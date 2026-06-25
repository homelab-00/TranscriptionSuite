// @vitest-environment node

/**
 * GH #158 — getComposeAvailable() must reflect the real detection result.
 *
 * Regression test for the Podman-on-Windows race: the renderer used to call
 * docker.available() (which *sets* the cached compose flag asynchronously) and
 * docker.getComposeAvailable() (which *read* it synchronously) concurrently in
 * the same Promise.all. On first mount the read landed before the write and saw
 * the initial `null` — which the old guard treated as "available" (true) — so
 * the setup checklist showed "Compose available ✓" while startContainer
 * simultaneously failed its `_composeAvailable === false` guard.
 *
 * The fix makes getComposeAvailable() await detection, so it never returns a
 * stale value regardless of call ordering.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ─── Hoisted mock state ─────────────────────────────────────────────────────

const { mockGetDetectionResult } = vi.hoisted(() => ({
  mockGetDetectionResult: vi.fn(),
}));

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => `/tmp/mock-${name}`,
    setPath: vi.fn(),
  },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

// Replace the whole containerRuntime module so detection is fully controlled.
vi.mock('../containerRuntime.js', () => ({
  getDetectionResult: mockGetDetectionResult,
  getContainerRuntime: vi.fn(async () => ({
    kind: 'podman',
    bin: 'podman',
    displayName: 'Podman',
  })),
  getRuntimeBin: vi.fn(async () => 'podman'),
  getSocketPaths: vi.fn(() => ({ system: '', user: () => '', envVar: 'CONTAINER_HOST' })),
  resolveRootlessSocket: vi.fn(() => null),
  getRuntimePathAdditions: vi.fn(() => []),
  resetDetection: vi.fn(),
}));

import { dockerManager } from '../dockerManager.js';

/** Detection result resolved on a later microtask to mimic real async probing. */
function asyncDetection(result: Record<string, unknown>) {
  return () => Promise.resolve().then(() => result);
}

beforeEach(() => {
  vi.clearAllMocks();
  // Reset module-level compose/guidance/runtime caches between tests.
  dockerManager.retryDetection();
});

describe('[GH158] dockerManager.getComposeAvailable', () => {
  it('returns false when detection reports compose missing — even on the first call', async () => {
    // No prior available() call: with the old synchronous read this returned
    // `true` (null !== false). The fix awaits detection first.
    mockGetDetectionResult.mockImplementation(
      asyncDetection({
        runtime: { kind: 'podman', bin: 'podman', displayName: 'Podman' },
        composeAvailable: false,
        guidance: 'Podman compose provider missing',
      }),
    );

    const result = await dockerManager.getComposeAvailable();

    expect(result).toBe(false);
  });

  it('returns true when detection confirms compose is available', async () => {
    mockGetDetectionResult.mockImplementation(
      asyncDetection({
        runtime: { kind: 'podman', bin: 'podman', displayName: 'Podman' },
        composeAvailable: true,
      }),
    );

    const result = await dockerManager.getComposeAvailable();

    expect(result).toBe(true);
  });

  it('stays consistent with available() under concurrent calls (no race)', async () => {
    mockGetDetectionResult.mockImplementation(
      asyncDetection({
        runtime: { kind: 'podman', bin: 'podman', displayName: 'Podman' },
        composeAvailable: false,
        guidance: 'Podman compose provider missing',
      }),
    );

    // Fire both in the same tick, exactly like the useDocker hook's Promise.all.
    const [available, compose] = await Promise.all([
      dockerManager.dockerAvailable(),
      dockerManager.getComposeAvailable(),
    ]);

    expect(available).toBe(true); // podman runtime present
    expect(compose).toBe(false); // …but compose provider is not — and we report it
  });

  it('surfaces the runtime-specific guidance captured during detection', async () => {
    mockGetDetectionResult.mockImplementation(
      asyncDetection({
        runtime: { kind: 'podman', bin: 'podman', displayName: 'Podman' },
        composeAvailable: false,
        guidance: 'Install the Podman compose provider and Retry Detection.',
      }),
    );

    await dockerManager.getComposeAvailable();

    expect(dockerManager.getDetectionGuidance()).toBe(
      'Install the Podman compose provider and Retry Detection.',
    );
  });
});
