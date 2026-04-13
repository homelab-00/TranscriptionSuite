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
  __resetErrorToastDedup,
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
  // Module-level error-toast dedup state persists across renders by design;
  // reset between tests to prevent leaks.
  __resetErrorToastDedup();
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

  // ── Dedup hardening: module-level state + 5 s window + extended clear ──────

  it('time window: same key re-toasts after 5001 ms', async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date(1_000_000));
      const h = buildHarness();
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      await act(async () => {
        h.emit({ state: 'error', message: 'flaky' });
      });
      expect(toastErrorMock).toHaveBeenCalledTimes(1);

      // Advance past the 5 s dedup window without any installer transition
      // that would clear state — pure time-based re-toast.
      vi.setSystemTime(new Date(1_000_000 + 5_001));
      await act(async () => {
        h.emit({ state: 'error', message: 'flaky' });
      });

      expect(toastErrorMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('time window: same key back-to-back dedups', async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date(1_000_000));
      const h = buildHarness();
      installHarness(h);
      render(<UpdateBanner isBusy={false} />);
      await flush();

      await act(async () => {
        h.emit({ state: 'error', message: 'flaky' });
      });
      // Advance well under the window — identical key must dedup.
      vi.setSystemTime(new Date(1_000_000 + 200));
      await act(async () => {
        h.emit({ state: 'error', message: 'flaky' });
      });
      vi.setSystemTime(new Date(1_000_000 + 400));
      await act(async () => {
        h.emit({ state: 'error', message: 'flaky' });
      });

      expect(toastErrorMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('idle transition clears dedup state', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });
    await act(async () => {
      h.emit({ state: 'idle' });
    });
    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(2);
  });

  it('cancelled transition clears dedup state', async () => {
    const h = buildHarness();
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });
    await act(async () => {
      h.emit({ state: 'cancelled' });
    });
    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });

    expect(toastErrorMock).toHaveBeenCalledTimes(2);
  });

  it('two rapid handleRetry calls with identical failure yield a single toast', async () => {
    const h = buildHarness();
    // Both retries resolve with the same {ok:false, reason:'error', message:'X'}
    // — second retry's failure must be absorbed by the 5 s time-window guard.
    h.download.mockResolvedValue({ ok: false, reason: 'error', message: 'flaky' });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    // Emit the initial error so the Retry action is rendered on the toast.
    await act(async () => {
      h.emit({ state: 'error', message: 'initial' });
    });
    expect(toastErrorMock).toHaveBeenCalledTimes(1);

    const [, options] = toastErrorMock.mock.calls[0] as [
      string,
      { action: { onClick: () => void } },
    ];

    // Fire Retry twice without waiting between — simulates the overlapping-
    // retry race the deferred-work item describes.
    await act(async () => {
      options.action.onClick();
      options.action.onClick();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(h.download).toHaveBeenCalledTimes(2);
    // Initial 'initial' toast + first retry-failure toast ('download-error' key).
    // Second retry-failure dedups on the shared 'download-error' key within
    // the window → total 2 toasts, not 3.
    expect(toastErrorMock).toHaveBeenCalledTimes(2);
  });

  it('dedup state survives unmount + remount within 5 s', async () => {
    // Module-level dedupState is intentionally outside the React tree so a
    // remount (StrictMode, parent re-key, future navigation refactor) does
    // NOT wipe the dedup memory. This test locks that contract.
    const h1 = buildHarness();
    installHarness(h1);
    const first = render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h1.emit({ state: 'error', message: 'flaky' });
    });
    expect(toastErrorMock).toHaveBeenCalledTimes(1);

    first.unmount();

    // Remount with a fresh harness. Note we do NOT call __resetErrorToastDedup
    // here — the assertion is that module state carries across the remount.
    const h2 = buildHarness();
    installHarness(h2);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    await act(async () => {
      h2.emit({ state: 'error', message: 'flaky' });
    });

    // Still 1 — same key still in the 5 s window.
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
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

// ── Invocation-failure toasts (split-spec: banner resilience) ──────────────

describe('UpdateBanner invocation-failure toasts', () => {
  async function openModalAndConfirm(h: TestHarness): Promise<void> {
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
  }

  it('download throw → toast surfaces raw Error.message with "Download failed:" prefix', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    h.download.mockRejectedValueOnce(new Error('net down'));
    await openModalAndConfirm(h);

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toMatch(/download failed/i);
    expect(message).toMatch(/net down/);
  });

  it('download returns {ok:false, reason:"error", message} → toast surfaces message', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    h.download.mockResolvedValueOnce({ ok: false, reason: 'error', message: 'disk full' });
    await openModalAndConfirm(h);

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('Download failed: disk full');
  });

  it('download returns {ok:false, reason:"manual-download-required"} → NO toast (installer status drives UI)', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    h.download.mockResolvedValueOnce({
      ok: false,
      reason: 'manual-download-required',
      downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
    });
    await openModalAndConfirm(h);

    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('download returns {ok:false, reason:"incompatible-server", detail} → toast includes server version and range', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    h.download.mockResolvedValueOnce({
      ok: false,
      reason: 'incompatible-server',
      detail: {
        serverVersion: '2.0.0',
        compatibleRange: '>=1.0.0 <2.0.0',
        deployment: 'local',
      },
    });
    await openModalAndConfirm(h);

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toContain('2.0.0');
    expect(message).toContain('>=1.0.0 <2.0.0');
  });

  it('download returns {ok:false, reason:"no-update-available"} → tailored toast copy', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    h.download.mockResolvedValueOnce({ ok: false, reason: 'no-update-available' });
    await openModalAndConfirm(h);

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('No update available to download.');
  });

  it('install throw → toast surfaces raw Error.message with "Install failed:" prefix', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    h.install.mockRejectedValueOnce(new Error('boom'));
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Quit & Install' }));
    await flush();

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toMatch(/install failed/i);
    expect(message).toMatch(/boom/);
  });

  it('install "install-already-requested" dedups: triple-click yields one toast', async () => {
    // Simulate the real IPC contract: first click succeeds (quitAndInstall begins),
    // subsequent clicks land in the `installRequested` guard and return ok:false.
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    h.install
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: false, reason: 'install-already-requested' })
      .mockResolvedValueOnce({ ok: false, reason: 'install-already-requested' });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    const btn = screen.getByRole('button', { name: 'Quit & Install' });
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        fireEvent.click(btn);
        await Promise.resolve();
      });
    }
    await flush();

    expect(h.install).toHaveBeenCalledTimes(3);
    // First click: ok:true → no toast. Second: ok:false → toast. Third: dedup skip.
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('Install already in progress.');
  });

  it('install "no-update-ready" → tailored toast copy', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    h.install.mockResolvedValueOnce({ ok: false, reason: 'no-update-ready' });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Quit & Install' }));
    await flush();

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('No update is ready to install.');
  });

  it('install "no-version" → same tailored copy as no-update-ready', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    h.install.mockResolvedValueOnce({ ok: false, reason: 'no-version' });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Quit & Install' }));
    await flush();

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('No update is ready to install.');
  });

  it('install unknown reason → generic toast with the reason embedded', async () => {
    const h = buildHarness({ installer: { state: 'downloaded', version: '1.3.3' } });
    h.install.mockResolvedValueOnce({ ok: false, reason: 'unforeseen-future-case' });
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    fireEvent.click(screen.getByRole('button', { name: 'Quit & Install' }));
    await flush();

    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toContain('Install failed');
    expect(message).toContain('unforeseen-future-case');
  });

  it('snooze setConfig throw → toast fires AND in-memory state still hides banner', async () => {
    const h = buildHarness({
      installer: { state: 'idle' },
      updateStatus: availableStatus('1.3.3'),
    });
    // Force the setConfig call from handleSnooze to reject on the next invocation.
    setConfigMock.mockRejectedValueOnce(new Error('disk full'));
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    // Banner visible before click.
    expect(screen.getByText('1.3.3 available')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Later' }));
    await flush();

    // Toast surfaces the persistence failure to the user.
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [message] = toastErrorMock.mock.calls[0] as [string, unknown?];
    expect(message).toBe('Could not save snooze preference.');

    // In-memory snoozedUntil was still updated → banner hidden on same tick.
    expect(screen.queryByText('1.3.3 available')).toBeNull();
  });
});

// ── Spec: in-app-update-test-coverage-closeout ────────────────────────
//
// Closes the four M2-review-item-10 sub-points (handleRetry catch arm,
// snooze resurface past 4h, 60s status poll, unmount cleanup).
// Pure-additive; all production-code paths exist already.

describe('Deferred coverage closeout', () => {
  it('handleRetry catch arm: api.download() throw → toast surfaces Download failed: <message>', async () => {
    // Sonner's `toast.error` is mocked (toastErrorMock). The Retry action
    // is captured as `options.action.onClick` on the first toast call.
    // Invoking it with `api.download` mocked to reject reaches
    // handleRetry's catch arm, which calls toastInvocationError(
    // 'download-error', `Download failed: ${msg}`) — surfacing as a
    // SECOND toastError call.
    const h = buildHarness({ installer: { state: 'idle' } });
    h.download.mockRejectedValue(new Error('boom'));
    installHarness(h);
    render(<UpdateBanner isBusy={false} />);
    await flush();

    // First emit drives the banner into 'error' state → first toast.
    await act(async () => {
      h.emit({ state: 'error', message: 'flaky' });
    });
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    const [, options] = toastErrorMock.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(options.action.label).toBe('Retry');

    // User clicks Retry — handleRetry runs api.download() which rejects.
    // The catch arm fires the invocation-error toast.
    await act(async () => {
      options.action.onClick();
      // Allow the rejected Promise + catch arm to settle.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(h.download).toHaveBeenCalledTimes(1);
    // Second toast: the catch-arm invocation-error toast. Pin the
    // shape so a stray dedup/emit regression that produces an
    // unrelated second toast cannot pass spuriously: invocation-error
    // toasts have NO action property (the user can't retry an
    // already-failed retry).
    expect(toastErrorMock).toHaveBeenCalledTimes(2);
    const [secondMessage, secondOptions] = toastErrorMock.mock.calls[1] as [
      string,
      { action?: unknown } | undefined,
    ];
    expect(secondMessage).toBe('Download failed: boom');
    expect(secondOptions?.action).toBeUndefined();
  });

  it('snooze resurface: banner re-appears after fake-timer advance past SNOOZE_MS', async () => {
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

      // Snooze.
      fireEvent.click(screen.getByRole('button', { name: 'Later' }));
      await flush();
      expect(screen.queryByText('1.3.3 available')).toBeNull();

      unmount();
      cleanup();

      // Advance past the 4h snooze window. The banner's nowTimer fires
      // every 30s and re-evaluates `snoozed = snoozedUntil > now`; once
      // we cross the boundary the banner re-derives to `available`.
      vi.setSystemTime(Date.now() + 4 * 60 * 60 * 1000 + 60 * 1000);

      const h2 = buildHarness({
        installer: { state: 'idle' },
        updateStatus: availableStatus(),
      });
      installHarness(h2);

      render(<UpdateBanner isBusy={false} />);
      await flush();

      // Past the snooze window → banner re-appears.
      expect(screen.queryByText('1.3.3 available')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('60s status poll: getStatus call count increments after vi.advanceTimersByTime(60_000)', async () => {
    vi.useFakeTimers();
    try {
      const h = buildHarness({ installer: { state: 'idle' } });
      installHarness(h);

      render(<UpdateBanner isBusy={false} />);
      await flush();

      const mountCalls = h.getStatus.mock.calls.length;
      expect(mountCalls).toBeGreaterThanOrEqual(1);

      // Advance one full 60s poll tick. Pin to EXACTLY +1 (not just
      // "more than mount") so a double-fire regression (e.g. strict-
      // mode artifact, duplicate effect registration) is caught.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(h.getStatus.mock.calls.length).toBe(mountCalls + 1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('unmount cleanup: clearInterval halts the poll AND onInstallerStatus unsubscribe fires', async () => {
    vi.useFakeTimers();
    try {
      // Capture the unsubscribe spy returned by onInstallerStatus.
      const unsubscribe = vi.fn();
      const h = buildHarness({ installer: { state: 'idle' } });
      h.onInstallerStatus.mockImplementation((cb: InstallerListener) => {
        h.listeners.push(cb);
        return () => {
          unsubscribe();
          h.listeners = h.listeners.filter((x) => x !== cb);
        };
      });
      installHarness(h);

      const { unmount } = render(<UpdateBanner isBusy={false} />);
      await flush();

      const callsAtMount = h.getStatus.mock.calls.length;
      // While mounted there are TWO setIntervals running — `statusTimer`
      // (60s poll) and `nowTimer` (30s snooze re-eval). Both must be
      // cleared on unmount; counting active timers post-unmount catches
      // a missed clearInterval that the call-count assertion alone
      // would miss for the nowTimer (which has no observable side
      // effect besides the timer itself).
      const timersWhileMounted = vi.getTimerCount();
      expect(timersWhileMounted).toBeGreaterThanOrEqual(2);

      unmount();

      // After unmount: advance 60s and confirm NO new getStatus poll fires.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(unsubscribe).toHaveBeenCalledTimes(1);
      expect(h.getStatus.mock.calls.length).toBe(callsAtMount);
      // No leaked intervals: the component cleared BOTH setIntervals.
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
