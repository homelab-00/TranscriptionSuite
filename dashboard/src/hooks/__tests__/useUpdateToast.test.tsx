import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// --- sonner mock: capture the options so we can invoke action/cancel ---
const toastCalls: Array<{ message: string; options: any }> = [];
const dismissed: string[] = [];
const errorCalls: Array<{ message: string; options: any }> = [];
vi.mock('sonner', () => ({
  toast: Object.assign(
    (message: string, options: any) => {
      toastCalls.push({ message, options });
      return options?.id ?? 'toast-id';
    },
    {
      dismiss: (id: string) => dismissed.push(id),
      error: (message: string, options?: any) => {
        errorCalls.push({ message, options });
      },
    },
  ),
}));

// --- config store mock ---
const configStore = new Map<string, unknown>();
const setConfigMock = vi.fn(async (k: string, v: unknown) => {
  configStore.set(k, v);
});
const getConfigMock = vi.fn(async (k: string) => configStore.get(k));
vi.mock('../../config/store', () => ({
  getConfig: (k: string) => getConfigMock(k),
  setConfig: (k: string, v: unknown) => setConfigMock(k, v),
}));

import { useUpdateToast } from '../useUpdateToast';

let listener: ((p: { version: string; releaseNotes: string | null }) => void) | null = null;
const unsubscribe = vi.fn();

// Mirrors the `updates.download()` IPC return union in src/types/electron.d.ts,
// so mockResolvedValueOnce can supply any of the four variants.
type DownloadResult =
  | { ok: true; reason?: 'already-downloading' }
  | { ok: false; reason: 'no-update-available' | 'error'; message?: string }
  | { ok: false; reason: 'manual-download-required'; downloadUrl: string }
  | {
      ok: false;
      reason: 'incompatible-server';
      detail: { serverVersion: string; compatibleRange: string; deployment: 'local' | 'remote' };
    };
const downloadMock = vi.fn(async (): Promise<DownloadResult> => ({ ok: true }));

function installStub() {
  (window as any).electronAPI = {
    updates: {
      onUpdateAvailable: vi.fn((cb: any) => {
        listener = cb;
        return unsubscribe;
      }),
      download: downloadMock,
      openReleasePage: vi.fn(async () => ({ ok: true })),
    },
  };
}

beforeEach(() => {
  toastCalls.length = 0;
  dismissed.length = 0;
  errorCalls.length = 0;
  configStore.clear();
  listener = null;
  vi.clearAllMocks();
  installStub();
});
afterEach(() => {
  delete (window as any).electronAPI;
});

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('useUpdateToast', () => {
  it('subscribes on mount and unsubscribes on unmount', () => {
    const { unmount } = renderHook(() => useUpdateToast());
    expect((window as any).electronAPI.updates.onUpdateAvailable).toHaveBeenCalledTimes(1);
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('shows an Update/Dismiss toast when a new version is pushed', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => {
      listener?.({ version: '1.4.0', releaseNotes: null });
    });
    await flush();
    expect(toastCalls).toHaveLength(1);
    expect(toastCalls[0].options.action.label).toBe('Update');
    expect(toastCalls[0].options.cancel.label).toBe('Dismiss');
    expect(toastCalls[0].options.duration).toBe(Infinity);
  });

  it('Update triggers download()', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.action.onClick();
    });
    expect(downloadMock).toHaveBeenCalledTimes(1);
  });

  it('Dismiss persists updates.dismissedAppVersion', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.cancel.onClick();
    });
    expect(setConfigMock).toHaveBeenCalledWith('updates.dismissedAppVersion', '1.4.0');
  });

  it('does not re-show a version the user already dismissed', async () => {
    configStore.set('updates.dismissedAppVersion', '1.4.0');
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    expect(toastCalls).toHaveLength(0);
  });

  it('routes Update to the release page when download returns manual-download-required', async () => {
    downloadMock.mockResolvedValueOnce({
      ok: false,
      reason: 'manual-download-required',
      downloadUrl: 'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.4.0',
    });
    const openReleasePage = (window as any).electronAPI.updates.openReleasePage;
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.action.onClick();
    });
    await flush();
    expect(openReleasePage).toHaveBeenCalledWith(
      'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.4.0',
    );
  });

  it('shows an error toast when download fails', async () => {
    downloadMock.mockResolvedValueOnce({ ok: false, reason: 'error', message: 'boom' });
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => {
      await toastCalls[0].options.action.onClick();
    });
    await flush();
    expect(errorCalls.some((c) => c.message === 'boom')).toBe(true);
  });

  it('uses a stable per-version toast id so repeat pushes coalesce', async () => {
    renderHook(() => useUpdateToast());
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    await act(async () => listener?.({ version: '1.4.0', releaseNotes: null }));
    await flush();
    expect(toastCalls).toHaveLength(2);
    expect(toastCalls[0].options.id).toBe('update-available-1.4.0');
    expect(toastCalls[1].options.id).toBe(toastCalls[0].options.id);
  });
});
