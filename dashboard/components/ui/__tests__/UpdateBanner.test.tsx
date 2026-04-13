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

// ── Import after mocks ──────────────────────────────────────────────────────

import { UpdateBanner, deriveBannerState } from '../UpdateBanner';

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
