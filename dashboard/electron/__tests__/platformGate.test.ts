// @vitest-environment node

/**
 * platformGate — install-strategy resolution matrix.
 *
 * Drives every row from the I/O matrix in
 *   _bmad-output/implementation-artifacts/spec-in-app-update-m7-platforms.md
 * by injecting `fsAccess` so every branch is exercised without touching disk.
 */

import { describe, it, expect, vi } from 'vitest';
import { resolveInstallStrategy } from '../platformGate.js';

describe('resolveInstallStrategy', () => {
  describe('darwin', () => {
    it('always returns manual-download with macos-unsigned reason', async () => {
      const result = await resolveInstallStrategy({ platform: 'darwin' });
      expect(result).toEqual({ strategy: 'manual-download', reason: 'macos-unsigned' });
    });

    it('ignores appImagePath on darwin (still macos-unsigned)', async () => {
      const fsAccess = vi.fn(() => Promise.resolve());
      const result = await resolveInstallStrategy({
        platform: 'darwin',
        appImagePath: '/Applications/foo.app',
        fsAccess,
      });
      expect(result.strategy).toBe('manual-download');
      expect(result.reason).toBe('macos-unsigned');
      expect(fsAccess).not.toHaveBeenCalled();
    });
  });

  describe('win32', () => {
    it('always returns electron-updater (no reason)', async () => {
      const result = await resolveInstallStrategy({ platform: 'win32' });
      expect(result).toEqual({ strategy: 'electron-updater' });
    });

    it('ignores appImagePath on win32', async () => {
      const fsAccess = vi.fn(() => Promise.resolve());
      const result = await resolveInstallStrategy({
        platform: 'win32',
        appImagePath: '/some/path',
        fsAccess,
      });
      expect(result.strategy).toBe('electron-updater');
      expect(fsAccess).not.toHaveBeenCalled();
    });
  });

  describe('linux', () => {
    it('returns electron-updater when APPIMAGE is set and writable', async () => {
      const fsAccess = vi.fn(() => Promise.resolve());
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/home/user/Applications/foo.AppImage',
        fsAccess,
      });
      expect(result).toEqual({ strategy: 'electron-updater' });
      expect(fsAccess).toHaveBeenCalledWith(
        '/home/user/Applications/foo.AppImage',
        expect.any(Number),
      );
    });

    it('returns manual-download when APPIMAGE exists but is not writable', async () => {
      const fsAccess = vi.fn(() => Promise.reject(new Error('EACCES: permission denied')));
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/opt/TranscriptionSuite.AppImage',
        fsAccess,
      });
      expect(result).toEqual({
        strategy: 'manual-download',
        reason: 'appimage-not-writable',
      });
    });

    it('returns manual-download with appimage-missing when APPIMAGE is absent', async () => {
      const fsAccess = vi.fn(() => Promise.resolve());
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: undefined,
        fsAccess,
      });
      expect(result).toEqual({ strategy: 'manual-download', reason: 'appimage-missing' });
      expect(fsAccess).not.toHaveBeenCalled();
    });

    it('returns manual-download with appimage-missing when APPIMAGE is null', async () => {
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: null,
      });
      expect(result).toEqual({ strategy: 'manual-download', reason: 'appimage-missing' });
    });

    it('returns manual-download with appimage-missing when APPIMAGE is empty string', async () => {
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '',
      });
      expect(result).toEqual({ strategy: 'manual-download', reason: 'appimage-missing' });
    });

    it('treats any fsAccess rejection as not-writable (fail-closed)', async () => {
      const fsAccess = vi.fn(() => Promise.reject(new Error('weird FS error')));
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/some/path',
        fsAccess,
      });
      expect(result.strategy).toBe('manual-download');
      expect(result.reason).toBe('appimage-not-writable');
    });

    it('checks parent directory writability (rename target requirement)', async () => {
      // electron-updater does AppImage replacement via rename() in the parent
      // dir, so a writable file in a read-only parent dir must fail-closed.
      const fsAccess = vi.fn((p: string) => {
        if (p === '/opt/foo/TranscriptionSuite.AppImage') return Promise.resolve();
        if (p === '/opt/foo') return Promise.reject(new Error('EACCES on dir'));
        throw new Error('unexpected path: ' + p);
      });
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/opt/foo/TranscriptionSuite.AppImage',
        fsAccess,
      });
      expect(result).toEqual({
        strategy: 'manual-download',
        reason: 'appimage-not-writable',
      });
    });

    it('requires BOTH file AND parent dir writable for electron-updater path', async () => {
      const calls: string[] = [];
      const fsAccess = vi.fn((p: string) => {
        calls.push(p);
        return Promise.resolve();
      });
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/home/user/Apps/TranscriptionSuite.AppImage',
        fsAccess,
      });
      expect(result).toEqual({ strategy: 'electron-updater' });
      // Both the file and its parent directory were probed.
      expect(calls).toContain('/home/user/Apps/TranscriptionSuite.AppImage');
      expect(calls).toContain('/home/user/Apps');
    });
  });

  describe('unsupported platforms', () => {
    it('returns manual-download with unsupported-platform reason', async () => {
      const result = await resolveInstallStrategy({
        platform: 'freebsd' as NodeJS.Platform,
      });
      expect(result).toEqual({
        strategy: 'manual-download',
        reason: 'unsupported-platform',
      });
    });

    it('handles aix (rare but valid NodeJS.Platform value)', async () => {
      const result = await resolveInstallStrategy({ platform: 'aix' });
      expect(result.strategy).toBe('manual-download');
      expect(result.reason).toBe('unsupported-platform');
    });
  });

  describe('default fsAccess', () => {
    it('uses fs.promises.access(W_OK) when fsAccess is omitted', async () => {
      // We can't easily mock the import without polluting other tests; instead
      // verify behavior by passing a path that definitely doesn't exist —
      // the default fsAccess should reject and we get appimage-not-writable.
      const result = await resolveInstallStrategy({
        platform: 'linux',
        appImagePath: '/nonexistent/path/that/will/never/exist/__m7__test__.AppImage',
      });
      expect(result).toEqual({
        strategy: 'manual-download',
        reason: 'appimage-not-writable',
      });
    });
  });
});
