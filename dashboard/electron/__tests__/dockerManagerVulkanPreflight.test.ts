// @vitest-environment node

/**
 * GH-101 — Vulkan pre-flight guard
 *
 * Tests that checkVulkanSupport() returns the correct error (or null) for
 * every combination of host platform and DRI device presence. The guard
 * protects against the cryptic Docker daemon error
 * `error gathering device information while adding custom device "/dev/dri"`
 * that surfaces on Windows/macOS where Docker Desktop's Linux VM has no
 * /dev/dri passthrough, and on Linux hosts without an AMD/Intel render node
 * (typical of WSL2 or systems missing kernel driver support).
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

import { checkVulkanSupport } from '../dockerManager.js';

function existsFor(present: ReadonlySet<string>): (p: string) => boolean {
  return (p: string) => present.has(p);
}

const fullDri = new Set(['/dev/dri', '/dev/dri/renderD128']);
const dirOnly = new Set(['/dev/dri']);
const renderOnly = new Set(['/dev/dri/renderD128']);
const nothing = new Set<string>();

describe('[GH-101] checkVulkanSupport', () => {
  it('Linux + full DRI: returns null (Vulkan viable)', () => {
    expect(checkVulkanSupport({ platform: 'linux', exists: existsFor(fullDri) })).toBeNull();
  });

  it('Linux + no DRI directory: returns DRI-missing message', () => {
    const err = checkVulkanSupport({ platform: 'linux', exists: existsFor(nothing) });
    expect(err).toMatch(/\/dev\/dri was not found/);
    expect(err).toMatch(/WSL2 or systems without AMD\/Intel GPU drivers/);
    expect(err).toMatch(/Switch the Runtime Profile to "CPU"/);
  });

  it('Linux + DRI directory but no renderD128: returns DRI-missing message', () => {
    const err = checkVulkanSupport({ platform: 'linux', exists: existsFor(dirOnly) });
    expect(err).toMatch(/\/dev\/dri was not found/);
  });

  it('Linux + renderD128 but no /dev/dri directory: returns DRI-missing message', () => {
    const err = checkVulkanSupport({ platform: 'linux', exists: existsFor(renderOnly) });
    expect(err).toMatch(/\/dev\/dri was not found/);
  });

  it('Windows: returns non-Linux message regardless of DRI predicate', () => {
    const err = checkVulkanSupport({ platform: 'win32', exists: existsFor(fullDri) });
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
    expect(err).toMatch(/Docker Desktop on Windows\/macOS/);
    expect(err).toMatch(/without \/dev\/dri GPU passthrough/);
    expect(err).toMatch(/CPU.*GPU \(CUDA\)/);
  });

  it('macOS: returns non-Linux message regardless of DRI predicate', () => {
    const err = checkVulkanSupport({ platform: 'darwin', exists: existsFor(fullDri) });
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
  });

  it('Non-Linux check runs before DRI check on Windows (no filesystem access)', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport({ platform: 'win32', exists });
    expect(exists).not.toHaveBeenCalled();
  });

  it('Non-Linux check runs before DRI check on macOS (no filesystem access)', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport({ platform: 'darwin', exists });
    expect(exists).not.toHaveBeenCalled();
  });

  it('Linux check does query the filesystem', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport({ platform: 'linux', exists });
    expect(exists).toHaveBeenCalledWith('/dev/dri');
    expect(exists).toHaveBeenCalledWith('/dev/dri/renderD128');
  });
});

describe('[GH-101 follow-up] checkVulkanSupport — vulkan-wsl2 profile', () => {
  const wslReady = {
    available: true,
    gpuPassthroughDetected: true,
  };
  const wslHyperV = {
    available: false,
    gpuPassthroughDetected: false,
    reason: 'Docker Desktop is using the Hyper-V backend, not WSL2.',
  };
  const wslAvailableNoGpu = {
    available: true,
    gpuPassthroughDetected: false,
    reason: '/dev/dxg unreachable from probe container.',
  };

  it('Win32 + WSL2 + GPU passthrough: returns null (vulkan-wsl2 viable)', () => {
    expect(
      checkVulkanSupport({
        platform: 'win32',
        exists: existsFor(nothing),
        wslSupport: wslReady,
        profile: 'vulkan-wsl2',
      }),
    ).toBeNull();
  });

  it('macOS rejects vulkan-wsl2 even with a positive wslSupport bag', () => {
    const err = checkVulkanSupport({
      platform: 'darwin',
      exists: existsFor(nothing),
      wslSupport: wslReady,
      profile: 'vulkan-wsl2',
    });
    expect(err).toMatch(/Vulkan WSL2 is an opt-in profile for Windows/);
  });

  it('Linux rejects vulkan-wsl2 (must use the standard "vulkan" profile)', () => {
    const err = checkVulkanSupport({
      platform: 'linux',
      exists: existsFor(fullDri),
      wslSupport: wslReady,
      profile: 'vulkan-wsl2',
    });
    expect(err).toMatch(/Vulkan WSL2 is an opt-in profile for Windows/);
  });

  it('Win32 + Hyper-V backend: rejects with reason from probe', () => {
    const err = checkVulkanSupport({
      platform: 'win32',
      exists: existsFor(nothing),
      wslSupport: wslHyperV,
      profile: 'vulkan-wsl2',
    });
    expect(err).toMatch(/Hyper-V backend/);
  });

  it('Win32 + WSL2 + no GPU passthrough: surfaces the probe reason verbatim', () => {
    const err = checkVulkanSupport({
      platform: 'win32',
      exists: existsFor(nothing),
      wslSupport: wslAvailableNoGpu,
      profile: 'vulkan-wsl2',
    });
    expect(err).toMatch(/\/dev\/dxg unreachable/);
  });

  it('Win32 + missing wslSupport object: rejects gracefully', () => {
    const err = checkVulkanSupport({
      platform: 'win32',
      exists: existsFor(nothing),
      profile: 'vulkan-wsl2',
    });
    expect(err).toMatch(/Docker Desktop is not running with the WSL2 backend/);
  });

  it('vulkan-wsl2 branch never queries the filesystem (no /dev/dri probe)', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport({
      platform: 'win32',
      exists,
      wslSupport: wslReady,
      profile: 'vulkan-wsl2',
    });
    expect(exists).not.toHaveBeenCalled();
  });

  it('Linux Vulkan path is unchanged (wslSupport ignored when profile === "vulkan")', () => {
    expect(
      checkVulkanSupport({
        platform: 'linux',
        exists: existsFor(fullDri),
        wslSupport: wslHyperV,
        profile: 'vulkan',
      }),
    ).toBeNull();
  });

  it('default profile is "vulkan" when omitted from options (back-compat with v1.3.4 callers)', () => {
    // No profile field → vulkan branch — Linux + DRI present should pass.
    expect(checkVulkanSupport({ platform: 'linux', exists: existsFor(fullDri) })).toBeNull();
    // No profile field → vulkan branch — Win32 should reject with Linux-only message.
    const err = checkVulkanSupport({ platform: 'win32', exists: existsFor(fullDri) });
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
  });

  it('Win32 + profile="vulkan" + wslSupport set: still rejects with Linux-only message (wslSupport ignored)', () => {
    // Project-context invariant: vulkan-wsl2 NEVER auto-selected. The
    // existing 'vulkan' profile semantics must not change just because the
    // caller happens to pass a positive wslSupport bag — that bag is for
    // the 'vulkan-wsl2' branch only.
    const err = checkVulkanSupport({
      platform: 'win32',
      exists: existsFor(nothing),
      wslSupport: wslReady,
      profile: 'vulkan',
    });
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
  });

  it('darwin + profile="vulkan" still rejects with Linux-only message after the refactor', () => {
    // Pins the legacy v1.3.4 darwin behavior. Reorderings in the new branch
    // structure could regress this if someone moves the platform check into
    // the wrong branch.
    const err = checkVulkanSupport({ platform: 'darwin', exists: existsFor(fullDri) });
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
  });
});
