/**
 * Docker management abstraction for the Electron main process.
 *
 * Uses Docker CLI via child_process — no Dockerode dependency.
 * All methods are async and designed to be called from IPC handlers.
 *
 * Compose file layering:
 *   base:         docker-compose.yml            (service, env, volumes)
 *   linux host:   docker-compose.linux-host.yml  (host networking)
 *   desktop VM:   docker-compose.desktop-vm.yml  (bridge + port mapping, macOS/Windows)
 *   GPU:          docker-compose.gpu.yml         (NVIDIA reservation)
 */

import { execFile, spawn, ChildProcess } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { app } from 'electron';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Constants ──────────────────────────────────────────────────────────────

const IMAGE_REPO = 'ghcr.io/homelab-00/transcriptionsuite-server';
const CONTAINER_NAME = 'transcriptionsuite-container';

/**
 * Resolve compose directory.
 *
 * In dev mode the repo's server/docker directory is used directly.
 *
 * When packaged (AppImage / installed), the compose files live inside the
 * read-only app bundle (extraResources).  Docker Compose resolves *relative*
 * bind-mount paths (like `./.empty`) against the compose file's parent
 * directory, so we must copy them to a writable location first.  We use
 * `<userData>/docker/` for this and also create the `.empty` placeholder
 * directory that the compose file defaults reference.
 */
function resolveComposeDir(): string {
  if (!app.isPackaged) {
    return path.resolve(__dirname, '../../server/docker');
  }

  const bundledDir = path.join(process.resourcesPath, 'docker');
  const writableDir = path.join(app.getPath('userData'), 'docker');

  // Ensure writable target exists
  fs.mkdirSync(writableDir, { recursive: true });

  // Copy / refresh compose files from the bundle into the writable dir
  for (const file of fs.readdirSync(bundledDir)) {
    const src = path.join(bundledDir, file);
    const dst = path.join(writableDir, file);
    // Only copy files (not directories)
    if (fs.statSync(src).isFile()) {
      fs.copyFileSync(src, dst);
    }
  }

  // Create the .empty directory that compose defaults reference for optional bind mounts
  fs.mkdirSync(path.join(writableDir, '.empty'), { recursive: true });

  return writableDir;
}

const COMPOSE_DIR = resolveComposeDir();

/** Runtime profile: GPU (NVIDIA CUDA) or CPU-only */
export type RuntimeProfile = 'gpu' | 'cpu';

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

export interface StartContainerOptions {
  mode: 'local' | 'remote';
  runtimeProfile: RuntimeProfile;
  imageTag?: string;
  tlsEnv?: Record<string, string>;
  hfToken?: string;
}

// ─── Compose File Selection ─────────────────────────────────────────────────

/**
 * Build the list of compose file args (-f ...) based on platform and runtime profile.
 */
function composeFileArgs(runtimeProfile: RuntimeProfile): string[] {
  const files: string[] = ['docker-compose.yml'];

  // Platform overlay
  if (process.platform === 'linux') {
    files.push('docker-compose.linux-host.yml');
  } else {
    // macOS (darwin) and Windows (win32) use Docker Desktop with VM networking
    files.push('docker-compose.desktop-vm.yml');
  }

  // GPU overlay (only for GPU profile)
  if (runtimeProfile === 'gpu') {
    files.push('docker-compose.gpu.yml');
  }

  // Flatten into docker compose args
  return files.flatMap(f => ['-f', f]);
}

function buildProcessEnv(extraEnv?: Record<string, string>): NodeJS.ProcessEnv {
  const delimiter = path.delimiter;
  const currentPath = process.env.PATH ?? '';
  const defaultPathEntries = process.platform === 'win32'
    ? ['C:\\Program Files\\Docker\\Docker\\resources\\bin']
    : ['/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  const mergedPath = Array.from(new Set([...currentPath.split(delimiter).filter(Boolean), ...defaultPathEntries])).join(delimiter);

  let rootlessDockerHost: string | undefined;
  const explicitDockerHost = process.env.DOCKER_HOST || extraEnv?.DOCKER_HOST;
  if (!explicitDockerHost && process.platform === 'linux' && typeof process.getuid === 'function') {
    const systemDockerSocket = '/var/run/docker.sock';
    const userDockerSocket = `/run/user/${process.getuid()}/docker.sock`;
    if (fs.existsSync(userDockerSocket)) {
      let systemSocketAccessible = false;
      try {
        fs.accessSync(systemDockerSocket, fs.constants.R_OK | fs.constants.W_OK);
        systemSocketAccessible = true;
      } catch {
        systemSocketAccessible = false;
      }

      if (!systemSocketAccessible) {
        rootlessDockerHost = `unix://${userDockerSocket}`;
      }
    }
  }

  return {
    ...process.env,
    PATH: mergedPath,
    ...(rootlessDockerHost ? { DOCKER_HOST: rootlessDockerHost } : {}),
    ...extraEnv,
  };
}

// ─── Helpers ────────────────────────────────────────────────────────────────

async function exec(cmd: string, args: string[], opts?: { cwd?: string; env?: Record<string, string> }): Promise<string> {
  try {
    const { stdout } = await execFileAsync(cmd, args, {
      cwd: opts?.cwd,
      env: buildProcessEnv(opts?.env),
      maxBuffer: 10 * 1024 * 1024, // 10MB
      timeout: 120_000, // 2 minutes
    });
    return stdout.trim();
  } catch (err: any) {
    const msg = err.stderr?.trim() || err.message || 'Unknown Docker error';
    throw new Error(msg);
  }
}

/**
 * Detect Docker availability using a three-stage fallback:
 *   1. `docker version --format` — validates daemon connectivity (strongest)
 *   2. `docker info`             — alternative daemon check
 *   3. `docker --version`        — binary-only presence check (weakest)
 *
 * All stages log diagnostics to the main-process console for debugging.
 */
async function dockerAvailable(): Promise<boolean> {
  const env = buildProcessEnv();

  // Stage 1: validate full daemon connectivity (matches original working code)
  try {
    const ver = await exec('docker', ['version', '--format', '{{.Server.Version}}']);
    console.log('[DockerManager] Docker daemon detected, server version:', ver);
    return true;
  } catch (err: any) {
    console.warn('[DockerManager] docker version failed:', err.message);
  }

  // Stage 2: try docker info as alternative daemon check
  try {
    await exec('docker', ['info', '--format', '{{.ServerVersion}}']);
    console.log('[DockerManager] Docker detected via docker info');
    return true;
  } catch (err: any) {
    console.warn('[DockerManager] docker info failed:', err.message);
  }

  // Stage 3: binary-only check (daemon might be down but binary exists)
  try {
    const clientVer = await exec('docker', ['--version']);
    console.log('[DockerManager] Docker binary found (daemon may be down):', clientVer);
    return true;
  } catch (err: any) {
    console.error('[DockerManager] Docker not found at all:', err.message);
    console.error('[DockerManager] PATH used:', env.PATH);
  }

  return false;
}

// ─── Image Operations ───────────────────────────────────────────────────────

/** Active pull process — tracked so it can be cancelled */
let pullProcess: ChildProcess | null = null;

/**
 * List local Docker images matching our repo.
 */
async function listImages(): Promise<DockerImage[]> {
  const parseLegacyFormat = (output: string): DockerImage[] => {
    return output
      .split('\n')
      .filter(Boolean)
      .map((line) => {
        const [fullNameRaw = '', size = '', created = '', id = ''] = line.split('\t');
        const fullName = fullNameRaw.trim();
        const repoAndTag = fullName.split(':');
        const tag = repoAndTag.length > 1 ? repoAndTag[repoAndTag.length - 1] : 'latest';
        return { tag, fullName, size, created, id };
      })
      .filter((img) => img.fullName.startsWith(`${IMAGE_REPO}:`) && img.tag !== '<none>');
  };

  // Strategy 1: JSON format with filter (most reliable on modern Docker)
  try {
    const output = await exec('docker', [
      'images', '--format', 'json',
      '--filter', `reference=${IMAGE_REPO}`,
    ]);
    if (!output) {
      console.log('[DockerManager] listImages: no matching images (json+filter)');
      return [];
    }

    const parsed: DockerImage[] = [];
    let parsedAnyJsonLine = false;

    for (const line of output.split('\n').filter(Boolean)) {
      try {
        const row = JSON.parse(line) as {
          Repository?: string;
          Tag?: string;
          Size?: string;
          CreatedAt?: string;
          ID?: string;
        };
        parsedAnyJsonLine = true;

        const repo = row.Repository?.trim() ?? '';
        const tag = row.Tag?.trim() || 'latest';
        if (tag === '<none>') continue;

        parsed.push({
          tag,
          fullName: `${repo}:${tag}`,
          size: row.Size?.trim() ?? '',
          created: row.CreatedAt?.trim() ?? '',
          id: row.ID?.trim() ?? '',
        });
      } catch {
        // Ignore malformed JSON line and continue.
      }
    }

    if (parsedAnyJsonLine) {
      console.log(`[DockerManager] listImages: found ${parsed.length} image(s) via json+filter`);
      return parsed;
    }
    // Fall through to legacy format if no JSON was parsed.
  } catch (err: any) {
    console.warn('[DockerManager] listImages json+filter failed:', err.message);
  }

  // Strategy 2: Go template format with filter (original working approach)
  try {
    const legacyOutput = await exec('docker', [
      'images',
      '--format', '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
      '--filter', `reference=${IMAGE_REPO}`,
    ]);
    const results = parseLegacyFormat(legacyOutput);
    console.log(`[DockerManager] listImages: found ${results.length} image(s) via template+filter`);
    return results;
  } catch (err: any) {
    console.warn('[DockerManager] listImages template+filter failed:', err.message);
  }

  // Strategy 3: No filter, manual filtering (broadest compatibility)
  try {
    const rawOutput = await exec('docker', [
      'images',
      '--format', '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
    ]);
    const results = parseLegacyFormat(rawOutput);
    console.log(`[DockerManager] listImages: found ${results.length} image(s) via unfiltered scan`);
    return results;
  } catch (err: any) {
    console.error('[DockerManager] listImages: all strategies failed:', err.message);
    return [];
  }
}

/**
 * Pull an image tag from the registry.
 * Uses spawn instead of exec so the process can be cancelled.
 */
function pullImage(tag: string = 'latest'): Promise<string> {
  return new Promise((resolve, reject) => {
    cancelPull(); // kill any existing pull first

    const proc = spawn('docker', ['pull', `${IMAGE_REPO}:${tag}`], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildProcessEnv(),
    });
    pullProcess = proc;

    let stdout = '';
    let stderr = '';

    proc.stdout?.on('data', (data: Buffer) => { stdout += data.toString(); });
    proc.stderr?.on('data', (data: Buffer) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      if (pullProcess === proc) pullProcess = null;
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        reject(new Error(stderr.trim() || `Pull exited with code ${code}`));
      }
    });

    proc.on('error', (err) => {
      if (pullProcess === proc) pullProcess = null;
      reject(err);
    });
  });
}

/**
 * Cancel an in-progress image pull.
 * Returns true if a pull was actually cancelled.
 */
function cancelPull(): boolean {
  if (pullProcess) {
    pullProcess.kill('SIGTERM');
    pullProcess = null;
    return true;
  }
  return false;
}

/**
 * Check if a pull is currently in progress.
 */
function isPulling(): boolean {
  return pullProcess !== null;
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
 * Start the container via docker compose with layered compose files.
 * @param options - Container start options including mode, runtime profile, and optional TLS env.
 */
async function startContainer(
  options: StartContainerOptions,
): Promise<string> {
  const { mode, runtimeProfile, imageTag, tlsEnv, hfToken } = options;
  const composeEnv: Record<string, string> = { ...tlsEnv };

  // Prefer a local image tag for dev workflows when no explicit tag is provided.
  let resolvedTag = imageTag;
  if (!resolvedTag) {
    const localImages = await listImages();
    if (localImages.length > 0) {
      resolvedTag = localImages[0].tag;
    }
  }

  // Pass the selected image tag to docker-compose (defaults to 'latest' only when none available locally)
  if (resolvedTag) {
    composeEnv['TAG'] = resolvedTag;
  }

  if (mode === 'remote') {
    composeEnv['TLS_ENABLED'] = 'true';
  }

  // For CPU mode, force CUDA invisible so the server deterministically uses CPU
  if (runtimeProfile === 'cpu') {
    composeEnv['CUDA_VISIBLE_DEVICES'] = '';
  }

  // Pass HuggingFace token to the container for diarization model access
  if (hfToken) {
    composeEnv['HUGGINGFACE_TOKEN'] = hfToken;
  }

  const fileArgs = composeFileArgs(runtimeProfile);

  return exec('docker', ['compose', ...fileArgs, 'up', '-d'], {
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

function resolveDockerTailArg(tail?: number): string {
  if (typeof tail !== 'number' || !Number.isFinite(tail) || tail < 0) {
    return 'all';
  }
  return String(Math.floor(tail));
}

/**
 * Start streaming container logs. Returns recent logs immediately.
 * The callback receives new log lines as they appear.
 */
function startLogStream(onData: (line: string) => void, tail?: number): void {
  stopLogStream();

  const tailArg = resolveDockerTailArg(tail);
  let stdoutRemainder = '';
  let stderrRemainder = '';

  logProcess = spawn('docker', ['logs', '--follow', '--timestamps', '--tail', tailArg, CONTAINER_NAME], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: buildProcessEnv(),
  });

  const handle = (data: Buffer, stream: 'stdout' | 'stderr') => {
    const previousRemainder = stream === 'stdout' ? stdoutRemainder : stderrRemainder;
    const lines = `${previousRemainder}${data.toString()}`.split(/\r?\n/);
    const remainder = lines.pop() ?? '';
    if (stream === 'stdout') {
      stdoutRemainder = remainder;
    } else {
      stderrRemainder = remainder;
    }
    for (const line of lines) {
      if (line.length > 0) {
        onData(line);
      }
    }
  };

  logProcess.stdout?.on('data', (data: Buffer) => handle(data, 'stdout'));
  logProcess.stderr?.on('data', (data: Buffer) => handle(data, 'stderr'));

  logProcess.on('close', () => {
    if (stdoutRemainder.length > 0) {
      onData(stdoutRemainder);
      stdoutRemainder = '';
    }
    if (stderrRemainder.length > 0) {
      onData(stderrRemainder);
      stderrRemainder = '';
    }
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
async function getLogs(tail?: number): Promise<string[]> {
  try {
    const output = await exec('docker', ['logs', '--timestamps', '--tail', resolveDockerTailArg(tail), CONTAINER_NAME]);
    return output.split(/\r?\n/).filter(Boolean);
  } catch {
    return [];
  }
}

// ─── GPU Detection ──────────────────────────────────────────────────────────

/**
 * Check for NVIDIA GPU + container toolkit availability.
 * Returns { gpu: boolean, toolkit: boolean }.
 */
async function checkGpu(): Promise<{ gpu: boolean; toolkit: boolean }> {
  let gpu = false;
  let toolkit = false;
  try {
    const gpuName = await exec('nvidia-smi', ['--query-gpu=name', '--format=csv,noheader']);
    gpu = true;
    console.log('[DockerManager] NVIDIA GPU detected:', gpuName);
  } catch (err: any) {
    console.warn('[DockerManager] nvidia-smi not found or failed:', err.message);
  }
  if (gpu) {
    // Check 1: Legacy nvidia runtime registered in Docker
    try {
      const info = await exec('docker', ['info', '--format', '{{json .Runtimes}}']);
      if (info.includes('nvidia')) {
        toolkit = true;
        console.log('[DockerManager] NVIDIA container toolkit: legacy runtime detected');
      }
    } catch (err: any) {
      console.warn('[DockerManager] docker info for toolkit check failed:', err.message);
    }

    // Check 2: Modern CDI (Container Device Interface) — nvidia-container-toolkit 1.14+
    if (!toolkit) {
      try {
        const cdiOutput = await exec('nvidia-ctk', ['cdi', 'list']);
        if (cdiOutput.includes('nvidia.com/gpu')) {
          toolkit = true;
          console.log('[DockerManager] NVIDIA container toolkit: CDI mode detected');
        }
      } catch {
        // nvidia-ctk not available or CDI not configured
      }
    }

    if (!toolkit) {
      console.warn('[DockerManager] NVIDIA container toolkit: not found (install nvidia-container-toolkit and configure CDI)');
    }
  }
  return { gpu, toolkit };
}

// ─── Public API ─────────────────────────────────────────────────────────────

export const dockerManager = {
  dockerAvailable,
  checkGpu,
  listImages,
  pullImage,
  cancelPull,
  isPulling,
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
