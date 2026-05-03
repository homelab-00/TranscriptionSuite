import { renderHook, act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useFolderPicker } from '../useFolderPicker';

const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

describe('useFolderPicker', () => {
  it('returns the chosen path from electronAPI.fileIO.selectFolder()', async () => {
    const selectFolder = vi.fn().mockResolvedValue('/home/user/Documents');
    (
      window as unknown as {
        electronAPI: { fileIO: { selectFolder: () => Promise<string | null> } };
      }
    ).electronAPI = {
      fileIO: { selectFolder },
    };

    const { result } = renderHook(() => useFolderPicker());
    let chosen: string | null = null;
    await act(async () => {
      chosen = await result.current();
    });

    expect(chosen).toBe('/home/user/Documents');
    expect(selectFolder).toHaveBeenCalledTimes(1);
  });

  it('returns null when the user cancels the dialog', async () => {
    const selectFolder = vi.fn().mockResolvedValue(null);
    (
      window as unknown as {
        electronAPI: { fileIO: { selectFolder: () => Promise<string | null> } };
      }
    ).electronAPI = {
      fileIO: { selectFolder },
    };

    const { result } = renderHook(() => useFolderPicker());
    let chosen: string | null = '/should-be-overwritten';
    await act(async () => {
      chosen = await result.current();
    });

    expect(chosen).toBeNull();
  });

  it('returns null when electronAPI is unavailable (web preview / Vitest jsdom)', async () => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;

    const { result } = renderHook(() => useFolderPicker());
    let chosen: string | null = '/initial';
    await act(async () => {
      chosen = await result.current();
    });

    expect(chosen).toBeNull();
  });

  it('returns null when fileIO bridge is missing the selectFolder method', async () => {
    (window as unknown as { electronAPI: { fileIO: Record<string, never> } }).electronAPI = {
      fileIO: {},
    };

    const { result } = renderHook(() => useFolderPicker());
    let chosen: string | null = '/initial';
    await act(async () => {
      chosen = await result.current();
    });

    expect(chosen).toBeNull();
  });
});
