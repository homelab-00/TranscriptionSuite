/**
 * Issue #87 — User-facing "Blur effects" boot-time application.
 *
 * Read the persisted blur-effects choice from localStorage and apply
 * `data-blur-effects="off"` to the document element if the user has
 * disabled blur. Runs synchronously before first paint to avoid a
 * flash-of-blur on cold start.
 *
 * In Electron, electron-store is the canonical source of truth and
 * is async via IPC. SettingsModal.tsx mirrors the value to localStorage
 * on Save so this synchronous boot-time read sees the latest choice.
 *
 * Default behavior (no entry, parse failure, missing storage, or any
 * access error) is blur ON — matching the documented default and
 * preserving the iOS-glass design when the toggle has never been used.
 */

export const BLUR_EFFECTS_STORAGE_KEY = 'ts-config:ui.blurEffectsEnabled';

type StorageReader = Pick<Storage, 'getItem'>;

function defaultStorage(): StorageReader | null {
  return typeof localStorage !== 'undefined' ? localStorage : null;
}

function defaultDocument(): Document | null {
  return typeof document !== 'undefined' ? document : null;
}

/**
 * Synchronously read the persisted Blur effects choice. Returns the
 * boolean equivalent, defaulting to true (blur ON) for any failure mode:
 * missing storage, missing key, JSON parse failure, or storage.getItem
 * throwing. Used by both `applyBlurEffectsBoot` (DOM-mutating boot path)
 * and by SettingsModal to seed `savedBlurEffectsRef` so the modal-close
 * revert branch agrees with what the boot probe actually applied.
 */
export function readPersistedBlurEffects(
  storage: StorageReader | null = defaultStorage(),
): boolean {
  if (!storage) return true;
  try {
    const raw = storage.getItem(BLUR_EFFECTS_STORAGE_KEY);
    if (raw !== null) return JSON.parse(raw) !== false;
  } catch {
    // fall through to default ON
  }
  return true;
}

export function applyBlurEffectsBoot(
  storage: StorageReader | null = defaultStorage(),
  doc: Document | null = defaultDocument(),
): void {
  if (!doc) return;
  if (!readPersistedBlurEffects(storage)) {
    doc.documentElement.dataset.blurEffects = 'off';
  }
}
