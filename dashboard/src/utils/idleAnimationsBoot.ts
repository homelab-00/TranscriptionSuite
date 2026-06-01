/**
 * GH-87 — User-facing "Idle animations" boot-time application.
 *
 * Read the persisted idle-animations choice from localStorage and apply
 * `data-idle-animations="off"` to the document element if the user has
 * disabled the idle AudioVisualizer wave animations. Runs synchronously
 * before first paint to avoid a flash of animating waves on cold start
 * when the user has opted out.
 *
 * This is the independent successor to the old combined "Low idle usage"
 * mode: it controls ONLY the idle-wave animations and no longer touches
 * `backdrop-filter` (blur is governed solely by blurEffectsBoot). Legacy
 * `ui.lowIdleUsageEnabled` values are mapped to the new split keys by
 * migrateLegacyAppearanceConfig before these probes run.
 *
 * In Electron, electron-store is the canonical source of truth and is
 * async via IPC. SettingsModal.tsx mirrors the value to localStorage on
 * Save so this synchronous boot-time read sees the latest choice.
 *
 * Default behavior (no entry, parse failure, missing storage, or any
 * access error) is ON — matching the shipped iOS-glass design, so the
 * attribute is only ever applied when the user has explicitly opted out.
 */

export const IDLE_ANIMATIONS_STORAGE_KEY = 'ts-config:ui.idleAnimationsEnabled';

type StorageReader = Pick<Storage, 'getItem'>;

function defaultStorage(): StorageReader | null {
  return typeof localStorage !== 'undefined' ? localStorage : null;
}

function defaultDocument(): Document | null {
  return typeof document !== 'undefined' ? document : null;
}

/**
 * Synchronously read the persisted Idle animations choice. Returns the
 * boolean equivalent, defaulting to true (animations ON) for any failure
 * mode: missing storage, missing key, JSON parse failure, or storage.getItem
 * throwing. Used by both `applyIdleAnimationsBoot` (DOM-mutating boot path)
 * and by SettingsModal to seed `savedIdleAnimationsRef` so the modal-close
 * revert branch agrees with the attribute the boot probe actually applied.
 */
export function readPersistedIdleAnimations(
  storage: StorageReader | null = defaultStorage(),
): boolean {
  if (!storage) return true;
  try {
    const raw = storage.getItem(IDLE_ANIMATIONS_STORAGE_KEY);
    if (raw !== null) return JSON.parse(raw) !== false;
  } catch {
    // fall through to default ON
  }
  return true;
}

export function applyIdleAnimationsBoot(
  storage: StorageReader | null = defaultStorage(),
  doc: Document | null = defaultDocument(),
): void {
  if (!doc) return;
  if (!readPersistedIdleAnimations(storage)) {
    doc.documentElement.dataset.idleAnimations = 'off';
  }
}
