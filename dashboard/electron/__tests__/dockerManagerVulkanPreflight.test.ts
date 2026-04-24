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
    expect(checkVulkanSupport('linux', existsFor(fullDri))).toBeNull();
  });

  it('Linux + no DRI directory: returns DRI-missing message', () => {
    const err = checkVulkanSupport('linux', existsFor(nothing));
    expect(err).toMatch(/\/dev\/dri was not found/);
    expect(err).toMatch(/WSL2 or systems without AMD\/Intel GPU drivers/);
    expect(err).toMatch(/Switch the Runtime Profile to "CPU"/);
  });

  it('Linux + DRI directory but no renderD128: returns DRI-missing message', () => {
    const err = checkVulkanSupport('linux', existsFor(dirOnly));
    expect(err).toMatch(/\/dev\/dri was not found/);
  });

  it('Linux + renderD128 but no /dev/dri directory: returns DRI-missing message', () => {
    const err = checkVulkanSupport('linux', existsFor(renderOnly));
    expect(err).toMatch(/\/dev\/dri was not found/);
  });

  it('Windows: returns non-Linux message regardless of DRI predicate', () => {
    const err = checkVulkanSupport('win32', existsFor(fullDri));
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
    expect(err).toMatch(/Docker Desktop on Windows\/macOS/);
    expect(err).toMatch(/without \/dev\/dri GPU passthrough/);
    expect(err).toMatch(/CPU.*GPU \(CUDA\)/);
  });

  it('macOS: returns non-Linux message regardless of DRI predicate', () => {
    const err = checkVulkanSupport('darwin', existsFor(fullDri));
    expect(err).toMatch(/Vulkan runtime is only supported on Linux/);
  });

  it('Non-Linux check runs before DRI check on Windows (no filesystem access)', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport('win32', exists);
    expect(exists).not.toHaveBeenCalled();
  });

  it('Non-Linux check runs before DRI check on macOS (no filesystem access)', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport('darwin', exists);
    expect(exists).not.toHaveBeenCalled();
  });

  it('Linux check does query the filesystem', () => {
    const exists = vi.fn().mockReturnValue(true);
    checkVulkanSupport('linux', exists);
    expect(exists).toHaveBeenCalledWith('/dev/dri');
    expect(exists).toHaveBeenCalledWith('/dev/dri/renderD128');
  });
});
