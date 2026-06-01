/**
 * GH-87 — One-time migration from the old combined "Low idle usage" toggle
 * to the two independent "Blur effects" + "Idle animations" toggles.
 *
 * The old `ui.lowIdleUsageEnabled=true` mode disabled blur AND froze idle
 * animations together. After the split, that single intent maps to:
 *   - idle animations OFF  (`ui.idleAnimationsEnabled = false`)
 *   - blur effects OFF     (`ui.blurEffectsEnabled = false`)
 * A legacy value of `false` (the old default) simply means animations ON,
 * which is also the new default, so it maps to `idleAnimationsEnabled=true`
 * and leaves blur untouched.
 *
 * Runs synchronously against localStorage BEFORE the boot probes
 * (blurEffectsBoot / idleAnimationsBoot) in `index.tsx`, so the very first
 * painted frame after upgrade already reflects the migrated choice — no
 * flash-of-blur or flash-of-animation. The canonical electron-store copy is
 * updated fire-and-forget via the config IPC bridge. Idempotent: once the
 * new idle key exists, the legacy key is dropped and migration is a no-op.
 *
 * Never throws — it sits on the pre-React critical path.
 */

const LEGACY_LOW_IDLE_KEY = 'ts-config:ui.lowIdleUsageEnabled';
const IDLE_ANIMATIONS_KEY = 'ts-config:ui.idleAnimationsEnabled';
const BLUR_EFFECTS_KEY = 'ts-config:ui.blurEffectsEnabled';

type MigrationStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): MigrationStorage | null {
  return typeof localStorage !== 'undefined' ? localStorage : null;
}

export function migrateLegacyAppearanceConfig(
  storage: MigrationStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    const legacyRaw = storage.getItem(LEGACY_LOW_IDLE_KEY);
    if (legacyRaw === null) return; // nothing to migrate

    // Already migrated on a prior launch — just drop the stale legacy key.
    if (storage.getItem(IDLE_ANIMATIONS_KEY) !== null) {
      storage.removeItem(LEGACY_LOW_IDLE_KEY);
      return;
    }

    const lowIdleWasOn = JSON.parse(legacyRaw) === true;
    storage.setItem(IDLE_ANIMATIONS_KEY, JSON.stringify(!lowIdleWasOn));
    if (lowIdleWasOn) {
      // The old combined mode forced blur off; preserve that.
      storage.setItem(BLUR_EFFECTS_KEY, JSON.stringify(false));
    }
    storage.removeItem(LEGACY_LOW_IDLE_KEY);

    // Mirror to the canonical electron-store copy (async via IPC). Best-effort:
    // localStorage above already covers the synchronous pre-paint read.
    const api = (
      globalThis as { electronAPI?: { config?: { set?: (k: string, v: unknown) => unknown } } }
    ).electronAPI;
    if (api?.config?.set) {
      api.config.set('ui.idleAnimationsEnabled', !lowIdleWasOn);
      if (lowIdleWasOn) api.config.set('ui.blurEffectsEnabled', false);
    }
  } catch {
    // Non-fatal — bootstrap must never throw.
  }
}
