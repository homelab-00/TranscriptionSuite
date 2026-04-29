// @vitest-environment node

/**
 * GPU preflight — validates the cheap subset of scripts/diagnose-gpu.sh that
 * runs at dashboard startup. Mirrors the dockerManagerVulkanPreflight test
 * pattern: the function under test is pure (all OS access is injected) and
 * returns a structured result the UI renders.
 */

import { describe, it, expect, vi } from 'vitest';

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

import { validateGpuPreflight } from '../dockerManager.js';

interface Env {
  cdiExists: boolean;
  cdiMtime: number;
  driverMtime: number;
  charSymlinks: string[];
  lsmodOutput: string;
}

function makeDeps(env: Env) {
  return {
    fsExists: (p: string) => {
      if (p === '/etc/cdi/nvidia.yaml') return env.cdiExists;
      if (p === '/dev/char') return true;
      return false;
    },
    readDir: (p: string) => {
      if (p === '/dev/char') return env.charSymlinks;
      return [];
    },
    statMtime: (p: string) => {
      if (p === '/etc/cdi/nvidia.yaml') return env.cdiExists ? env.cdiMtime : null;
      if (p.includes('/lib/modules')) return env.driverMtime;
      return null;
    },
    runLsmod: () => env.lsmodOutput,
  };
}

const healthyEnv: Env = {
  cdiExists: true,
  cdiMtime: 2_000_000_000,
  driverMtime: 1_000_000_000,
  charSymlinks: ['195:0', '195:255', '512:0'],
  lsmodOutput: 'nvidia\nnvidia_modeset\nnvidia_uvm\nnvidia_drm\n',
};

describe('validateGpuPreflight', () => {
  it('non-Linux platform: returns status=unknown, no checks run', () => {
    const deps = makeDeps(healthyEnv);
    const result = validateGpuPreflight('darwin', deps);
    expect(result.status).toBe('unknown');
    expect(result.checks).toEqual([]);
  });

  it('Windows: returns status=unknown, no checks run', () => {
    const deps = makeDeps(healthyEnv);
    const result = validateGpuPreflight('win32', deps);
    expect(result.status).toBe('unknown');
    expect(result.checks).toEqual([]);
  });

  it('Linux + healthy environment: status=healthy, all checks pass', () => {
    const result = validateGpuPreflight('linux', makeDeps(healthyEnv));
    expect(result.status).toBe('healthy');
    expect(result.checks.every((c) => c.pass)).toBe(true);
    expect(result.checks.map((c) => c.name)).toEqual([
      'CDI spec exists',
      'CDI spec newer than driver',
      '/dev/char NVIDIA symlinks',
      'nvidia_uvm module loaded',
    ]);
  });

  it('Linux + missing /dev/char symlinks: status=warning, fixCommand provided', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, charSymlinks: ['512:0', '999:1'] }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === '/dev/char NVIDIA symlinks');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk system create-dev-char-symlinks/);
  });

  it('Linux + stale CDI spec: status=warning with regenerate command', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, cdiMtime: 500_000_000, driverMtime: 1_000_000_000 }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk cdi generate/);
  });

  it('Linux + missing CDI spec: status=warning, generate command shown', () => {
    const result = validateGpuPreflight('linux', makeDeps({ ...healthyEnv, cdiExists: false }));
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'CDI spec exists');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk cdi generate/);
    // The "newer than driver" check is skipped (passes vacuously) when the spec is missing.
    const driverCheck = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(driverCheck?.pass).toBe(true);
  });

  it('Linux + nvidia_uvm not loaded: status=warning, modprobe command shown', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, lsmodOutput: 'nvidia\nnvidia_modeset\nnvidia_drm\n' }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'nvidia_uvm module loaded');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/modprobe nvidia_uvm/);
  });

  it('Linux + missing driver mtime info: skips comparison, no warning', () => {
    const deps = {
      ...makeDeps(healthyEnv),
      statMtime: (p: string) => {
        if (p === '/etc/cdi/nvidia.yaml') return 2_000_000_000;
        return null; // driver path not located
      },
    };
    const result = validateGpuPreflight('linux', deps);
    const driverCheck = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(driverCheck?.pass).toBe(true); // conservative: skip rather than false-warn
  });
});
