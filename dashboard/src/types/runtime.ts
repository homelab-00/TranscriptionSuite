/**
 * Canonical RuntimeProfile type — import from here instead of defining locally.
 *
 * Also declared as an ambient type in electron.d.ts (for StartContainerOptions)
 * and in electron/preload.ts (isolated Electron main-process build).
 * Keep all three in sync when adding new profiles.
 */
const RUNTIME_PROFILES = ['gpu', 'cpu', 'vulkan', 'metal'] as const;
export type RuntimeProfile = (typeof RUNTIME_PROFILES)[number];

export function isRuntimeProfile(value: unknown): value is RuntimeProfile {
  return typeof value === 'string' && (RUNTIME_PROFILES as readonly string[]).includes(value);
}
