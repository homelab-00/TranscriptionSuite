import { useCallback } from 'react';

/**
 * useFolderPicker — opens the OS-native folder selection dialog.
 *
 * Wraps `window.electronAPI.fileIO.selectFolder()` (which delegates to
 * Electron `dialog.showOpenDialog({ properties: ['openDirectory'] })`).
 * Returns the chosen absolute path or `null` if the user cancelled.
 *
 * In environments without the Electron preload bridge (Vitest jsdom,
 * web preview), this returns `null` so callers can branch safely.
 *
 * Issue #104, Story 1.4 (FR14, FR51, FR53).
 */
export function useFolderPicker(): () => Promise<string | null> {
  return useCallback(async () => {
    const api = window.electronAPI?.fileIO;
    if (!api?.selectFolder) {
      return null;
    }
    return api.selectFolder();
  }, []);
}
