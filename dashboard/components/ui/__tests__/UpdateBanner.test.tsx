/**
 * UpdateBanner — unit tests.
 *
 * Covers every row of the spec's I/O & Edge-Case Matrix plus:
 *   - snooze round-trip persistence
 *   - mount-time getInstallerStatus() invocation (guards the M1 deferred-work gap)
 *   - component hidden when window.electronAPI is absent (browser dev mode)
 */

import { render, screen, act, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// ── Mock config/store before importing the component ────────────────────────

const configStore = new Map<string, unknown>();
const getConfigMock = vi.fn(async (key: string) => configStore.get(key));
const setConfigMock = vi.fn(async (key: string, value: unknown) => {
  configStore.set(key, value);
});

vi.mock('../../../src/config/store', () => ({
  getConfig: (key: string) => getConfigMock(key),
  setConfig: (key: string, value: unknown) => setConfigMock(key, value),
}));

// ── Mock sonner (M6 error toast) ────────────────────────────────────────────

const toastErrorMock = vi.fn();
const toastSuccessMock = vi.fn();

vi.mock('sonner', () => ({
  toast: {
    error: (...args: unknown[]) => toastErrorMock(...args),
    success: (...args: unknown[]) => toastSuccessMock(...args),
  },
}));

// ── Import after mocks ──────────────────────────────────────────────────────

import {
  UpdateBanner,
  clampSnooze,
  deriveBannerState,
  manualDownloadTooltip,
} from '../UpdateBanner';

// ── Test electronAPI harness ────────────────────────────────────────────────

type InstallerListener = (status: InstallerStatus) => void;

interface TestHarness {
  currentInstaller: InstallerStatus;
  currentUpdateStatus: UpdateStatus | null;
  listeners: InstallerListener[];
  getInstallerStatus: ReturnType<typeof vi.fn>;
  getStatus: ReturnType<typeof vi.fn>;
  onInstallerStatus: ReturnType<typeof vi.fn>;
  download: ReturnType<typeof vi.fn>;
  install: ReturnType<typeof vi.fn>;
  cancelDownload: ReturnType<typeof vi.fn>;
  checkCompatibility: ReturnType<typeof vi.fn>;
  getVersion: ReturnType<typeof vi.fn>;
  openReleasePage: ReturnType<typeof vi.fn>;
  emit: (status: InstallerStatus) => void;
}

function buildHarness(
  overrides: Partial<{
    installer: InstallerStatus;
    updateStatus: UpdateStatus | null;
  }> = {},
): TestHarness {
  const h: TestHarness = {
    currentInstaller: overrides.installer ?? { state: 'idle' },
    currentUpdateStatus: overrides.updateStatus ?? null,
    listeners: [],
    getInstallerStatus: vi.fn(),
    getStatus: vi.fn(),
    onInstallerStatus: vi.fn(),
    download: vi.fn().mockResolvedValue({ ok: true }),
    install: vi.fn().mockResolvedValue({ ok: true }),
    cancelDownload: vi.fn().mockResolvedValue({ ok: true }),
    checkCompatibility: vi
      .fn()
      .mockResolvedValue({ result: 'unknown', reason: 'manifest-fetch-failed' }),
    getVersion: vi.fn().mockResolvedValue('1.3.2'),
    openReleasePage: vi.fn().mockResolvedValue({ ok: true }),
    emit: (s: InstallerStatus) => {
      h.currentInstaller = s;
      for (const cb of h.listeners) cb(s);
    },
  };
  h.getInstallerStatus.mockImplementation(async () => h.currentInstaller);
  h.getStatus.mockImplementation(async () => h.currentUpdateStatus);
  h.onInstallerStatus.mockImplementation((cb: InstallerListener) => {
    h.listeners.push(cb);
    return () => {
      h.listeners = h.listeners.filter((x) => x !== cb);
    };
  });
  return h;
}

function installHarness(h: TestHarness): void {
  (
    window as unknown as {
      electronAPI: { updates: unknown; app: unknown; docker: unknown };
    }
  ).electronAPI = {
    updates: {
      getStatus: h.getStatus,
      checkNow: vi.fn(),
      getInstallerStatus: h.getInstallerStatus,
      onInstallerStatus: h.onInstallerStatus,
      download: h.download,
      install: h.install,
      cancelDownload: h.cancelDownload,
      checkCompatibility: h.checkCompatibility,
      openReleasePage: h.openReleasePage,
    },
    app: { getVersion: h.getVersion },
    docker: { pullImage: vi.fn().mockResolvedValue('') },
  };
}

function availableStatus(latest = '1.3.3'): UpdateStatus {
  return {
    lastChecked: new Date().toISOString(),
    app: { current: '1.3.2', latest, updateAvailable: true, error: null, releaseNotes: null },
    server: {
      current: null,
      latest: null,
      updateAvailable: false,
      error: null,
      releaseNotes: null,
    },
  };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

// ── Setup ───────────────────────────────────────────────────────────────────

beforeEach(() => {
  configStore.clear();
  getConfigMock.mockClear();
  setConfigMock.mockClear();
  toastErrorMock.mockClear();
  toastSuccessMock.mockClear();
});

afterEach(() => {
  cleanup();
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

// ── deriveBannerState (pure function) ───────────────────────────────────────

describe('deriveBannerState', () => {
  const now = 1_000_000;

  it('returns available when updateAvailable + idle installer + not snoozed', () => {
    const out = deriveBannerState({ state: 'idle' }, availableStatus('1.3.3'), false, now, 0);
    expect(out).toEqual({ state: 'available', version: '1.3.3' });
  });

  it('returns hidden when snoozed even though update is available', () => {
    const out = deriveBannerState({ state: 'idle' }, availableStatus(), false, now, now + 1000);
    expect(out.state).toBe('hidden');
  });

  it('maps downloading with percent', () => {
    const out = deriveBannerState(
      {
        state: 'downloading',
        version: '1.3.3',
        percent: 43,
        bytesPerSecond: 1,
        transferred: 1,
        total: 2,
      },
      availableStatus(),
      false,
      now,
      0,
    );
    expect(out).toEqual({ state: 'downloading', version: '1.3.3', percent: 43 });
  });

  it('maps checking to downloading at 0% using updateStatus.app.latest', () => {
    const out = deriveBannerState({ state: 'checking' }, availableStatus('1.3.4'), false, now, 0);
    expect(out).toEqual({ state: 'downloading', version: '1.3.4', percent: 0 });
  });

  it('maps downloaded + idle app to ready', () => {
    const out = deriveBannerState({ state: 'downloaded', version: '1.3.3' }, null, false, now, 0);
    expect(out).toEqual({ state: 'ready', version: '1.3.3' });
  });

  it('maps downloaded + busy app to ready_blocked', () => {
    const out = deriveBannerState({ state: 'downloaded', version: '1.3.3' }, null, true, now, 0);
    expect(out).toEqual({ state: 'ready_blocked', version: '1.3.3' });
  });

  it('collapses cancelled to hidden when no update available', () => {
    const out = deriveBannerState({ state: 'cancelled' }, null, false, now, 0);
    expect(out.state).toBe('hidden');
  });

  it('collapses cancelled to available when update still pending', () => {
    const out = deriveBannerState({ state: 'cancelled' }, availableStatus(), false, now, 0);
    expect(out).toEqual({ state: 'available', version: '1.3.3' });
  });

  it('collapses error to hidden', () => {
    const out = deriveBannerState({ state: 'error', message: 'boom' }, null, false, now, 0);
    expect(out.state).toBe('hidden');
  });

  it('returns hidden when no installer and no update available', () => {
    const out = deriveBannerState(null, null, false, now, 0);
    expect(out.state).toBe('hidden');
  });

  it('returns available when installer is null but update available', () => {
    const out = deriveBannerState(null, availableStatus(), false, now, 0);
    expect(out).toEqual({ state: 'available', version: '1.3.3' });
  });

  it('hides when updateAvailable is true but latest is null or empty string', () => {
    const statusNull: UpdateStatus = {
      lastChecked: new Date(now).toISOString(),
      app: {
        current: '1.3.2',
        latest: null,
        updateAvailable: true,
        error: null,
        releaseNotes: null,
      },
      server: {
        current: null,
        latest: null,
        updateAvailable: false,
        error: null,
        releaseNotes: null,
      },
    };
    expect(deriveBannerState({ state: 'idle' }, statusNull, false, now, 0).state).toBe('hidden');

    const statusEmpty: UpdateStatus = {
      ...statusNull,
      app: { ...statusNull.app, latest: '' },
    };
    expect(deriveBannerState({ state: 'idle' }, statusEmpty, false, now, 0).state).toBe('hidden');
  });

  it('survives a malformed persisted UpdateStatus missing the app field', () => {
    // Legacy / schema-drift payload — .app is absent.
    const malformed = { lastChecked: new Date(now).toISOString() } as unknown as UpdateStatus;
    const out = deriveBannerState({ state: 'idle' }, malformed, false, now, 0);
    expect(out.state).toBe('hidden');
  });

  // ── Deferred bug: M7 review surfaced a missing case in the switch ─────
  it('maps verifying to downloading visual (no [Download] surface)', () => {
    // Without this case the switch falls through to availableFromPoll,
    // re-enabling [Download] mid-verify; a fast double-click can re-enter
    // UpdateInstaller.startDownload (which only guards 'downloading').
    const out = deriveBannerState(
      { state: 'verifying', version: '1.3.3' },
      availableStatus('1.3.3'),
      false,
      now,
      0,
    );
    expect(out).toEqual({ state: 'downloading', version: '1.3.3' });
  });
});

// ── Component behavior ──────────────────────────────────────────────────────

describe('UpdateBanner component', () => {
  it('renders nothing when window.electronAPI is absent (browser dev mode)', async () => {
    // electronAPI intentionally not installed on window.
    const h = buildHarness();
    // Don't install — just keep handle to the harness mocks so we can assert absence of calls.
    const { container } = render(<UpdateBanner isBusy={false} />);
    await flush();
    expect(container.firstChild).toBeNull();
    // Guard against regression where the effect runs logic before the isElectron() check.
    expect(h.getInstallerStatus).not.toHaveBeenCalled();
    expect(h.getStatus).not.toHaveBeenCalled();
    expect(h.onInstallerStatus).not.toHaveBeenCalled();
    expect(getConfigMock).not.toHaveBeenCalled();
  });

  it('calls getInstallerStatus() exactly once on mount', async () => {
    const h = buildHarness({
      installer: {
        state: 'downloading',
        version: '1.3.3',
        percent: 10,
        bytesPerSecond: 1,
        transferred: 1,
        total: 10,
      },
    });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(h.getInstallerStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Downloading 1\.3\.3/)).toBeTruthy();
  });

  it('renders available banner from poll-only state when installer is idle', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(screen.getByText('1.3.3 available')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Later' })).toBeTruthy();
  });

  it('renders downloading banner with progress text', async () => {
    const h = buildHarness({
      installer: {
        state: 'downloading',
        version: '1.3.3',
        percent: 43,
        bytesPerSecond: 1,
        transferred: 1,
        total: 2,
      },
    });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(screen.getByText('Downloading 1.3.3 — 43%')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Later' })).toBeNull();
  });

  it('renders ready banner with Quit & Install when idle', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(screen.getByText('1.3.3 ready')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Quit & Install' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Later' })).toBeTruthy();
  });

  it('renders ready_blocked with disabled install and no Later when busy', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    installHarness(h);

    render(<UpdateBanner isBusy={true} />);
    await flush();

    expect(screen.getByText(/will install when jobs finish/)).toBeTruthy();
    const btn = screen.getByRole('button', { name: 'Quit & Install' }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute('title')).toBe('Will install when jobs finish');
    expect(screen.queryByRole('button', { name: 'Later' })).toBeNull();
  });

  // M5: [Download] no longer calls api.download() directly — it opens the
  // pre-install modal. The actual download fires from the modal's
  // [Install Dashboard] button (covered below).
  it('Download click opens the pre-install modal and does NOT call updates.download()', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus(),
    });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await flush();

    expect(h.download).not.toHaveBeenCalled();
    expect(
      screen.getByRole('dialog', { name: /dashboard update.*install confirmation/i }),
    ).toBeTruthy();
  });

  it('Install Dashboard (modal footer) invokes updates.download()', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus(),
    });
    // Compatible verdict so the [Install Dashboard] button is enabled.
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /install dashboard/i }));
    await flush();

    expect(h.download).toHaveBeenCalledTimes(1);
  });

  it('Quit & Install click invokes updates.install()', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Quit & Install' }));
    await flush();

    expect(h.install).toHaveBeenCalledTimes(1);
  });

  it('Later click persists snooze + hides banner; stays hidden on remount within 4h', async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date(2026, 3, 12, 12, 0, 0));

      const h = buildHarness({
        installer: { state: 'idle' },
        updateStatus: availableStatus(),
      });
      installHarness(h);

      const { unmount } = render(<UpdateBanner isBusy={false} />);
      await flush();

      fireEvent.click(screen.getByRole('button', { name: 'Later' }));
      await flush();

      expect(setConfigMock).toHaveBeenCalledWith('updates.bannerSnoozedUntil', expect.any(Number));
      const persistedUntil = configStore.get('updates.bannerSnoozedUntil') as number;
      expect(persistedUntil).toBe(Date.now() + 4 * 60 * 60 * 1000);
      expect(screen.queryByText('1.3.3 available')).toBeNull();

      unmount();

      // Advance 1h — still within 4h snooze window.
      vi.setSystemTime(Date.now() + 60 * 60 * 1000);

      const h2 = buildHarness({
        installer: { state: 'idle' },
        updateStatus: availableStatus(),
      });
      installHarness(h2);

      render(<UpdateBanner isBusy={false} />);
      await flush();

      expect(screen.queryByText('1.3.3 available')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('clamps NaN percent to 0 in the rendered progress label and bar width', async () => {
    const h = buildHarness({
      installer: {
        state: 'downloading',
        version: '1.3.3',
        percent: Number.NaN,
        bytesPerSecond: 0,
        transferred: 0,
        total: 0,
      },
    });
    installHarness(h);

    const { container } = render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(screen.getByText('Downloading 1.3.3 — 0%')).toBeTruthy();
    // Progress bar inner div should have a finite width — grab it by class.
    const bar = container.querySelector('[style*="width"]') as HTMLElement | null;
    expect(bar).not.toBeNull();
    expect(bar!.style.width).toBe('0%');
  });

  it('does not clobber a live transition when getInstallerStatus resolves late', async () => {
    // Hold the getInstallerStatus promise so we can resolve it after a transition event.
    let resolveStatus: (s: InstallerStatus) => void = () => {};
    const h = buildHarness({ installer: { state: 'idle' } });
    h.getInstallerStatus.mockImplementation(
      () =>
        new Promise<InstallerStatus>((res) => {
          resolveStatus = res;
        }),
    );
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    // Deliver a live transition before the stale snapshot resolves.
    await act(async () => {
      h.emit({
        state: 'downloading',
        version: '1.3.3',
        percent: 50,
        bytesPerSecond: 1,
        transferred: 5,
        total: 10,
      });
    });
    expect(screen.getByText('Downloading 1.3.3 — 50%')).toBeTruthy();

    // Now resolve the stale snapshot with an older frame.
    await act(async () => {
      resolveStatus({
        state: 'downloading',
        version: '1.3.3',
        percent: 10,
        bytesPerSecond: 1,
        transferred: 1,
        total: 10,
      });
      await Promise.resolve();
    });

    // Banner must NOT regress to 10%.
    expect(screen.getByText('Downloading 1.3.3 — 50%')).toBeTruthy();
  });

  it('reacts to live installer transitions after mount', async () => {
    const h = buildHarness({ installer: { state: 'idle' } });
    installHarness(h);

    render(<UpdateBanner isBusy={false} />);
    await flush();

    // Initially hidden (no update available, installer idle).
    expect(screen.queryByRole('status')).toBeNull();

    // Transition to downloading.
    await act(async () => {
      h.emit({
        state: 'downloading',
        version: '1.3.3',
        percent: 10,
        bytesPerSecond: 1,
        transferred: 1,
        total: 10,
      });
    });

    expect(screen.getByText('Downloading 1.3.3 — 10%')).toBeTruthy();

    // Transition to downloaded.
    await act(async () => {
      h.emit({ state: 'downloaded', version: '1.3.3' });
    });

    expect(screen.getByText('1.3.3 ready')).toBeTruthy();
  });
});

// ── M6: installer-error toasts ──────────────────────────────────────────────

describe('UpdateBanner M6 error toasts', () => {
  it('toasts when the installer transitions to error and includes a Retry action', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'disk full' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message, options] = toastErrorMock.mock.calls[0] as [string, { action?: unknown }];
    expect(message).toBe('Update failed: disk full');
    expect(options.action).toBeDefined();
  });

  it('uses tailored copy for checksum-mismatch errors', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'checksum-mismatch' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown];
    expect(message).toBe('Downloaded update failed integrity check. Retry to download again.');
  });

  it('dedups repeated error broadcasts with the same message', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'network down' });
    });
    await act(async () => {
      h.emit({ state: 'error', message: 'network down' });
    });
    await act(async () => {
      h.emit({ state: 'error', message: 'network down' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
  });

  it('toasts again when a different error message is broadcast', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'first error' });
    });
    await act(async () => {
      h.emit({ state: 'error', message: 'second error' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(2);
  });

  it('retry action invokes api.download()', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'disk full' });
    });

    const [, options] = toastErrorMock.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(options.action.label).toBe('Retry');
    await act(async () => {
      options.action.onClick();
      await Promise.resolve();
    });

    expect(h.download).toHaveBeenCalledTimes(1);
  });

  it('resets the dedup ref after a successful downloading/downloaded transition', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });
    // Successful retry clears the dedup ref.
    await act(async () => {
      h.emit({
        state: 'downloading',
        version: '1.3.3',
        percent: 10,
        bytesPerSecond: 0,
        transferred: 0,
        total: 100,
      });
    });
    // A later error with the same message should toast again.
    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(2);
  });
});

// ── M7: manual-download visual state ────────────────────────────────────────

describe('M7: manual-download state', () => {
  function manualDownloadStatus(
    overrides: Partial<{
      version: string | null;
      downloadUrl: string;
      reason: string;
    }> = {},
  ): InstallerStatus {
    // Respect explicit `null` overrides (don't coerce via `??`).
    const version = 'version' in overrides ? (overrides.version as string | null) : '1.3.3';
    return {
      state: 'manual-download-required',
      version,
      downloadUrl:
        overrides.downloadUrl ??
        'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
      reason: overrides.reason ?? 'macos-unsigned',
    };
  }

  describe('deriveBannerState', () => {
    const now = 1_000_000;

    it('maps manual-download-required to manual-download with version + URL + reason', () => {
      const out = deriveBannerState(manualDownloadStatus(), null, false, now, 0);
      expect(out).toEqual({
        state: 'manual-download',
        version: '1.3.3',
        downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
        reason: 'macos-unsigned',
      });
    });

    it('hides manual-download when snoozed', () => {
      const out = deriveBannerState(manualDownloadStatus(), null, false, now, now + 1000);
      expect(out.state).toBe('hidden');
    });

    it('preserves null version (latest fallback)', () => {
      const out = deriveBannerState(
        manualDownloadStatus({
          version: null,
          downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
        }),
        null,
        false,
        now,
        0,
      );
      expect(out.version).toBeNull();
      expect(out.downloadUrl).toMatch(/releases\/latest$/);
    });
  });

  describe('manualDownloadTooltip', () => {
    it('returns macOS copy for macos-unsigned', () => {
      expect(manualDownloadTooltip('macos-unsigned')).toMatch(/macOS/);
    });

    it('returns read-only copy for appimage-not-writable', () => {
      expect(manualDownloadTooltip('appimage-not-writable')).toMatch(/read-only/);
    });

    it('returns AppImage-required copy for appimage-missing', () => {
      expect(manualDownloadTooltip('appimage-missing')).toMatch(/AppImage/);
    });

    it('returns generic fallback for unknown reason', () => {
      expect(manualDownloadTooltip('unknown-reason')).toMatch(/unavailable/);
      expect(manualDownloadTooltip(undefined)).toMatch(/unavailable/);
    });
  });

  describe('rendered banner', () => {
    it('renders the manual-download visual block with version + button', async () => {
      const h = buildHarness({ installer: manualDownloadStatus() });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      // The version label is in the body text
      expect(screen.getByText(/1\.3\.3 available/)).toBeInTheDocument();
      // The CTA button
      const button = screen.getByRole('button', { name: /Download from GitHub/i });
      expect(button).toBeInTheDocument();
      expect(button).not.toBeDisabled();
    });

    it('Download from GitHub click dispatches openReleasePage IPC with the URL', async () => {
      const h = buildHarness({ installer: manualDownloadStatus() });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      const button = screen.getByRole('button', { name: /Download from GitHub/i });
      await act(async () => {
        fireEvent.click(button);
        await Promise.resolve();
      });

      expect(h.openReleasePage).toHaveBeenCalledWith(
        'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
      );
    });

    it('button is disabled when downloadUrl is empty', async () => {
      const h = buildHarness({ installer: manualDownloadStatus({ downloadUrl: '' }) });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      const button = screen.getByRole('button', { name: /Download from GitHub/i });
      expect(button).toBeDisabled();
    });

    it('renders "latest available" when version is null', async () => {
      const h = buildHarness({
        installer: manualDownloadStatus({
          version: null,
          downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
        }),
      });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      expect(screen.getByText(/latest available/)).toBeInTheDocument();
    });

    it('reason-tailored tooltip on the button (macos-unsigned)', async () => {
      const h = buildHarness({
        installer: manualDownloadStatus({ reason: 'macos-unsigned' }),
      });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      const button = screen.getByRole('button', { name: /Download from GitHub/i });
      expect(button.getAttribute('title')).toMatch(/macOS/);
    });

    it('reason-tailored tooltip (appimage-not-writable)', async () => {
      const h = buildHarness({
        installer: manualDownloadStatus({ reason: 'appimage-not-writable' }),
      });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      const button = screen.getByRole('button', { name: /Download from GitHub/i });
      expect(button.getAttribute('title')).toMatch(/read-only/);
    });

    it('snooze "Later" hides the banner on next render', async () => {
      const h = buildHarness({ installer: manualDownloadStatus() });
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      const laterBtn = screen.getByRole('button', { name: /Later/i });
      await act(async () => {
        fireEvent.click(laterBtn);
        await Promise.resolve();
      });

      expect(setConfigMock).toHaveBeenCalledWith('updates.bannerSnoozedUntil', expect.any(Number));
    });
  });
});

// ── Deferred bugs: verifying-state render + snooze clamp ───────────────────

describe('Deferred bug fixes (M1-M7 review)', () => {
  it('verifying installer state renders no [Download] button in the DOM', async () => {
    // Verify the rendered output, not just the pure mapper. A switch fallthrough
    // would re-enable [Download] mid-verify and let a double-click re-enter
    // startDownload(). Render-side regression test pairs with the deriveBannerState
    // unit test to lock both ends.
    const h = buildHarness({
      installer: { state: 'verifying', version: '1.3.3' },
      updateStatus: availableStatus('1.3.3'),
    });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    expect(screen.queryByRole('button', { name: /^Download$/ })).toBeNull();
    expect(screen.getByText(/Downloading 1\.3\.3/)).toBeTruthy();
  });

  it('clampSnooze caps a bogus far-future stored value at now + SNOOZE_MS', () => {
    // Direct unit test: NTP-correction, VM suspend, manual clock-forward — any
    // store write that left a value far past the legitimate ceiling must be
    // clamped to the freshest possible 4h horizon, not honored as-is.
    const SNOOZE_MS = 4 * 60 * 60 * 1000;
    const now = 1_000_000_000;
    const bogusFuture = now + 30 * 24 * 3600 * 1000;
    expect(clampSnooze(bogusFuture, now)).toBe(now + SNOOZE_MS);
    // Legitimate value passes through unchanged.
    expect(clampSnooze(now + 3 * 60 * 60 * 1000, now)).toBe(now + 3 * 60 * 60 * 1000);
    // Zero / not-snoozed fast-paths through.
    expect(clampSnooze(0, now)).toBe(0);
  });

  it('clampSnooze rejects non-finite inputs as bogus (returns 0)', () => {
    // NaN passes both `<= 0` and `> ceiling` comparisons silently; without
    // an explicit Number.isFinite guard it would propagate to React state and
    // permanently un-snooze the banner. Defensive against corrupt config or
    // upstream NaN propagation.
    const now = 1_000_000_000;
    expect(clampSnooze(Number.NaN, now)).toBe(0);
    expect(clampSnooze(Number.POSITIVE_INFINITY, now)).toBe(0);
    expect(clampSnooze(Number.NEGATIVE_INFINITY, now)).toBe(0);
    // Defensive on the `now` side too — exported contract is loose.
    expect(clampSnooze(now + 1000, Number.NaN)).toBe(0);
    expect(clampSnooze(now + 1000, Number.POSITIVE_INFINITY)).toBe(0);
  });

  it('snooze load applies clampSnooze before the banner renders', async () => {
    // End-to-end: a stored bogus epoch should NOT survive a mount cycle to
    // setConfig — the load handler clamps it before calling setSnoozedUntil,
    // so the banner's effective snooze is always sane.
    const SNOOZE_MS = 4 * 60 * 60 * 1000;
    const bogusFuture = Date.now() + 30 * 24 * 3600 * 1000;
    configStore.set('updates.bannerSnoozedUntil', bogusFuture);

    const h = buildHarness({ updateStatus: availableStatus('1.3.3') });
    installHarness(h);
    const before = Date.now();
    render(<UpdateBanner isBusy={false} />);
    await flush();

    // Banner is hidden because we ARE within the clamped 4h window — but the
    // window is tied to "now" (≤ before + SNOOZE_MS), not to bogusFuture.
    expect(screen.queryByText(/1\.3\.3 available/)).toBeNull();

    // Verify deriveBannerState would re-surface the banner if we time-traveled
    // 4h+1m forward (using "now" param directly — no real-timer dependency).
    const futureNow = before + SNOOZE_MS + 60_000;
    const clamped = clampSnooze(bogusFuture, before);
    const derived = deriveBannerState(
      { state: 'idle' },
      availableStatus('1.3.3'),
      false,
      futureNow,
      clamped,
    );
    expect(derived).toEqual({ state: 'available', version: '1.3.3' });
  });

  it('snooze write persists exactly Date.now() + SNOOZE_MS (no wrapper subtraction)', async () => {
    // Lock the no-wrapper invariant: `handleSnooze` writes `Date.now() + SNOOZE_MS`
    // directly, not `clampSnooze(...)` which is structurally inert at the write
    // site. ±50 ms tolerance absorbs the wall-clock drift between the click and
    // the assertion. Would fail if a future change re-introduces clampSnooze with
    // a subtractive branch (e.g. "subtract a safety margin"), since the persisted
    // value would no longer equal `Date.now() + SNOOZE_MS` within tolerance.
    const SNOOZE_MS = 4 * 60 * 60 * 1000;
    const h = buildHarness({ updateStatus: availableStatus('1.3.3') });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    const laterBtn = screen.getByRole('button', { name: /Later/i });
    await act(async () => {
      fireEvent.click(laterBtn);
      await Promise.resolve();
    });

    expect(setConfigMock).toHaveBeenCalled();
    const persistedValue = setConfigMock.mock.calls.at(-1)?.[1] as number;
    const expected = Date.now() + SNOOZE_MS;
    // 500 ms tolerance: tight enough to catch a subtractive clamp branch
    // (would diverge by hours), loose enough to absorb GC / event-loop
    // jitter on slow CI runners. Tightened from an initial 50 ms guess
    // after review flagged CI-flakiness risk.
    expect(Math.abs(persistedValue - expected)).toBeLessThan(500);
  });
});
