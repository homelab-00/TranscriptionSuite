// @vitest-environment node

/**
 * UpdateInstaller — state machine tests for the electron-updater wrapper.
 *
 * Drives each I/O matrix row from
 *   _bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md
 * via a fake AutoUpdater that mimics electron-updater's EventEmitter surface.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';

// ─── Mocks ──────────────────────────────────────────────────────────────

const { FakeCancellationToken } = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { EventEmitter: EE } = require('events') as typeof import('events');
  class FakeCancellationTokenImpl extends EE {
    cancelled = false;
    cancel(): void {
      this.cancelled = true;
      this.emit('cancel');
    }
  }
  return { FakeCancellationToken: FakeCancellationTokenImpl };
});

vi.mock('electron-updater', () => {
  // electron-updater is imported as a default export (see updateInstaller.ts
  // header). The mock must expose both the default payload (for the runtime
  // destructure) and the named shape for any type-only consumers.
  const payload = {
    autoUpdater: new EventEmitter(),
    CancellationToken: FakeCancellationToken,
  };
  return {
    default: payload,
    ...payload,
  };
});

type FakeCancellationToken = InstanceType<typeof FakeCancellationToken>;

import type { AutoUpdaterLike, UpdateInstallerLogger } from '../updateInstaller.js';
import { UpdateInstaller } from '../updateInstaller.js';
import type { InstallerStatus } from '../updateManager.js';

// ─── Helpers ────────────────────────────────────────────────────────────

interface FakeAutoUpdater extends AutoUpdaterLike {
  // Test-only hooks controlling the shape of checkForUpdates / downloadUpdate.
  __checkResult: unknown;
  __checkThrows: Error | null;
  __downloadResolver: () => void;
  __downloadRejecter: (err: Error) => void;
}

function makeFakeUpdater(): FakeAutoUpdater {
  const emitter = new EventEmitter() as FakeAutoUpdater;

  emitter.autoDownload = true;
  emitter.autoInstallOnAppQuit = true;
  emitter.logger = null;
  emitter.__checkResult = null;
  emitter.__checkThrows = null;
  emitter.__downloadResolver = () => {};
  emitter.__downloadRejecter = () => {};

  emitter.checkForUpdates = vi.fn(async () => {
    if (emitter.__checkThrows) throw emitter.__checkThrows;
    return emitter.__checkResult as Awaited<ReturnType<AutoUpdaterLike['checkForUpdates']>>;
  });

  emitter.downloadUpdate = vi.fn(
    () =>
      new Promise<string[]>((resolve, reject) => {
        emitter.__downloadResolver = () => resolve(['/tmp/fake.AppImage']);
        emitter.__downloadRejecter = reject;
      }),
  );

  emitter.quitAndInstall = vi.fn();

  return emitter;
}

function silentLogger(): UpdateInstallerLogger {
  return {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
}

function statusHistory(inst: UpdateInstaller): InstallerStatus[] {
  const history: InstallerStatus[] = [];
  inst.on('status', (s) => history.push(s));
  return history;
}

// ─── Tests ──────────────────────────────────────────────────────────────

describe('UpdateInstaller', () => {
  let updater: FakeAutoUpdater;
  let inst: UpdateInstaller;

  beforeEach(() => {
    updater = makeFakeUpdater();
    inst = new UpdateInstaller(silentLogger(), updater);
  });

  it('configures autoUpdater with autoDownload=false and autoInstallOnAppQuit=false', () => {
    expect(updater.autoDownload).toBe(false);
    expect(updater.autoInstallOnAppQuit).toBe(false);
  });

  it('starts at idle', () => {
    expect(inst.getStatus()).toEqual({ state: 'idle' });
  });

  it('startDownload: no update available transitions checking → idle', async () => {
    updater.__checkResult = null;
    const history = statusHistory(inst);

    const result = await inst.startDownload();

    expect(result).toEqual({ ok: false, reason: 'no-update-available' });
    expect(history.map((s) => s.state)).toEqual(['checking', 'idle']);
  });

  // Issue #105: electron-updater always populates `updateInfo` (it carries
  // the latest release info even when the running version equals it). The
  // real signal is `isUpdateAvailable`. Without this guard, a Download click
  // against stale state would skate past the `!updateInfo` check, transition
  // the installer to `downloading`, and eventually error from
  // `downloadUpdate("Please check update first")`.
  it('startDownload: isUpdateAvailable=false with populated updateInfo → idle (Issue #105)', async () => {
    updater.__checkResult = {
      isUpdateAvailable: false,
      updateInfo: { version: '1.3.3' },
    };
    const history = statusHistory(inst);

    const result = await inst.startDownload();

    expect(result).toEqual({ ok: false, reason: 'no-update-available' });
    expect(history.map((s) => s.state)).toEqual(['checking', 'idle']);
    // Critical: downloadUpdate must NOT have been invoked. The bug was that
    // the installer entered the download path and electron-updater's
    // `downloadUpdate` rejected with "Please check update first" only after
    // the user-visible `downloading` flicker.
    expect(updater.downloadUpdate).not.toHaveBeenCalled();
    // Defense against a future refactor that collapses both no-update guards
    // into one condition that drops a term: assert exactly one check call.
    expect(updater.checkForUpdates).toHaveBeenCalledTimes(1);
  });

  // Backward-compat: older electron-updater versions and minimal mocks
  // omit `isUpdateAvailable`. The strict `=== false` guard must let those
  // through and the legacy `!updateInfo` path remains the sole gate. This
  // test pins that behaviour so a future "simplify to !isUpdateAvailable"
  // refactor breaks here.
  it('startDownload: isUpdateAvailable=undefined with updateInfo proceeds to download', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = {
      // isUpdateAvailable intentionally omitted
      updateInfo: { version: '1.4.0' },
      cancellationToken: token,
    };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    expect(inst.getStatus().state).toBe('downloading');

    updater.emit('update-downloaded', { version: '1.4.0' });
    updater.__downloadResolver();
    const result = await downloadPromise;

    expect(result).toEqual({ ok: true });
    expect(updater.downloadUpdate).toHaveBeenCalledTimes(1);
  });

  it('startDownload: newer version transitions checking → downloading, updates progress via events', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const history = statusHistory(inst);
    const downloadPromise = inst.startDownload();

    // Wait for checkForUpdates microtask to flush
    await new Promise((r) => setImmediate(r));

    // Emit progress while the download is in flight.
    updater.emit('download-progress', {
      percent: 50,
      bytesPerSecond: 1000,
      transferred: 500,
      total: 1000,
    });

    // Complete the download (emits update-downloaded first, then resolve).
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();

    const result = await downloadPromise;

    expect(result).toEqual({ ok: true });
    const states = history.map((s) => s.state);
    expect(states).toContain('checking');
    expect(states).toContain('downloading');
    expect(states[states.length - 1]).toBe('downloaded');

    const finalStatus = inst.getStatus();
    expect(finalStatus).toEqual({ state: 'downloaded', version: '1.3.3' });

    // Progress snapshot captured from the download-progress event
    const downloadingWithProgress = history.find(
      (s): s is Extract<InstallerStatus, { state: 'downloading' }> =>
        s.state === 'downloading' && s.percent === 50,
    );
    expect(downloadingWithProgress).toBeDefined();
    expect(downloadingWithProgress?.version).toBe('1.3.3');
    expect(downloadingWithProgress?.transferred).toBe(500);
    expect(downloadingWithProgress?.total).toBe(1000);
  });

  it('startDownload: concurrent call while downloading returns already-downloading', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const first = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    // Now state is 'downloading'
    expect(inst.getStatus().state).toBe('downloading');

    const second = await inst.startDownload();
    expect(second).toEqual({ ok: true, reason: 'already-downloading' });

    // downloadUpdate was called only once (for the first call)
    expect(updater.downloadUpdate).toHaveBeenCalledTimes(1);

    // Clean up the first download
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await first;
  });

  it('startDownload: checkForUpdates throws → status becomes error', async () => {
    updater.__checkThrows = new Error('network down');

    const result = await inst.startDownload();

    expect(result.ok).toBe(false);
    expect(inst.getStatus()).toEqual({ state: 'error', message: 'network down' });
  });

  it('autoUpdater error event after download starts → status becomes error; main process does not crash', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));

    updater.emit('error', new Error('disk full'));
    updater.__downloadRejecter(new Error('disk full'));

    const result = await downloadPromise;

    expect(result.ok).toBe(false);
    expect(inst.getStatus()).toEqual({ state: 'error', message: 'disk full' });
  });

  it('install: not downloaded returns no-update-ready without throwing', async () => {
    const result = await inst.install();
    expect(result).toEqual({ ok: false, reason: 'no-update-ready' });
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
  });

  it('install: after download calls quitAndInstall(false, true)', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));

    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;

    const result = await inst.install();
    expect(result).toEqual({ ok: true });
    expect(updater.quitAndInstall).toHaveBeenCalledWith(false, true);
  });

  it('cancelDownload: while downloading cancels the token and transitions to cancelled', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    expect(inst.getStatus().state).toBe('downloading');

    const result = inst.cancelDownload();

    expect(result).toEqual({ ok: true });
    expect(token.cancelled).toBe(true);
    expect(inst.getStatus()).toEqual({ state: 'cancelled' });

    // Reject the download to simulate electron-updater honoring the token
    updater.__downloadRejecter(new Error('cancelled'));
    const downloadResult = await downloadPromise;
    expect(downloadResult).toEqual({ ok: true });
  });

  it('cancelDownload: when idle is a no-op', () => {
    const result = inst.cancelDownload();
    expect(result).toEqual({ ok: true });
    expect(inst.getStatus()).toEqual({ state: 'idle' });
  });

  it('download-progress after cancel does not overwrite cancelled status', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    inst.cancelDownload();

    updater.emit('download-progress', {
      percent: 99,
      bytesPerSecond: 500,
      transferred: 990,
      total: 1000,
    });

    expect(inst.getStatus()).toEqual({ state: 'cancelled' });

    updater.__downloadRejecter(new Error('cancelled'));
    await downloadPromise;
  });

  it('destroy: removes autoUpdater listeners', () => {
    expect(updater.listenerCount('download-progress')).toBeGreaterThan(0);
    inst.destroy();
    expect(updater.listenerCount('download-progress')).toBe(0);
    expect(updater.listenerCount('error')).toBe(0);
  });

  it('destroy: cancels active download so the orphan Promise rejects cleanly', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    expect(inst.getStatus().state).toBe('downloading');

    inst.destroy();

    expect(token.cancelled).toBe(true);

    updater.__downloadRejecter(new Error('cancelled'));
    await downloadPromise.catch(() => {});
  });

  it('error event after downloaded does not clobber the downloaded status', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;

    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });

    updater.emit('error', new Error('late disk error'));

    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });
  });

  it('download-progress after downloaded does not regress the status', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;

    updater.emit('download-progress', {
      percent: 100,
      bytesPerSecond: 0,
      transferred: 1000,
      total: 1000,
    });

    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });
  });

  it('install: second call after the first is rejected with install-already-requested', async () => {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };

    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;

    const first = await inst.install();
    expect(first).toEqual({ ok: true });

    const second = await inst.install();
    expect(second).toEqual({ ok: false, reason: 'install-already-requested' });
    expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);
  });

  it('getStatus returns a shallow clone, not the internal reference', () => {
    const a = inst.getStatus();
    const b = inst.getStatus();
    expect(a).not.toBe(b);
    expect(a).toEqual(b);
  });
});

// ─── M6: verifier + cacheHook ────────────────────────────────────────────

import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import path from 'path';
import { existsSync } from 'fs';

describe('UpdateInstaller verifier integration (M6)', () => {
  let updater: FakeAutoUpdater;
  let tmp: string;

  beforeEach(() => {
    updater = makeFakeUpdater();
    tmp = mkdtempSync(path.join(tmpdir(), 'verifier-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  async function driveDownload(inst: UpdateInstaller, downloadedFile: string): Promise<void> {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3', downloadedFile });
    updater.__downloadResolver();
    await downloadPromise;
  }

  it('passes through to downloaded when verifier returns ok', async () => {
    const file = path.join(tmp, 'bin.AppImage');
    writeFileSync(file, 'ok');
    const verifier = vi.fn(async () => ({ ok: true as const }));
    const inst = new UpdateInstaller(silentLogger(), updater, { verifier });
    const history = statusHistory(inst);

    await driveDownload(inst, file);
    await new Promise((r) => setImmediate(r));

    const states = history.map((s) => s.state);
    expect(states).toContain('verifying');
    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });
    expect(verifier).toHaveBeenCalledWith(file, '1.3.3');
  });

  it('unlinks the file and flips to error when verifier returns ok:false', async () => {
    const file = path.join(tmp, 'bad.AppImage');
    writeFileSync(file, 'tampered');
    const verifier = vi.fn(async () => ({ ok: false as const, reason: 'checksum-mismatch' }));
    const inst = new UpdateInstaller(silentLogger(), updater, { verifier });

    await driveDownload(inst, file);
    // Allow the verifier promise + the unlink I/O to settle. Real fsp.unlink
    // is a native-bound async op, so we need more than one microtask tick.
    for (let i = 0; i < 10 && inst.getStatus().state !== 'error'; i++) {
      await new Promise((r) => setTimeout(r, 5));
    }

    expect(inst.getStatus()).toEqual({ state: 'error', message: 'checksum-mismatch' });
    expect(existsSync(file)).toBe(false);
  });

  it('surfaces a rejected verifier as error{verifier-threw:...}', async () => {
    const file = path.join(tmp, 'throws.AppImage');
    writeFileSync(file, 'x');
    const verifier = vi.fn(async () => {
      throw new Error('boom');
    });
    const inst = new UpdateInstaller(silentLogger(), updater, { verifier });

    await driveDownload(inst, file);
    await new Promise((r) => setImmediate(r));

    const status = inst.getStatus();
    expect(status.state).toBe('error');
    if (status.state === 'error') {
      expect(status.message).toContain('boom');
    }
  });

  it('skips verification and goes to downloaded when downloadedFile is absent', async () => {
    const verifier = vi.fn(async () => ({ ok: true as const }));
    const inst = new UpdateInstaller(silentLogger(), updater, { verifier });

    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    // Emit event without downloadedFile
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;
    await new Promise((r) => setImmediate(r));

    expect(verifier).not.toHaveBeenCalled();
    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });
  });

  it('when no verifier is wired, behaves exactly like M1 (no verifying state)', async () => {
    const inst = new UpdateInstaller(silentLogger(), updater);
    const history = statusHistory(inst);

    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;

    expect(history.map((s) => s.state)).not.toContain('verifying');
    expect(inst.getStatus()).toEqual({ state: 'downloaded', version: '1.3.3' });
  });

  it('does not regress a cancelled state if verifier resolves late', async () => {
    let resolveVerifier: (v: { ok: true } | { ok: false; reason: string }) => void = () => {};
    const verifier = vi.fn(
      () =>
        new Promise<{ ok: true } | { ok: false; reason: string }>((r) => {
          resolveVerifier = r;
        }),
    );
    const file = path.join(tmp, 'bin.AppImage');
    writeFileSync(file, 'x');
    const inst = new UpdateInstaller(silentLogger(), updater, { verifier });

    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3', downloadedFile: file });
    updater.__downloadResolver();
    await downloadPromise;
    // Wait for the verifying state to settle (setStatus fires after the
    // verifier Promise is awaited — needs a microtask tick).
    for (let i = 0; i < 10 && inst.getStatus().state !== 'verifying'; i++) {
      await new Promise((r) => setTimeout(r, 5));
    }
    expect(inst.getStatus().state).toBe('verifying');

    // User cancels mid-verify
    inst.cancelDownload();
    expect(inst.getStatus()).toEqual({ state: 'cancelled' });

    // Verifier resolves late — must not regress cancelled → downloaded
    resolveVerifier({ ok: true });
    await new Promise((r) => setImmediate(r));

    expect(inst.getStatus()).toEqual({ state: 'cancelled' });
  });
});

describe('UpdateInstaller cache hook integration (M6)', () => {
  let updater: FakeAutoUpdater;

  beforeEach(() => {
    updater = makeFakeUpdater();
  });

  async function downloadReady(inst: UpdateInstaller): Promise<void> {
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '1.3.3' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '1.3.3' });
    updater.__downloadResolver();
    await downloadPromise;
  }

  it('invokes the cache hook before quitAndInstall', async () => {
    const events: string[] = [];
    const cacheHook = vi.fn(async (ctx: { version: string }) => {
      events.push(`cached:${ctx.version}`);
    });
    const inst = new UpdateInstaller(silentLogger(), updater, { cacheHook });
    (updater.quitAndInstall as ReturnType<typeof vi.fn>).mockImplementation(() => {
      events.push('quitAndInstall');
    });

    await downloadReady(inst);
    await inst.install();

    expect(cacheHook).toHaveBeenCalledWith({ version: '1.3.3' });
    expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);
    // Cache hook must complete BEFORE quitAndInstall — electron can
    // kill the process mid-copy otherwise.
    expect(events).toEqual(['cached:1.3.3', 'quitAndInstall']);
  });

  it('still calls quitAndInstall when the cache hook rejects', async () => {
    const cacheHook = vi.fn(async () => {
      throw new Error('disk full');
    });
    const inst = new UpdateInstaller(silentLogger(), updater, { cacheHook });

    await downloadReady(inst);
    const result = await inst.install();

    expect(result).toEqual({ ok: true });
    expect(updater.quitAndInstall).toHaveBeenCalledWith(false, true);
  });

  it('does not invoke the cache hook when install returns no-update-ready', async () => {
    const cacheHook = vi.fn(async () => {});
    const inst = new UpdateInstaller(silentLogger(), updater, { cacheHook });

    const result = await inst.install();

    expect(result).toEqual({ ok: false, reason: 'no-update-ready' });
    expect(cacheHook).not.toHaveBeenCalled();
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
  });

  // ─── cacheHook timeout (spec: in-app-update-cache-write-hardening) ──

  describe('cacheHook timeout', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('falls through to quitAndInstall after 30s when cacheHook never resolves', async () => {
      // Hook that never resolves — simulates a hung copyFile on failing
      // storage. Without the Promise.race bound, install() would block
      // indefinitely here, freezing the user's "Install" click.
      const neverResolves = new Promise<void>(() => {});
      const cacheHook = vi.fn(() => neverResolves);
      const logger = silentLogger();
      const inst = new UpdateInstaller(logger, updater, { cacheHook });

      // Use REAL timers for downloadReady — it awaits setImmediate and
      // would deadlock under fake timers. Switch to fake AFTER setup so
      // only install()'s timeout bound is under our control.
      await downloadReady(inst);
      vi.useFakeTimers();

      // Detach install() — its Promise is still pending at this point
      // because cacheHook hasn't resolved.
      const installPromise = inst.install();

      // Flush microtasks so install()'s await reaches the Promise.race.
      await vi.advanceTimersByTimeAsync(0);
      expect(updater.quitAndInstall).not.toHaveBeenCalled();

      // Advance past the 30s timeout. The sentinel-Promise resolves and
      // install() continues to quitAndInstall.
      await vi.advanceTimersByTimeAsync(30_000);

      const result = await installPromise;
      expect(result).toEqual({ ok: true });
      expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);
      expect(cacheHook).toHaveBeenCalledWith({ version: '1.3.3' });

      // Warn-log fired with the timeout marker. Use a substring so the
      // exact millisecond string in the message isn't hard-coded here.
      const warnCalls = (logger.warn as ReturnType<typeof vi.fn>).mock.calls;
      const timedOutCall = warnCalls.find((call) =>
        call.some((arg) => typeof arg === 'string' && arg.includes('cache-hook timed out')),
      );
      expect(timedOutCall).toBeDefined();
    });

    it('does not log timeout when cacheHook resolves before the bound', async () => {
      // Real timers: the hook resolves immediately, so the race ends on
      // the hook side. No sentinel fire, no timeout log.
      const cacheHook = vi.fn(async () => {});
      const logger = silentLogger();
      const inst = new UpdateInstaller(logger, updater, { cacheHook });

      await downloadReady(inst);
      const result = await inst.install();

      expect(result).toEqual({ ok: true });
      expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);

      const warnCalls = (logger.warn as ReturnType<typeof vi.fn>).mock.calls;
      const timedOutCall = warnCalls.find((call) =>
        call.some((arg) => typeof arg === 'string' && arg.includes('cache-hook timed out')),
      );
      expect(timedOutCall).toBeUndefined();
    });
  });

  // ─── M7: platform-strategy short-circuit ────────────────────────────

  describe('M7: platformStrategy', () => {
    it('manual-download strategy short-circuits before checkForUpdates', async () => {
      const platformStrategy = vi.fn(async () => ({
        strategy: 'manual-download' as const,
        reason: 'macos-unsigned',
        version: '1.3.3',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
      }));
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });
      const history = statusHistory(m7Inst);

      const result = await m7Inst.startDownload();

      expect(platformStrategy).toHaveBeenCalledOnce();
      expect(updater.checkForUpdates).not.toHaveBeenCalled();
      expect(result).toEqual({
        ok: false,
        reason: 'manual-download-required',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
      });
      expect(m7Inst.getStatus()).toEqual({
        state: 'manual-download-required',
        version: '1.3.3',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
        reason: 'macos-unsigned',
      });
      // No 'checking' transition — went straight from idle → manual-download-required
      expect(history.map((s) => s.state)).toEqual(['manual-download-required']);
    });

    it('electron-updater strategy preserves M1 behavior (checkForUpdates IS invoked)', async () => {
      const platformStrategy = vi.fn(async () => ({
        strategy: 'electron-updater' as const,
      }));
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });

      updater.__checkResult = null; // no update available
      const result = await m7Inst.startDownload();

      expect(platformStrategy).toHaveBeenCalledOnce();
      expect(updater.checkForUpdates).toHaveBeenCalledOnce();
      expect(result).toEqual({ ok: false, reason: 'no-update-available' });
    });

    it('absent platformStrategy preserves M1 behavior (no resolver call)', async () => {
      // Default constructor (no platformStrategy dep) — should never short-circuit.
      const m1Inst = new UpdateInstaller(silentLogger(), updater);
      updater.__checkResult = null;
      await m1Inst.startDownload();
      expect(updater.checkForUpdates).toHaveBeenCalledOnce();
    });

    it('manual-download with null version uses the URL as-is', async () => {
      const platformStrategy = vi.fn(async () => ({
        strategy: 'manual-download' as const,
        reason: 'appimage-missing',
        version: null,
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
      }));
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });

      const result = await m7Inst.startDownload();

      expect(result).toEqual({
        ok: false,
        reason: 'manual-download-required',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
      });
      const status = m7Inst.getStatus();
      expect(status.state).toBe('manual-download-required');
      if (status.state === 'manual-download-required') {
        expect(status.version).toBeNull();
        expect(status.reason).toBe('appimage-missing');
      }
    });

    it('platformStrategy throwing falls open to electron-updater (no stuck UI)', async () => {
      const platformStrategy = vi.fn(async () => {
        throw new Error('fs blew up');
      });
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });

      updater.__checkResult = null;
      const result = await m7Inst.startDownload();

      expect(updater.checkForUpdates).toHaveBeenCalledOnce();
      expect(result).toEqual({ ok: false, reason: 'no-update-available' });
    });

    it('cancelDownload from manual-download-required transitions to cancelled', async () => {
      const platformStrategy = vi.fn(async () => ({
        strategy: 'manual-download' as const,
        reason: 'macos-unsigned',
        version: '1.3.3',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
      }));
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });
      await m7Inst.startDownload();
      expect(m7Inst.getStatus().state).toBe('manual-download-required');

      const result = m7Inst.cancelDownload();

      expect(result).toEqual({ ok: true });
      expect(m7Inst.getStatus()).toEqual({ state: 'cancelled' });
    });

    it('manual-download omits downloadUrl → status carries empty string fallback', async () => {
      const platformStrategy = vi.fn(async () => ({
        strategy: 'manual-download' as const,
        reason: 'unsupported-platform',
      }));
      const m7Inst = new UpdateInstaller(silentLogger(), updater, { platformStrategy });

      const result = await m7Inst.startDownload();
      expect(result).toEqual({
        ok: false,
        reason: 'manual-download-required',
        downloadUrl: '',
      });
    });
  });

  it('install rejects with no-version when currentVersion was never captured', async () => {
    // Force the installer into a 'downloaded' state without going through
    // startDownload (which is what normally populates currentVersion).
    // Manually emit update-downloaded to exercise the guard.
    const inst = new UpdateInstaller(silentLogger(), updater, {});
    const token = new FakeCancellationToken();
    updater.__checkResult = { updateInfo: { version: '' }, cancellationToken: token };
    const downloadPromise = inst.startDownload();
    await new Promise((r) => setImmediate(r));
    updater.emit('update-downloaded', { version: '' });
    updater.__downloadResolver();
    await downloadPromise;

    // Clear currentVersion via construction quirk: replace with a fresh
    // instance where no download ever happened but state is faked.
    // Simpler: bypass via direct manipulation to simulate a race — we
    // assert the guard works regardless of how the state got there.
    (inst as unknown as { currentVersion: string | null }).currentVersion = null;
    (inst as unknown as { status: InstallerStatus }).status = {
      state: 'downloaded',
      version: '1.3.3',
    };

    const result = await inst.install();
    expect(result).toEqual({ ok: false, reason: 'no-version' });
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
  });
});
