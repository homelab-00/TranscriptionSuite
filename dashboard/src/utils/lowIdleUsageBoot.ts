/**
 * GH-124 Part C / issue 87 — User-facing "Low idle usage" boot-time application.
 *
 * Read the persisted low-idle-usage choice from localStorage and apply
 * `data-low-idle-usage="on"` to the document element if the user has
 * enabled the mode. Runs synchronously before first paint to avoid a
 * flash of full-cost UI on cold start when the user has opted in.
 *
 * In Electron, electron-store is the canonical source of truth and
 * is async via IPC. SettingsModal.tsx mirrors the value to localStorage
 * on Save so this synchronous boot-time read sees the latest choice.
 *
 * Default behavior (no entry, parse failure, missing storage, or any
 * access error) is OFF — the INVERSE of the Blur effects default. OFF
 * preserves the shipped iOS-glass design and the animating idle waves on
 * every platform, so the attribute is only ever applied when the user has
 * explicitly opted in.
 */

export const LOW_IDLE_USAGE_STORAGE_KEY = 'ts-config:ui.lowIdleUsageEnabled';

type StorageReader = Pick<Storage, 'getItem'>;

function defaultStorage(): StorageReader | null {
  return typeof localStorage !== 'undefined' ? localStorage : null;
}

function defaultDocument(): Document | null {
  return typeof document !== 'undefined' ? document : null;
}

/**
 * Synchronously read the persisted Low idle usage choice. Returns the
 * boolean equivalent, defaulting to false (mode OFF) for any failure mode:
 * missing storage, missing key, JSON parse failure, or storage.getItem
 * throwing. Used by both `applyLowIdleUsageBoot` (DOM-mutating boot path)
 * and by SettingsModal to seed `savedLowIdleUsageRef` so the modal-close
 * revert branch agrees with what the boot probe actually applied.
 */
export function readPersistedLowIdleUsage(
  storage: StorageReader | null = defaultStorage(),
): boolean {
  if (!storage) return false;
  try {
    const raw = storage.getItem(LOW_IDLE_USAGE_STORAGE_KEY);
    if (raw !== null) return JSON.parse(raw) === true;
  } catch {
    // fall through to default OFF
  }
  return false;
}

export function applyLowIdleUsageBoot(
  storage: StorageReader | null = defaultStorage(),
  doc: Document | null = defaultDocument(),
): void {
  if (!doc) return;
  if (readPersistedLowIdleUsage(storage)) {
    doc.documentElement.dataset.lowIdleUsage = 'on';
  }
}
