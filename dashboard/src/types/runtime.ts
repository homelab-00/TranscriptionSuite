/**
 * Canonical RuntimeProfile type — import from here instead of defining locally.
 *
 * Also declared as an ambient type in electron.d.ts (for StartContainerOptions)
 * and in electron/preload.ts (isolated Electron main-process build).
 * Keep all three in sync when adding new profiles.
 */
export type RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'metal';
