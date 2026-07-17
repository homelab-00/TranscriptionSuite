import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useModelRemoval } from '../useModelRemoval';

const toastMessage = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (m: string) => toastMessage(m),
    error: (m: string) => toastMessage(m),
    warning: (m: string) => toastMessage(m),
  },
}));

const dockerRemove = vi.fn();
const mlxRemove = vi.fn();
const refreshCacheStatus = vi.fn();

// A GGML model id. This is what triggers the WSL2 host-cache branch.
const GGML = 'ggml-large-v3-turbo-q8_0.bin';
const HF = 'Systran/faster-whisper-medium';

beforeEach(() => {
  [dockerRemove, mlxRemove].forEach((m) => m.mockReset().mockResolvedValue(undefined));
  refreshCacheStatus.mockReset();
  toastMessage.mockReset();
  (window as any).electronAPI = {
    docker: { removeModelCache: dockerRemove },
    mlx: { removeModelCache: mlxRemove },
  };
});

afterEach(() => {
  delete (window as any).electronAPI;
});

function setup(runtimeProfile = 'gpu', isMetal = false) {
  return renderHook(() => useModelRemoval({ isMetal, runtimeProfile, refreshCacheStatus }));
}

describe('useModelRemoval', () => {
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

  // Plain vulkan (Linux) keeps GGML weights in the container volume, so the
  // normal Docker removal path applies.
  it('removes GGML models from the container cache on plain vulkan', async () => {
    const { result } = setup('vulkan');

    await act(() => result.current.removeModel(GGML));

    expect(dockerRemove).toHaveBeenCalledWith(GGML);
  });

  it('surfaces a removal failure as an error toast', async () => {
    dockerRemove.mockRejectedValue(new Error('exec failed'));
    const { result } = setup();

    await act(() => result.current.removeModel(HF));

    expect(toastMessage).toHaveBeenCalledWith(expect.stringMatching(/remove failed/i));
    expect(refreshCacheStatus).not.toHaveBeenCalled();
  });
});
