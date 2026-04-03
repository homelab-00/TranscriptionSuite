/**
 * Container runtime detection — Docker vs Podman.
 *
 * Detects which container runtime is available on the system, caches
 * the result, and exports the resolved binary name and runtime-specific
 * configuration.  Podman's CLI is a Docker drop-in, so most commands
 * work identically with just a binary-name swap.
 *
 * Detection order:
 *   1. CONTAINER_RUNTIME env override ('docker' | 'podman')
 *   2. `docker version` — validates daemon connectivity
 *   3. `podman version` — validates Podman availability
 *   4. Falls back to binary presence checks for better error messaging
 */

import { execFile } from 'child_process';
import net from 'net';
import { promisify } from 'util';
import { existsSync } from 'fs';
import path from 'path';

const execFileAsync = promisify(execFile);

// ─── Types ───────────────────────────────────────────────────────────────────

export type ContainerRuntimeKind = 'docker' | 'podman';

export interface ContainerRuntime {
  /** Which runtime was detected */
  kind: ContainerRuntimeKind;
  /** Binary name to use for CLI commands ('docker' or 'podman') */
  bin: string;
  /** Display name for UI labels */
  displayName: string;
}

export interface DetectionResult {
  runtime: ContainerRuntime | null;
  /** True if binary was found but daemon/service is not running */
  binaryFoundButNotRunning: boolean;
  /** Which binary was found (for error messaging) */
  binaryFound: string | null;
  /** True when Podman CLI works but the API socket is not listening */
  socketDead?: boolean;
  /** Actionable guidance for the user when detection fails */
  guidance?: string;
}

// ─── Socket Paths ────────────────────────────────────────────────────────────

export interface SocketPaths {
  system: string;
  user: (uid: number) => string;
  envVar: string;
}

export const DOCKER_SOCKET_PATHS: SocketPaths = {
  system: '/var/run/docker.sock',
  user: (uid: number) => `/run/user/${uid}/docker.sock`,
  envVar: 'DOCKER_HOST',
};

export const PODMAN_SOCKET_PATHS: SocketPaths = {
  system: '/var/run/podman/podman.sock',
  user: (uid: number) => `/run/user/${uid}/podman/podman.sock`,
  envVar: 'CONTAINER_HOST',
};

export function getSocketPaths(kind: ContainerRuntimeKind): SocketPaths {
  return kind === 'podman' ? PODMAN_SOCKET_PATHS : DOCKER_SOCKET_PATHS;
}

// ─── Detection ───────────────────────────────────────────────────────────────

let cachedResult: DetectionResult | null = null;

function buildDetectionEnv(): NodeJS.ProcessEnv {
  const delimiter = path.delimiter;
  const currentPath = process.env.PATH ?? '';
  const defaultPathEntries =
    process.platform === 'win32'
      ? ['C:\\Program Files\\Docker\\Docker\\resources\\bin']
      : ['/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  const mergedPath = Array.from(
    new Set([...currentPath.split(delimiter).filter(Boolean), ...defaultPathEntries]),
  ).join(delimiter);
  return { ...process.env, PATH: mergedPath };
}

async function tryExec(cmd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync(cmd, args, {
    env: buildDetectionEnv(),
    timeout: 10_000,
  });
  return stdout.trim();
}

async function probeRuntime(bin: string): Promise<boolean> {
  try {
    await tryExec(bin, ['version', '--format', '{{.Server.Version}}']);
    return true;
  } catch {
    return false;
  }
}

async function probeBinary(bin: string): Promise<boolean> {
  try {
    await tryExec(bin, ['--version']);
    return true;
  } catch {
    return false;
  }
}

/**
 * Verify that the API socket for a container runtime is actually listening.
 * Podman's CLI can work without a socket (it forks internally), but
 * `docker-compose` (used by `podman compose` as external provider) requires
 * an active socket.  Returns true if a TCP/Unix connection succeeds.
 */
async function probeSocket(kind: ContainerRuntimeKind): Promise<boolean> {
  if (process.platform !== 'linux') return true; // macOS/Windows use Docker Desktop
  if (typeof process.getuid !== 'function') return true;

  // If an explicit host is configured (e.g. tcp://...), the socket file check
  // is irrelevant — the runtime will connect via the configured transport.
  const paths = getSocketPaths(kind);
  if (process.env[paths.envVar] || process.env.DOCKER_HOST) return true;

  const uid = process.getuid();
  // Prefer user socket for rootless, fall back to system socket
  const candidates = [paths.user(uid), paths.system];
  const socketPath = candidates.find((p) => existsSync(p));
  if (!socketPath) {
    console.warn(`[ContainerRuntime] No ${kind} socket file found at: ${candidates.join(', ')}`);
    return false;
  }
  console.log(`[ContainerRuntime] Probing ${kind} socket at ${socketPath}`);

  return new Promise<boolean>((resolve) => {
    const sock = net.connect({ path: socketPath });
    const timer = setTimeout(() => {
      sock.destroy();
      resolve(false);
    }, 3_000);
    sock.on('connect', () => {
      clearTimeout(timer);
      sock.destroy();
      resolve(true);
    });
    sock.on('error', () => {
      clearTimeout(timer);
      sock.destroy();
      resolve(false);
    });
  });
}

const PODMAN_SOCKET_GUIDANCE =
  'Podman was detected but its API socket is not active. ' +
  'External compose providers (docker-compose) require the socket to be running. ' +
  'Fix: run  systemctl --user enable --now podman.socket  — ' +
  'then click "Retry Detection" in the app.';

function makeRuntime(kind: ContainerRuntimeKind): ContainerRuntime {
  return {
    kind,
    bin: kind,
    displayName: kind === 'podman' ? 'Podman' : 'Docker',
  };
}

/**
 * Detect the available container runtime.
 *
 * Checks in order:
 *   1. CONTAINER_RUNTIME env override
 *   2. Docker daemon connectivity
 *   3. Podman availability
 *   4. Binary-only presence for error messaging
 */
export async function detectRuntime(): Promise<DetectionResult> {
  // Check for env override
  const override = process.env.CONTAINER_RUNTIME?.toLowerCase();
  if (override === 'docker' || override === 'podman') {
    const runtime = makeRuntime(override);
    const running = await probeRuntime(override);
    console.log(
      `[ContainerRuntime] Override CONTAINER_RUNTIME=${override}, daemon ${running ? 'running' : 'not running'}`,
    );
    if (running && override === 'podman' && !(await probeSocket('podman'))) {
      console.warn(
        '[ContainerRuntime] Override: Podman CLI responds but API socket is not listening.',
      );
      return {
        runtime: null,
        binaryFoundButNotRunning: true,
        binaryFound: override,
        socketDead: true,
        guidance: PODMAN_SOCKET_GUIDANCE,
      };
    }
    return {
      runtime: running ? runtime : null,
      binaryFoundButNotRunning: !running,
      binaryFound: override,
    };
  }

  // Try Docker first (most common)
  if (await probeRuntime('docker')) {
    const runtime = makeRuntime('docker');
    console.log('[ContainerRuntime] Docker daemon detected');
    return { runtime, binaryFoundButNotRunning: false, binaryFound: 'docker' };
  }

  // Try Podman
  if (await probeRuntime('podman')) {
    // Podman CLI works, but verify the API socket is alive — external compose
    // providers (docker-compose) connect via socket, not the CLI.
    if (!(await probeSocket('podman'))) {
      console.warn(
        '[ContainerRuntime] Podman CLI responds but API socket is not listening. ' +
          'Run: systemctl --user enable --now podman.socket',
      );
      return {
        runtime: null,
        binaryFoundButNotRunning: true,
        binaryFound: 'podman',
        socketDead: true,
        guidance: PODMAN_SOCKET_GUIDANCE,
      };
    }
    const runtime = makeRuntime('podman');
    console.log('[ContainerRuntime] Podman detected');
    return { runtime, binaryFoundButNotRunning: false, binaryFound: 'podman' };
  }

  // Neither daemon is running — check for binary presence for better errors
  if (await probeBinary('docker')) {
    console.log('[ContainerRuntime] Docker binary found but daemon is not running');
    return { runtime: null, binaryFoundButNotRunning: true, binaryFound: 'docker' };
  }
  if (await probeBinary('podman')) {
    console.log('[ContainerRuntime] Podman binary found but service is not running');
    return { runtime: null, binaryFoundButNotRunning: true, binaryFound: 'podman' };
  }

  console.error('[ContainerRuntime] No container runtime found');
  return { runtime: null, binaryFoundButNotRunning: false, binaryFound: null };
}

/**
 * Get the cached detection result, running detection if needed.
 */
export async function getDetectionResult(): Promise<DetectionResult> {
  if (!cachedResult) {
    cachedResult = await detectRuntime();
  }
  return cachedResult;
}

/**
 * Get the detected container runtime, or null if none available.
 */
export async function getContainerRuntime(): Promise<ContainerRuntime | null> {
  const result = await getDetectionResult();
  return result.runtime;
}

/**
 * Get the runtime binary name. Returns 'docker' as default fallback
 * (commands will fail with a clear error if Docker isn't installed).
 */
export async function getRuntimeBin(): Promise<string> {
  const runtime = await getContainerRuntime();
  return runtime?.bin ?? 'docker';
}

/**
 * Reset cached detection. Call when the user clicks "Retry Detection".
 */
export function resetDetection(): void {
  cachedResult = null;
}

/**
 * Resolve the rootless socket path for the detected runtime on Linux.
 * Returns the env var name and socket URI if the rootless socket exists
 * and the system socket is not accessible.
 */
export function resolveRootlessSocket(
  kind: ContainerRuntimeKind,
  uid: number,
): { envVar: string; socketUri: string } | null {
  if (process.platform !== 'linux') return null;

  const paths = getSocketPaths(kind);
  const userSocket = paths.user(uid);

  if (!existsSync(userSocket)) return null;

  // Only use rootless socket if system socket is not accessible
  let systemAccessible = false;
  try {
    const fs = require('fs');
    fs.accessSync(paths.system, fs.constants.R_OK | fs.constants.W_OK);
    systemAccessible = true;
  } catch {
    systemAccessible = false;
  }

  if (systemAccessible) return null;

  return {
    envVar: paths.envVar,
    socketUri: `unix://${userSocket}`,
  };
}
