/**
 * Canonical RuntimeProfile type — import from here instead of defining locally.
 *
 * Also declared as an ambient type in electron.d.ts (for StartContainerOptions)
 * and in electron/preload.ts (isolated Electron main-process build).
 * Keep all three in sync when adding new profiles.
 *
 * `vulkan-wsl2` is an experimental opt-in profile for AMD/Intel GPU acceleration
 * on Windows + Docker Desktop with WSL2 backend (GH-101 follow-up). It is never
 * auto-selected — only surfaced in Settings when detectWslGpuPassthrough()
 * confirms /dev/dxg passthrough. Requires the locally-built sidecar image
 * `transcriptionsuite/whisper-cpp-vulkan-wsl2:latest`.
 */
const RUNTIME_PROFILES = ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'] as const;
export type RuntimeProfile = (typeof RUNTIME_PROFILES)[number];

export function isRuntimeProfile(value: unknown): value is RuntimeProfile {
  return typeof value === 'string' && (RUNTIME_PROFILES as readonly string[]).includes(value);
}

/**
 * Result of probing Docker Desktop for WSL2 GPU paravirtualization (GH-101 follow-up).
 *
 * `available`: Docker is running with the WSL2 backend (vs Hyper-V or no Docker).
 * `gpuPassthroughDetected`: a throwaway probe container could see /dev/dxg + /usr/lib/wsl libs.
 * `reason`: optional human-readable diagnostic for negative results.
 */
export interface WslSupport {
  available: boolean;
  gpuPassthroughDetected: boolean;
  reason?: string;
}
