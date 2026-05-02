/**
 * WSL2 + GPU paravirtualization detection (GH-101 follow-up).
 *
 * Used to gate the experimental `'vulkan-wsl2'` runtime profile. The probe runs
 * once per dashboard session (single-flight cached Promise) and returns:
 *
 *   - `available`: Docker is running with the WSL2 backend (vs Hyper-V or no Docker).
 *   - `gpuPassthroughDetected`: a throwaway probe container could see /dev/dxg
 *     and the WSL user-mode driver bundle at /usr/lib/wsl/lib/libd3d12.so.
 *
 * Both signals must be true for the dashboard to surface the Vulkan-WSL2
 * profile button. The legacy `'vulkan'` profile path is unaffected.
 *
 * Why two signals: `docker info` tells us *which Docker engine* is running, but
 * not whether `/dev/dxg` is reachable from inside an arbitrary container.
 * Docker Desktop only auto-binds GPU paths for `--gpus all` (NVIDIA CUDA);
 * non-NVIDIA paths require explicit `--device /dev/dxg -v /usr/lib/wsl:...`.
 * The throwaway probe confirms both binds resolve, distinguishing
 * "WSL2 backend exists" from "GPU paravirtualization is wired up".
 */

export interface WslSupport {
  available: boolean;
  gpuPassthroughDetected: boolean;
  reason?: string;
}

export interface WslDetectDeps {
  /** Returns stdout of `docker info`. Should reject on non-zero exit. */
  runDockerInfo: () => Promise<string>;
  /**
   * Optional: returns stdout of `docker info --format '{{json .}}'`. When
   * provided, `doDetect` prefers the structured JSON path and falls back to
   * `runDockerInfo` only if the JSON output is malformed or the call rejects.
   * Defended against future Docker label tweaks (e.g. `Server:`/`Client:`
   * header shifts) that the text parser pattern-matches.
   */
  runDockerInfoJson?: () => Promise<string>;
  /**
   * Runs a tiny throwaway container with /dev/dxg + /usr/lib/wsl mounts and
   * returns true if both resolve. Best-effort: on any failure (image missing,
   * mount denied, kernel missing), returns false.
   */
  runDockerProbe: () => Promise<boolean>;
}

/**
 * Pure parser for `docker info` output. Inspects two well-known fields:
 *   - `OperatingSystem: Docker Desktop` (Docker Desktop in use vs native engine).
 *   - `Kernel Version: ...microsoft-standard-WSL2...` (WSL2 backend vs Hyper-V).
 *
 * Both must match for the WSL2 backend to be considered available.
 */
export function parseDockerInfoForWsl(stdout: string): {
  available: boolean;
  reason?: string;
} {
  if (!stdout || typeof stdout !== 'string') {
    return { available: false, reason: 'docker info returned empty output' };
  }

  const lines = stdout.split(/\r?\n/);
  let isDockerDesktop = false;
  let kernelLine = '';
  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith('Operating System:')) {
      isDockerDesktop = line.includes('Docker Desktop');
    } else if (line.startsWith('Kernel Version:')) {
      kernelLine = line.slice('Kernel Version:'.length).trim();
    }
  }

  if (!isDockerDesktop) {
    return {
      available: false,
      reason:
        'Docker is not running as Docker Desktop (Vulkan WSL2 requires Docker Desktop on Windows).',
    };
  }
  if (!/wsl2/i.test(kernelLine)) {
    return {
      available: false,
      reason:
        'Docker Desktop is using the Hyper-V backend, not WSL2. Switch to the WSL2 backend in Docker Desktop settings.',
    };
  }
  return { available: true };
}

/**
 * Pure parser for `docker info --format '{{json .}}'`. Reads the structured
 * `OperatingSystem` and `KernelVersion` fields directly, dodging the future
 * upstream-label-shift hazard the text parser carries.
 *
 * Returns the same `{available, reason}` shape as `parseDockerInfoForWsl`.
 * The sentinel reason `'malformed JSON output'` is reserved for the doDetect
 * fallback path — callers can pattern-match it to retry with the text parser.
 */
export function parseDockerInfoJsonForWsl(stdout: string): {
  available: boolean;
  reason?: string;
} {
  if (!stdout || typeof stdout !== 'string') {
    return { available: false, reason: 'docker info returned empty output' };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return { available: false, reason: 'malformed JSON output' };
  }

  // Reject arrays (typeof === 'object' but not the field bag we expect) and
  // primitives. `docker info --format '{{json .}}'` always returns an object.
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { available: false, reason: 'malformed JSON output' };
  }

  const obj = parsed as Record<string, unknown>;
  const operatingSystem = typeof obj.OperatingSystem === 'string' ? obj.OperatingSystem : '';
  const kernelVersion = typeof obj.KernelVersion === 'string' ? obj.KernelVersion : '';

  const isDockerDesktop = operatingSystem.includes('Docker Desktop');
  if (!isDockerDesktop) {
    return {
      available: false,
      reason:
        'Docker is not running as Docker Desktop (Vulkan WSL2 requires Docker Desktop on Windows).',
    };
  }
  if (!/wsl2/i.test(kernelVersion)) {
    return {
      available: false,
      reason:
        'Docker Desktop is using the Hyper-V backend, not WSL2. Switch to the WSL2 backend in Docker Desktop settings.',
    };
  }
  return { available: true };
}

/**
 * Run the actual probe. Single-flight cached Promise — calling more than once
 * returns the same result for the lifetime of the process.
 *
 * **Cache invalidation policy:** the cached Promise is cleared on REJECTION
 * so a transient failure (Docker daemon starting, network glitch, image pull
 * blocked) does not lock the dashboard into a permanent negative result. A
 * resolved-but-negative result (`available: false` or `gpuPassthroughDetected:
 * false`) is still cached — that's a deliberate state that won't change
 * mid-session without a Docker Desktop backend toggle (which the user will
 * notice and can recover from with a dashboard restart).
 *
 * Tests should NOT use this directly; they should call `_resetWslSupportCacheForTests()`
 * between cases or pass deps directly into a helper that bypasses the cache.
 */
let _wslSupportPromise: Promise<WslSupport> | null = null;

export function detectWslGpuPassthrough(deps: WslDetectDeps): Promise<WslSupport> {
  if (!_wslSupportPromise) {
    _wslSupportPromise = doDetect(deps).catch((err) => {
      // Clear the cache so the next call retries instead of sticking on
      // the rejected promise forever.
      _wslSupportPromise = null;
      throw err;
    });
  }
  return _wslSupportPromise;
}

/**
 * Clears the cached probe result. Safe to call mid-session — the next
 * `detectWslGpuPassthrough()` call will re-run `docker info` + the probe.
 * Used by the dashboard's "Re-detect GPU" affordance to recover from a
 * Docker Desktop WSL2 ↔ Hyper-V backend toggle without an Electron restart.
 */
export function resetWslSupportCache(): void {
  _wslSupportPromise = null;
}

/**
 * @deprecated Use `resetWslSupportCache()`. Kept as an alias for back-compat
 * with existing tests that call the underscore-prefixed variant.
 */
export const _resetWslSupportCacheForTests = resetWslSupportCache;

async function doDetect(deps: WslDetectDeps): Promise<WslSupport> {
  // Prefer the structured `--format '{{json .}}'` path when available — it
  // dodges the future Docker label-shift hazard the text parser pattern-matches.
  // Fall back to the text parser if the JSON call rejects or returns malformed
  // output, so we never regress below the v1.3.4 detection capability.
  let parsed: { available: boolean; reason?: string } | null = null;
  if (deps.runDockerInfoJson) {
    try {
      const jsonOut = await deps.runDockerInfoJson();
      const jsonParsed = parseDockerInfoJsonForWsl(jsonOut);
      if (jsonParsed.reason !== 'malformed JSON output') {
        parsed = jsonParsed;
      }
    } catch {
      // JSON path threw — drop through to text fallback.
    }
  }

  if (parsed === null) {
    let dockerInfoStdout: string;
    try {
      dockerInfoStdout = await deps.runDockerInfo();
    } catch (err) {
      const reason = err instanceof Error ? err.message : 'docker info failed';
      return { available: false, gpuPassthroughDetected: false, reason };
    }
    parsed = parseDockerInfoForWsl(dockerInfoStdout);
  }

  if (!parsed.available) {
    return { available: false, gpuPassthroughDetected: false, reason: parsed.reason };
  }

  let probeOk = false;
  try {
    probeOk = await deps.runDockerProbe();
  } catch {
    probeOk = false;
  }

  if (!probeOk) {
    return {
      available: true,
      gpuPassthroughDetected: false,
      reason:
        '/dev/dxg or /usr/lib/wsl/lib/libd3d12.so was not reachable from inside a probe container. ' +
        'Ensure your Windows GPU driver is current (WDDM 3.0+) and Docker Desktop is using the WSL2 backend.',
    };
  }

  return { available: true, gpuPassthroughDetected: true };
}
