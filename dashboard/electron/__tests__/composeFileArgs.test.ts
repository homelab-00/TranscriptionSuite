// @vitest-environment node

/**
 * P1-DOCK-001 — Compose file selection: Linux/VM/GPU/Vulkan/Podman
 *
 * Tests that composeFileArgs() returns the correct layered compose file args
 * for each combination of platform, runtime profile, and GPU mode.
 *
 * 6 platform scenarios covering the full compose override matrix.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';

// Mock `electron` before importing the module under test — dockerManager.ts
// imports `app` at the top level.
vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => `/tmp/mock-${name}`,
    setPath: vi.fn(),
  },
}));

// Mock electron-store (imported transitively by dockerManager config readers)
vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

import { composeFileArgs } from '../dockerManager.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Extract just the filenames from the flat [-f, file, -f, file, ...] array. */
function extractFiles(args: string[]): string[] {
  return args.filter((_, i) => i % 2 === 1);
}

const originalPlatform = process.platform;

function setPlatform(platform: string): void {
  Object.defineProperty(process, 'platform', { value: platform, writable: true });
}

afterEach(() => {
  Object.defineProperty(process, 'platform', { value: originalPlatform, writable: true });
});

// ─── P1-DOCK-001: Compose File Selection ────────────────────────────────────

describe('[P1] composeFileArgs', () => {
  it('Linux + CPU: base + linux-host overlay', () => {
    setPlatform('linux');
    const args = composeFileArgs('cpu', 'docker', null);
    const files = extractFiles(args);

    expect(files).toEqual(['docker-compose.yml', 'docker-compose.linux-host.yml']);
  });

  it('Linux + GPU (Docker legacy): base + linux-host + gpu', () => {
    setPlatform('linux');
    const args = composeFileArgs('gpu', 'docker', 'legacy');
    const files = extractFiles(args);

    expect(files).toEqual([
      'docker-compose.yml',
      'docker-compose.linux-host.yml',
      'docker-compose.gpu.yml',
    ]);
  });

  it('Linux + GPU (Docker CDI): base + linux-host + gpu-cdi', () => {
    setPlatform('linux');
    const args = composeFileArgs('gpu', 'docker', 'cdi');
    const files = extractFiles(args);

    expect(files).toEqual([
      'docker-compose.yml',
      'docker-compose.linux-host.yml',
      'docker-compose.gpu-cdi.yml',
    ]);
  });

  it('Linux + GPU (Podman): base + linux-host + podman gpu', () => {
    setPlatform('linux');
    const args = composeFileArgs('gpu', 'podman', null);
    const files = extractFiles(args);

    expect(files).toEqual([
      'docker-compose.yml',
      'docker-compose.linux-host.yml',
      'podman-compose.gpu.yml',
    ]);
  });

  it('Desktop VM (macOS/Windows) + CPU: base + desktop-vm overlay', () => {
    setPlatform('darwin');
    const args = composeFileArgs('cpu', 'docker', null);
    const files = extractFiles(args);

    expect(files).toEqual(['docker-compose.yml', 'docker-compose.desktop-vm.yml']);

    // Same for Windows
    setPlatform('win32');
    const winArgs = composeFileArgs('cpu', 'docker', null);
    const winFiles = extractFiles(winArgs);

    expect(winFiles).toEqual(['docker-compose.yml', 'docker-compose.desktop-vm.yml']);
  });

  it('Linux + Vulkan: base + linux-host + vulkan sidecar', () => {
    setPlatform('linux');
    const args = composeFileArgs('vulkan', 'docker', null);
    const files = extractFiles(args);

    expect(files).toEqual([
      'docker-compose.yml',
      'docker-compose.linux-host.yml',
      'docker-compose.vulkan.yml',
    ]);
  });

  // ── GH-101 follow-up: Vulkan-WSL2 compose selection ─────────────────────

  it('Win32 + Vulkan-WSL2: base + desktop-vm + vulkan-wsl2 sidecar', () => {
    setPlatform('win32');
    const args = composeFileArgs('vulkan-wsl2', 'docker', null);
    const files = extractFiles(args);

    expect(files).toEqual([
      'docker-compose.yml',
      'docker-compose.desktop-vm.yml',
      'docker-compose.vulkan-wsl2.yml',
    ]);
  });

  it('Vulkan-WSL2 selects the WSL2 overlay (NOT the Linux-DRI overlay)', () => {
    setPlatform('win32');
    const files = extractFiles(composeFileArgs('vulkan-wsl2', 'docker', null));

    expect(files).toContain('docker-compose.vulkan-wsl2.yml');
    expect(files).not.toContain('docker-compose.vulkan.yml');
  });

  it('Vulkan (Linux-DRI) selects the Linux overlay (NOT the WSL2 overlay)', () => {
    setPlatform('linux');
    const files = extractFiles(composeFileArgs('vulkan', 'docker', null));

    expect(files).toContain('docker-compose.vulkan.yml');
    expect(files).not.toContain('docker-compose.vulkan-wsl2.yml');
  });

  it('Vulkan-WSL2 on Linux: defense-in-depth — overlay is NOT attached even if profile leaks', () => {
    setPlatform('linux');
    const files = extractFiles(composeFileArgs('vulkan-wsl2', 'docker', null));

    expect(files).not.toContain('docker-compose.vulkan-wsl2.yml');
    expect(files).not.toContain('docker-compose.vulkan.yml');
  });

  it('Vulkan-WSL2 on macOS: defense-in-depth — overlay is NOT attached even if profile leaks', () => {
    setPlatform('darwin');
    const files = extractFiles(composeFileArgs('vulkan-wsl2', 'docker', null));

    expect(files).not.toContain('docker-compose.vulkan-wsl2.yml');
  });

  // ── Output format tests ─────────────────────────────────────────────────

  it('returns flat [-f, file] pairs', () => {
    setPlatform('linux');
    const args = composeFileArgs('cpu', 'docker', null);

    // Every even index should be '-f'
    for (let i = 0; i < args.length; i += 2) {
      expect(args[i]).toBe('-f');
    }
    // Total length should be 2x the number of compose files
    expect(args.length % 2).toBe(0);
  });

  it('base compose file is always first', () => {
    setPlatform('linux');
    for (const profile of ['cpu', 'gpu', 'vulkan'] as const) {
      const args = composeFileArgs(profile, 'docker', 'legacy');
      expect(args[1]).toBe('docker-compose.yml');
    }
  });
});
