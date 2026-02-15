/**
 * Docker management abstraction for the Electron main process.
 *
 * Uses Docker CLI via child_process — no Dockerode dependency.
 * All methods are async and designed to be called from IPC handlers.
 */

import { execFile, spawn, ChildProcess } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { fileURLToPath } from 'url';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Constants ──────────────────────────────────────────────────────────────

const IMAGE_REPO = 'ghcr.io/homelab-00/transcriptionsuite-server';
const CONTAINER_NAME = 'transcriptionsuite-container';
const COMPOSE_DIR = path.resolve(__dirname, '../../server/docker');

const VOLUME_NAMES = {
  data: 'transcriptionsuite-data',
  models: 'transcriptionsuite-models',
  runtime: 'transcriptionsuite-runtime',
  uvCache: 'transcriptionsuite-uv-cache',
} as const;

// ─── Types ──────────────────────────────────────────────────────────────────

export interface DockerImage {
  tag: string;
  fullName: string;
  size: string;
  created: string;
  id: string;
}

export interface ContainerStatus {
  exists: boolean;
  running: boolean;
  status: string; // "running", "exited", "created", "paused", etc.
  health?: string;
  startedAt?: string;
  ports?: string;
}

export interface VolumeInfo {
  name: string;
  label: string;
  driver: string;
  mountpoint: string;
  size?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

async function exec(cmd: string, args: string[], opts?: { cwd?: string; env?: Record<string, string> }): Promise<string> {
  try {
    const { stdout } = await execFileAsync(cmd, args, {
      cwd: opts?.cwd,
      env: { ...process.env, ...opts?.env },
      maxBuffer: 10 * 1024 * 1024, // 10MB
      timeout: 120_000, // 2 minutes
    });
    return stdout.trim();
  } catch (err: any) {
    const msg = err.stderr?.trim() || err.message || 'Unknown Docker error';
    throw new Error(msg);
  }
}

async function dockerAvailable(): Promise<boolean> {
  try {
    await exec('docker', ['version', '--format', '{{.Server.Version}}']);
    return true;
  } catch {
    return false;
  }
}

// ─── Image Operations ───────────────────────────────────────────────────────

/**
 * List local Docker images matching our repo.
 */
async function listImages(): Promise<DockerImage[]> {
  try {
    const output = await exec('docker', [
      'images',
      '--format', '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
      '--filter', `reference=${IMAGE_REPO}`,
    ]);
    if (!output) return [];

    return output.split('\n').filter(Boolean).map(line => {
      const [fullName, size, created, id] = line.split('\t');
      const tag = fullName.split(':')[1] || 'latest';
      return { tag, fullName, size, created, id };
    });
  } catch {
    return [];
  }
}

/**
 * Pull an image tag from the registry.
 */
async function pullImage(tag: string = 'latest'): Promise<string> {
  return exec('docker', ['pull', `${IMAGE_REPO}:${tag}`]);
}

/**
 * Remove a local image by tag.
 */
async function removeImage(tag: string): Promise<string> {
  return exec('docker', ['rmi', `${IMAGE_REPO}:${tag}`]);
}

// ─── Container Operations ───────────────────────────────────────────────────

/**
 * Get the current status of the transcription suite container.
 */
async function getContainerStatus(): Promise<ContainerStatus> {
  try {
    const output = await exec('docker', [
      'inspect',
      '--format',
      '{{.State.Status}}\t{{.State.Health.Status}}\t{{.State.StartedAt}}\t{{.Config.ExposedPorts}}',
      CONTAINER_NAME,
    ]);
    const [status, health, startedAt] = output.split('\t');
    return {
      exists: true,
      running: status === 'running',
      status: status || 'unknown',
      health: health && health !== '<nil>' ? health : undefined,
      startedAt,
    };
  } catch {
    return { exists: false, running: false, status: 'not found' };
  }
}

/**
 * Start the container via docker compose.
 * @param mode - 'local' or 'remote'
 * @param env - Additional environment variables (TLS paths etc.)
 */
async function startContainer(
  mode: 'local' | 'remote',
  env?: Record<string, string>,
): Promise<string> {
  const composeEnv: Record<string, string> = { ...env };

  if (mode === 'remote') {
    composeEnv['TLS_ENABLED'] = 'true';
  }

  return exec('docker', ['compose', 'up', '-d'], {
    cwd: COMPOSE_DIR,
    env: composeEnv,
  });
}

/**
 * Stop the container via docker compose.
 */
async function stopContainer(): Promise<string> {
  return exec('docker', ['compose', 'stop'], { cwd: COMPOSE_DIR });
}

/**
 * Remove the container (docker compose down).
 */
async function removeContainer(): Promise<string> {
  return exec('docker', ['compose', 'down'], { cwd: COMPOSE_DIR });
}

// ─── Volume Operations ──────────────────────────────────────────────────────

const VOLUME_LABELS: Record<string, string> = {
  [VOLUME_NAMES.data]: 'Data Volume',
  [VOLUME_NAMES.models]: 'Models Volume',
  [VOLUME_NAMES.runtime]: 'Runtime Volume',
  [VOLUME_NAMES.uvCache]: 'UV Cache Volume',
};

/**
 * Get info about all TranscriptionSuite Docker volumes.
 */
async function getVolumes(): Promise<VolumeInfo[]> {
  const names = Object.values(VOLUME_NAMES);
  const results: VolumeInfo[] = [];

  for (const name of names) {
    try {
      const output = await exec('docker', [
        'volume', 'inspect',
        '--format', '{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}',
        name,
      ]);
      const [volName, driver, mountpoint] = output.split('\t');

      // Try to get the actual size via du (may need sudo in some configs)
      let size: string | undefined;
      try {
        const duOut = await exec('sudo', ['du', '-sh', mountpoint]);
        size = duOut.split('\t')[0];
      } catch {
        // Fallback: try without sudo (works if Docker uses overlay in user namespace)
        try {
          const duOut = await exec('du', ['-sh', mountpoint]);
          size = duOut.split('\t')[0];
        } catch {
          size = undefined;
        }
      }

      results.push({
        name: volName,
        label: VOLUME_LABELS[volName] || volName,
        driver,
        mountpoint,
        size,
      });
    } catch {
      // Volume doesn't exist — still include it as not found
      results.push({
        name,
        label: VOLUME_LABELS[name] || name,
        driver: 'local',
        mountpoint: '',
        size: undefined,
      });
    }
  }

  return results;
}

/**
 * Remove a Docker volume by name. Container must be stopped first.
 */
async function removeVolume(name: string): Promise<string> {
  return exec('docker', ['volume', 'rm', name]);
}

// ─── Log Streaming ──────────────────────────────────────────────────────────

let logProcess: ChildProcess | null = null;

/**
 * Start streaming container logs. Returns recent logs immediately.
 * The callback receives new log lines as they appear.
 */
function startLogStream(onData: (line: string) => void, tail: number = 100): void {
  stopLogStream();

  logProcess = spawn('docker', ['logs', '--follow', '--tail', String(tail), CONTAINER_NAME], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  const handle = (data: Buffer) => {
    const lines = data.toString().split('\n').filter(Boolean);
    for (const line of lines) {
      onData(line);
    }
  };

  logProcess.stdout?.on('data', handle);
  logProcess.stderr?.on('data', handle);

  logProcess.on('close', () => {
    logProcess = null;
  });
}

/**
 * Stop any active log stream.
 */
function stopLogStream(): void {
  if (logProcess) {
    logProcess.kill();
    logProcess = null;
  }
}

/**
 * Get recent container logs (non-streaming).
 */
async function getLogs(tail: number = 200): Promise<string[]> {
  try {
    const output = await exec('docker', ['logs', '--tail', String(tail), CONTAINER_NAME]);
    return output.split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

export const dockerManager = {
  dockerAvailable,
  listImages,
  pullImage,
  removeImage,
  getContainerStatus,
  startContainer,
  stopContainer,
  removeContainer,
  getVolumes,
  removeVolume,
  startLogStream,
  stopLogStream,
  getLogs,
  VOLUME_NAMES,
  CONTAINER_NAME,
  IMAGE_REPO,
};
