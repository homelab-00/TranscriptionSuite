/**
 * Writes text to the clipboard, preferring Electron's native clipboard module
 * over navigator.clipboard. The native path works in Flatpak/AppImage sandboxes
 * where the Web Clipboard API is blocked due to missing permissions.
 */
export async function writeToClipboard(text: string): Promise<void> {
  if (typeof window !== 'undefined' && (window as any).electronAPI?.clipboard?.writeText) {
    await (window as any).electronAPI.clipboard.writeText(text);
    return;
  }
  await navigator.clipboard.writeText(text);
}
