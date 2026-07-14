import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useModelDownloads } from '../useModelDownloads';

const toastMessage = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (m: string) => toastMessage(m),
    error: (m: string) => toastMessage(m),
    warning: (m: string) => toastMessage(m),
  },
}));

const dockerDownload = vi.fn();
const dockerRemove = vi.fn();
const ggmlToHost = vi.fn();
const mlxDownload = vi.fn();
const mlxRemove = vi.fn();
const refreshCacheStatus = vi.fn();
const refreshHostCacheStatus = vi.fn();

// A GGML model id. This is what triggers the WSL2 host-cache branch.
const GGML = 'ggml-large-v3-turbo-q8_0.bin';
const HF = 'Systran/faster-whisper-medium';

beforeEach(() => {
  [dockerDownload, dockerRemove, ggmlToHost, mlxDownload, mlxRemove].forEach((m) =>
    m.mockReset().mockResolvedValue(undefined),
  );
  refreshCacheStatus.mockReset();
  refreshHostCacheStatus.mockReset();
  toastMessage.mockReset();
  (window as any).electronAPI = {
    docker: {
      downloadModelToCache: dockerDownload,
      removeModelCache: dockerRemove,
      downloadGgmlModelToHost: ggmlToHost,
    },
    mlx: { downloadModelToCache: mlxDownload, removeModelCache: mlxRemove },
  };
});

afterEach(() => {
  delete (window as any).electronAPI;
});

function setup(runtimeProfile = 'gpu', isMetal = false) {
  return renderHook(() =>
    useModelDownloads({ isMetal, runtimeProfile, refreshCacheStatus, refreshHostCacheStatus }),
  );
}

describe('useModelDownloads', () => {
  it('downloads into the container cache on Docker', async () => {
    const { result } = setup();

    await act(() => result.current.downloadModel(HF));

    expect(dockerDownload).toHaveBeenCalledWith(HF);
    expect(refreshCacheStatus).toHaveBeenCalledWith([HF]);
  });

  it('downloads via the MLX bridge on Metal', async () => {
    const { result } = setup('metal', true);

    await act(() => result.current.downloadModel('mlx-community/parakeet-tdt-0.6b-v3'));

    expect(mlxDownload).toHaveBeenCalled();
    expect(dockerDownload).not.toHaveBeenCalled();
  });

  // The branch that is easy to lose. On WSL2 the GGML weights go to the Windows
  // host, not into the container, and they have their own cache probe.
  it('routes GGML models to the Windows host cache on vulkan-wsl2', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.downloadModel(GGML));

    expect(ggmlToHost).toHaveBeenCalledWith(GGML);
    expect(dockerDownload).not.toHaveBeenCalled();
    expect(refreshHostCacheStatus).toHaveBeenCalledWith([GGML]);
  });

  it('still uses the container cache for non-GGML models on vulkan-wsl2', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.downloadModel(HF));

    expect(dockerDownload).toHaveBeenCalledWith(HF);
    expect(ggmlToHost).not.toHaveBeenCalled();
  });

  it('does NOT route GGML to the host cache on plain vulkan (only wsl2)', async () => {
    const { result } = setup('vulkan');

    await act(() => result.current.downloadModel(GGML));

    expect(ggmlToHost).not.toHaveBeenCalled();
    expect(dockerDownload).toHaveBeenCalledWith(GGML);
  });

  it('tracks which models are in flight', async () => {
    let release: () => void = () => {};
    dockerDownload.mockImplementation(() => new Promise<void>((r) => (release = r)));
    const { result } = setup();

    act(() => {
      void result.current.downloadModel(HF);
    });

    await waitFor(() => expect(result.current.downloadingIds.has(HF)).toBe(true));

    await act(async () => {
      release();
    });

    await waitFor(() => expect(result.current.downloadingIds.has(HF)).toBe(false));
  });

  it('clears the in-flight marker even when the download fails', async () => {
    dockerDownload.mockRejectedValue(new Error('network down'));
    const { result } = setup();

    await act(() => result.current.downloadModel(HF));

    expect(result.current.downloadingIds.size).toBe(0);
    expect(toastMessage).toHaveBeenCalledWith(expect.stringMatching(/network down/));
  });

  it('removes from the container cache on Docker', async () => {
    const { result } = setup();

    await act(() => result.current.removeModel(HF));

    expect(dockerRemove).toHaveBeenCalledWith(HF);
    expect(refreshCacheStatus).toHaveBeenCalledWith([HF]);
  });

  it('removes via the MLX bridge on Metal', async () => {
    const { result } = setup('metal', true);

    await act(() => result.current.removeModel('mlx-community/parakeet-tdt-0.6b-v3'));

    expect(mlxRemove).toHaveBeenCalled();
    expect(dockerRemove).not.toHaveBeenCalled();
  });

  // Removing a host-side GGML model is not wired through IPC. Tell the user how
  // to do it by hand rather than failing quietly.
  it('explains that GGML removal on vulkan-wsl2 must be done by hand', async () => {
    const { result } = setup('vulkan-wsl2');

    await act(() => result.current.removeModel(GGML));

    expect(dockerRemove).not.toHaveBeenCalled();
    expect(toastMessage).toHaveBeenCalledWith(expect.stringMatching(/manually/i));
  });
});
