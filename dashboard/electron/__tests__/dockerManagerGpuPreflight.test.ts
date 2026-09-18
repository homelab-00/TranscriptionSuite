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
  /** Raw /etc/cdi/nvidia.yaml content; null = unreadable. */
  cdiContent: string | null;
  /** Host paths (as referenced by the CDI spec) that exist on disk. */
  existingPaths: string[];
}

function makeDeps(env: Env) {
  return {
    fsExists: (p: string) => {
      if (p === '/etc/cdi/nvidia.yaml') return env.cdiExists;
      if (p === '/dev/char') return true;
      return env.existingPaths.includes(p);
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
    readFile: (p: string) => (p === '/etc/cdi/nvidia.yaml' ? env.cdiContent : null),
  };
}

// Trimmed-down shape of a real `nvidia-ctk cdi generate` spec: a device node
// plus versioned library bind mounts, each with a hostPath/containerPath pair.
function cdiSpec(hostPaths: string[]): string {
  const mounts = hostPaths
    .map(
      (hp) =>
        `        - hostPath: ${hp}\n          containerPath: ${hp}\n          options:\n            - ro\n`,
    )
    .join('');
  return `cdiVersion: 0.5.0\nkind: nvidia.com/gpu\ncontainerEdits:\n    mounts:\n${mounts}`;
}

const LIB_GLX = '/usr/lib/libGLX_nvidia.so.615.71.09';
const LIB_EGL_WAYLAND = '/usr/lib/libnvidia-egl-wayland.so.1.1.21';
const LIB_EGL_WAYLAND2 = '/usr/lib/libnvidia-egl-wayland2.so.1.0.1';

const healthyEnv: Env = {
  cdiExists: true,
  cdiMtime: 2_000_000_000,
  driverMtime: 1_000_000_000,
  charSymlinks: ['195:0', '195:255', '512:0'],
  lsmodOutput: 'nvidia\nnvidia_modeset\nnvidia_uvm\nnvidia_drm\n',
  cdiContent: cdiSpec([LIB_GLX, LIB_EGL_WAYLAND, LIB_EGL_WAYLAND2]),
  existingPaths: [LIB_GLX, LIB_EGL_WAYLAND, LIB_EGL_WAYLAND2],
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
      'CDI spec host paths exist',
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

  // Regression: a distro hook rewrote the spec in place (driver version string
  // substitution) right after a driver upgrade, so its mtime looked fresh while
  // it still bind-mounted a library version that the same upgrade had removed.
  it('Linux + fresh-mtime spec referencing a removed library: status=warning, names the path', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, existingPaths: [LIB_GLX, LIB_EGL_WAYLAND2] }),
    );
    expect(result.status).toBe('warning');
    const mtimeCheck = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(mtimeCheck?.pass).toBe(true);
    const failed = result.checks.find((c) => c.name === 'CDI spec host paths exist');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk cdi generate/);
    expect(failed?.detail).toContain(LIB_EGL_WAYLAND);
  });

  it('Linux + several missing host paths: detail reports the first and how many more', () => {
    const result = validateGpuPreflight('linux', makeDeps({ ...healthyEnv, existingPaths: [] }));
    const failed = result.checks.find((c) => c.name === 'CDI spec host paths exist');
    expect(failed?.pass).toBe(false);
    expect(failed?.detail).toContain(LIB_GLX);
    expect(failed?.detail).toContain('2 more');
  });

  it('Linux + quoted hostPath values: quotes are stripped before the existence check', () => {
    const content = cdiSpec([`"${LIB_GLX}"`, `'${LIB_EGL_WAYLAND}'`]);
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, cdiContent: content, existingPaths: [LIB_GLX, LIB_EGL_WAYLAND] }),
    );
    const check = result.checks.find((c) => c.name === 'CDI spec host paths exist');
    expect(check?.pass).toBe(true);
  });

  it('Linux + missing CDI spec: host-path check passes vacuously (reported by check 1)', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, cdiExists: false, cdiContent: null }),
    );
    const check = result.checks.find((c) => c.name === 'CDI spec host paths exist');
    expect(check?.pass).toBe(true);
    expect(check?.detail).toBeUndefined();
  });

  it('Linux + unreadable CDI spec: skips host-path check, no warning', () => {
    const result = validateGpuPreflight('linux', makeDeps({ ...healthyEnv, cdiContent: null }));
    expect(result.status).toBe('healthy'); // conservative: skip rather than false-warn
  });
});
