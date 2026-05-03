import { useCallback } from 'react';

/**
 * useFileSaveDialog — opens the OS-native file-save dialog (Issue #104,
 * Story 3.5). Returns the user-chosen absolute path or `null` if cancelled
 * or unsupported.
 *
 * In environments without the Electron preload bridge (Vitest jsdom, web
 * preview), returns `null` so callers can branch safely. Same fallback
 * convention as `useFolderPicker` (Story 1.4).
 */
export interface SaveDialogOptions {
  /** Suggested filename + parent directory. */
  defaultPath?: string;
  /** File-type filters shown in the dialog. */
  filters?: { name: string; extensions: string[] }[];
}

export function useFileSaveDialog(): (opts?: SaveDialogOptions) => Promise<string | null> {
  return useCallback(async (opts?: SaveDialogOptions) => {
    const api = window.electronAPI?.fileIO;
    if (!api?.saveFile) {
      return null;
    }
    return api.saveFile(opts ?? {});
  }, []);
}
