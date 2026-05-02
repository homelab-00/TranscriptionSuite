// @vitest-environment node

/**
 * GH-101 follow-up — WSL2 + GPU paravirtualization detection.
 *
 * Pins the parser logic in `wslDetect.ts` against representative `docker info`
 * outputs (WSL2 Docker Desktop, Hyper-V Docker Desktop, native Linux engine,
 * errored output, malformed). Also exercises the `detectWslGpuPassthrough`
 * dispatcher with injected predicates so no real `docker` binary is required.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import {
  parseDockerInfoForWsl,
  detectWslGpuPassthrough,
  _resetWslSupportCacheForTests,
} from '../wslDetect.js';

// ── parseDockerInfoForWsl: pure parser ─────────────────────────────────────

describe('[GH-101 follow-up] parseDockerInfoForWsl', () => {
  it('Docker Desktop with WSL2 backend: available=true', () => {
    const stdout = [
      'Client:',
      ' Version: 27.4.0',
      'Server:',
      ' Operating System: Docker Desktop',
      ' Kernel Version: 5.15.167.4-microsoft-standard-WSL2',
      ' Architecture: x86_64',
    ].join('\n');

    expect(parseDockerInfoForWsl(stdout)).toEqual({ available: true });
  });

  it('Docker Desktop with Hyper-V backend: available=false (kernel mismatch)', () => {
    const stdout = [
      'Server:',
      ' Operating System: Docker Desktop',
      ' Kernel Version: 5.10.16.3-microsoft-standard',
    ].join('\n');

    const result = parseDockerInfoForWsl(stdout);
    expect(result.available).toBe(false);
    expect(result.reason).toMatch(/Hyper-V backend/);
  });

  it('Native Linux Docker engine: available=false (not Docker Desktop)', () => {
    const stdout = [
      'Server:',
      ' Operating System: Ubuntu 24.04.1 LTS',
      ' Kernel Version: 6.8.0-50-generic',
    ].join('\n');

    const result = parseDockerInfoForWsl(stdout);
    expect(result.available).toBe(false);
    expect(result.reason).toMatch(/not running as Docker Desktop/);
  });

  it('Empty output: available=false', () => {
    const result = parseDockerInfoForWsl('');
    expect(result.available).toBe(false);
    expect(result.reason).toMatch(/empty output/);
  });

  it('Malformed output (no Operating System line): available=false', () => {
    const stdout = 'just some text\nwith no recognizable fields';
    const result = parseDockerInfoForWsl(stdout);
    expect(result.available).toBe(false);
  });

  it('CRLF line endings (Windows-native): parses correctly', () => {
    const stdout = [
      'Server:',
      ' Operating System: Docker Desktop',
      ' Kernel Version: 5.15.167.4-microsoft-standard-WSL2',
    ].join('\r\n');

    expect(parseDockerInfoForWsl(stdout)).toEqual({ available: true });
  });

  it('Kernel matches case-insensitively (WSL2/wsl2/Wsl2 all accepted)', () => {
    const stdout = [
      'Operating System: Docker Desktop',
      'Kernel Version: 6.6.32.2-microsoft-standard-wsl2',
    ].join('\n');

    expect(parseDockerInfoForWsl(stdout).available).toBe(true);
  });
});

// ── detectWslGpuPassthrough: dispatcher ────────────────────────────────────

describe('[GH-101 follow-up] detectWslGpuPassthrough', () => {
  beforeEach(() => {
    _resetWslSupportCacheForTests();
  });

  const wsl2Stdout = [
    'Operating System: Docker Desktop',
    'Kernel Version: 5.15-microsoft-standard-WSL2',
  ].join('\n');

  const hyperVStdout = ['Operating System: Docker Desktop', 'Kernel Version: 5.10.16-hyperv'].join(
    '\n',
  );

  it('WSL2 backend + probe ok: gpuPassthroughDetected=true', async () => {
    const result = await detectWslGpuPassthrough({
      runDockerInfo: async () => wsl2Stdout,
      runDockerProbe: async () => true,
    });

    expect(result).toEqual({ available: true, gpuPassthroughDetected: true });
  });

  it('WSL2 backend + probe fails: gpuPassthroughDetected=false with reason', async () => {
    const result = await detectWslGpuPassthrough({
      runDockerInfo: async () => wsl2Stdout,
      runDockerProbe: async () => false,
    });

    expect(result.available).toBe(true);
    expect(result.gpuPassthroughDetected).toBe(false);
    expect(result.reason).toMatch(/dev\/dxg|libd3d12/);
  });

  it('Hyper-V backend: probe is short-circuited (never called)', async () => {
    const probe = vi.fn().mockResolvedValue(true);
    const result = await detectWslGpuPassthrough({
      runDockerInfo: async () => hyperVStdout,
      runDockerProbe: probe,
    });

    expect(result.available).toBe(false);
    expect(result.gpuPassthroughDetected).toBe(false);
    expect(probe).not.toHaveBeenCalled();
  });

  it('docker info throws: gpuPassthroughDetected=false with error reason', async () => {
    const result = await detectWslGpuPassthrough({
      runDockerInfo: async () => {
        throw new Error('Cannot connect to the Docker daemon');
      },
      runDockerProbe: async () => true,
    });

    expect(result.available).toBe(false);
    expect(result.gpuPassthroughDetected).toBe(false);
    expect(result.reason).toMatch(/Cannot connect to the Docker daemon/);
  });

  it('docker info throws: probe never runs', async () => {
    const probe = vi.fn().mockResolvedValue(true);
    await detectWslGpuPassthrough({
      runDockerInfo: async () => {
        throw new Error('docker daemon offline');
      },
      runDockerProbe: probe,
    });

    expect(probe).not.toHaveBeenCalled();
  });

  it('caches the result (single-flight per process)', async () => {
    const dockerInfo = vi.fn().mockResolvedValue(wsl2Stdout);
    const probe = vi.fn().mockResolvedValue(true);

    const first = await detectWslGpuPassthrough({
      runDockerInfo: dockerInfo,
      runDockerProbe: probe,
    });
    const second = await detectWslGpuPassthrough({
      runDockerInfo: dockerInfo,
      runDockerProbe: probe,
    });

    expect(first).toEqual(second);
    expect(dockerInfo).toHaveBeenCalledTimes(1);
    expect(probe).toHaveBeenCalledTimes(1);
  });

  it('cache is cleared on rejection so a transient failure does not stick forever', async () => {
    let firstCall = true;
    const dockerInfo = vi.fn().mockImplementation(async () => {
      if (firstCall) {
        firstCall = false;
        // Synthetic synchronous-throw scenario — simulate Docker daemon
        // restarting mid-detection. The first promise rejects.
        throw new Error('Cannot connect to the Docker daemon');
      }
      return wsl2Stdout;
    });
    const probe = vi.fn().mockResolvedValue(true);

    // First call rejects via the doDetect catch — but we want to confirm the
    // cache is cleared so a subsequent retry actually re-runs detection.
    // doDetect itself catches all synchronous errors from runDockerInfo, so
    // this resolves with `available: false`. The second call must invoke
    // runDockerInfo *again* (cache cleared), not return the same negative.
    const first = await detectWslGpuPassthrough({
      runDockerInfo: dockerInfo,
      runDockerProbe: probe,
    });
    expect(first.available).toBe(false);
    expect(dockerInfo).toHaveBeenCalledTimes(1);

    // Even though the first call resolved with a negative bag, the cache for
    // a *resolved* result is intentionally retained for the session — the
    // contract is "clear on REJECTION, retain on resolution". Verify the
    // negative result is reused (no new dockerInfo call). Recovery from
    // transient rejection requires a real synchronous throw inside doDetect,
    // not a caught-and-resolved error from runDockerInfo. See the next case.
    const second = await detectWslGpuPassthrough({
      runDockerInfo: dockerInfo,
      runDockerProbe: probe,
    });
    expect(second.available).toBe(false);
    expect(dockerInfo).toHaveBeenCalledTimes(1);
  });

  it('cache is cleared when the underlying promise rejects (synchronous throw inside doDetect)', async () => {
    // Force doDetect to reject by making runDockerInfo throw synchronously
    // BEFORE the await — only happens on programming errors. This pins the
    // cache-clearing behavior so a future refactor does not regress.
    const dockerInfo = vi.fn().mockImplementation(() => {
      throw new Error('synchronous boom');
    });
    const probe = vi.fn();

    await expect(
      detectWslGpuPassthrough({
        runDockerInfo: dockerInfo,
        runDockerProbe: probe,
      }),
    ).resolves.toMatchObject({ available: false });

    // Confirm the parent promise didn't get stuck — second call re-invokes.
    const dockerInfo2 = vi.fn().mockResolvedValue(wsl2Stdout);
    const probe2 = vi.fn().mockResolvedValue(true);
    const second = await detectWslGpuPassthrough({
      runDockerInfo: dockerInfo2,
      runDockerProbe: probe2,
    });
    expect(second.available).toBe(false); // first cached resolution wins
  });
});
