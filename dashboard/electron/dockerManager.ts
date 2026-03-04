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
  const userDataDir = path.join(app.getPath('appData'), 'TranscriptionSuite');
  app.setPath('userData', userDataDir);
  const writableDir = path.join(userDataDir, 'docker');

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

let composeDir: string | null = null;

function hasComposeFiles(dir: string): boolean {
  return fs.existsSync(path.join(dir, 'docker-compose.yml'));
}

function getComposeDir(): string {
  if (composeDir && hasComposeFiles(composeDir)) {
    return composeDir;
  }

  composeDir = resolveComposeDir();
  return composeDir;
}

/** Runtime profile: GPU (NVIDIA CUDA) or CPU-only */
export type RuntimeProfile = 'gpu' | 'cpu';
export type HfTokenDecision = 'unset' | 'provided' | 'skipped';

const VOLUME_NAMES = {
  data: 'transcriptionsuite-data',
  models: 'transcriptionsuite-models',
  runtime: 'transcriptionsuite-runtime',
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

export interface OptionalDependencyBootstrapFeatureStatus {
  available: boolean;
  reason?: string;
}

export interface OptionalDependencyBootstrapStatus {
  source: 'runtime-volume-bootstrap-status';
  whisper?: OptionalDependencyBootstrapFeatureStatus;
  nemo?: OptionalDependencyBootstrapFeatureStatus;
  vibevoiceAsr?: OptionalDependencyBootstrapFeatureStatus;
}

interface DockerDfVolumeRow {
  Name?: string;
  Size?: string;
}

export interface StartContainerOptions {
  mode: 'local' | 'remote';
  runtimeProfile: RuntimeProfile;
  imageTag?: string;
  tlsEnv?: Record<string, string>;
  hfToken?: string;
  hfTokenDecision?: HfTokenDecision;
  installWhisper?: boolean;
  installNemo?: boolean;
  installVibeVoiceAsr?: boolean;
  mainTranscriberModel?: string;
  liveTranscriberModel?: string;
  diarizationModel?: string;
}

const HF_DECISION_VALUES = new Set<HfTokenDecision>(['unset', 'provided', 'skipped']);

function normalizeHfTokenDecision(value: unknown): HfTokenDecision | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim().toLowerCase() as HfTokenDecision;
  return HF_DECISION_VALUES.has(normalized) ? normalized : undefined;
}

function sanitizeEnvValue(value: string): string {
  return value.replace(/[\r\n]+/g, '').trim();
}

function upsertComposeEnvValues(values: Record<string, string>): void {
  const composeEnvPath = path.join(getComposeDir(), '.env');
  const entries = Object.entries(values);
  if (entries.length === 0) return;

  let existingLines: string[] = [];
  try {
    const existing = fs.readFileSync(composeEnvPath, 'utf8');
    existingLines = existing.split(/\r?\n/);
  } catch {
    existingLines = [];
  }

  const keys = new Set(entries.map(([key]) => key));
  const filteredLines = existingLines.filter((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return true;
    const keyMatch = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(trimmed);
    if (!keyMatch) return true;
    return !keys.has(keyMatch[1]);
  });

  const nextLines = [
    ...filteredLines,
    ...entries.map(([key, value]) => `${key}=${sanitizeEnvValue(value)}`),
  ];

  const normalizedText = nextLines
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trimEnd();
  fs.writeFileSync(composeEnvPath, `${normalizedText}\n`, 'utf8');
}

// ─── TLS Certificate Resolution ────────────────────────────────────────────

type RemoteTlsProfile = 'tailscale' | 'lan';

/**
 * Read the active remote TLS profile from the electron-store JSON on disk.
 * Falls back to 'tailscale' if the file is missing or the key is absent.
 */
function readRemoteTlsProfile(): RemoteTlsProfile {
  try {
    const storePath = path.join(app.getPath('userData'), 'dashboard-config.json');
    const raw = fs.readFileSync(storePath, 'utf8');
    const data = JSON.parse(raw) as Record<string, unknown>;
    const value = data['connection.remoteProfile'];
    return value === 'lan' ? 'lan' : 'tailscale';
  } catch {
    return 'tailscale';
  }
}

/**
 * Locate the effective server config.yaml.
 * Preference: user-local sparse override → bundled template (dev or packaged).
 */
function findServerConfigPath(): string | null {
  const userConfigPath = path.join(app.getPath('userData'), 'config.yaml');
  if (fs.existsSync(userConfigPath)) {
    return userConfigPath;
  }

  // Dev mode: repo server/config.yaml
  const devPath = path.resolve(__dirname, '../../server/config.yaml');
  if (fs.existsSync(devPath)) {
    return devPath;
  }

  // Packaged: bundled extra resource
  const bundledPath = path.join(process.resourcesPath ?? '', 'config.yaml');
  if (fs.existsSync(bundledPath)) {
    return bundledPath;
  }

  return null;
}

/**
 * Extract the value of a named scalar key from YAML text using simple
 * line-based regex — no YAML parser needed.
 * Handles:  key: value  /  key: "value"  /  key: 'value'
 * This mirrors the grep/sed approach used by start-common.sh.
 */
function extractYamlScalar(yamlText: string, key: string): string | undefined {
  // Match lines like:  [whitespace]key: [optional-quote]value[optional-quote]
  const re = new RegExp(`^[ \\t]+${key}:[ \\t]*(["']?)([^"'\\r\\n#]+?)\\1[ \\t]*$`, 'm');
  const m = re.exec(yamlText);
  return m ? m[2].trim() || undefined : undefined;
}

/** Expand leading `~` or `~/<rest>` to the user's home directory. */
function expandTilde(p: string): string {
  if (p === '~') return app.getPath('home');
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(app.getPath('home'), p.slice(2));
  }
  return p;
}

interface TlsCertPaths {
  certPath: string;
  keyPath: string;
  profile: RemoteTlsProfile;
}

/**
 * Resolve the host-side TLS cert + key paths for the active remote profile.
 *
 * Reads `connection.remoteProfile` from the electron-store to decide which
 * set of paths to extract from `config.yaml`, then validates the files exist.
 *
 * This mirrors the logic in `start-common.sh` (lines 297-365) so the Electron
 * dashboard behaves identically to the CLI scripts.
 *
 * @throws {Error} If config.yaml is missing, cert paths are unset, or files don't exist
 */
function resolveTlsCertPaths(): TlsCertPaths {
  const profile = readRemoteTlsProfile();

  // ---------- Read config.yaml ----------
  // The user's local sparse override is checked first; the bundled template
  // provides defaults.  We read both as raw text and use simple line-based
  // regex extraction (no YAML parser) so there is no external dependency.

  const userConfigPath = path.join(app.getPath('userData'), 'config.yaml');
  const templateCandidates = [
    path.resolve(__dirname, '../../server/config.yaml'),
    path.join(process.resourcesPath ?? '', 'config.yaml'),
  ];

  let templateText = '';
  for (const candidate of templateCandidates) {
    try {
      templateText = fs.readFileSync(candidate, 'utf8');
      break;
    } catch {
      // try next
    }
  }

  let userText = '';
  try {
    userText = fs.readFileSync(userConfigPath, 'utf8');
  } catch {
    // user config is optional
  }

  // ---------- Pick paths for the active profile ----------
  // User config wins over template; template provides defaults.
  const certKey = profile === 'lan' ? 'lan_host_cert_path' : 'host_cert_path';
  const keyKey = profile === 'lan' ? 'lan_host_key_path' : 'host_key_path';
  const profileLabel = profile === 'lan' ? 'LAN' : 'Tailscale';

  const rawCertPath =
    extractYamlScalar(userText, certKey) ?? extractYamlScalar(templateText, certKey);
  const rawKeyPath = extractYamlScalar(userText, keyKey) ?? extractYamlScalar(templateText, keyKey);

  if (!rawCertPath) {
    throw new Error(
      `TLS certificate path (remote_server.tls.${certKey}) is not set in config.yaml.\n\n` +
        `Please edit your config.yaml and set the ${profileLabel} TLS certificate path.\n` +
        `See the README for certificate generation instructions.`,
    );
  }

  if (!rawKeyPath) {
    throw new Error(
      `TLS key path (remote_server.tls.${keyKey}) is not set in config.yaml.\n\n` +
        `Please edit your config.yaml and set the ${profileLabel} TLS key path.`,
    );
  }

  const certPath = expandTilde(rawCertPath.trim());
  const keyPath = expandTilde(rawKeyPath.trim());

  // ---------- Validate files exist on disk ----------
  if (!fs.existsSync(certPath)) {
    const hint =
      profile === 'tailscale'
        ? 'Generate certificates with:  sudo tailscale cert <your-machine>.tail<xxxx>.ts.net\n' +
          'Then rename and move them to the path configured in config.yaml.'
        : 'Create or obtain a TLS certificate for your LAN hostname/IP\n' +
          'and place it at the path configured in config.yaml.';
    throw new Error(`TLS certificate file not found: ${certPath}\n\n${hint}`);
  }

  if (!fs.existsSync(keyPath)) {
    throw new Error(
      `TLS key file not found: ${keyPath}\n\n` +
        `Please ensure the key file exists at the configured path.`,
    );
  }

  return { certPath, keyPath, profile };
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
  return files.flatMap((f) => ['-f', f]);
}

function buildProcessEnv(extraEnv?: Record<string, string>): NodeJS.ProcessEnv {
  const delimiter = path.delimiter;
  const currentPath = process.env.PATH ?? '';
  const defaultPathEntries =
    process.platform === 'win32'
      ? ['C:\\Program Files\\Docker\\Docker\\resources\\bin']
      : ['/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  const mergedPath = Array.from(
    new Set([...currentPath.split(delimiter).filter(Boolean), ...defaultPathEntries]),
  ).join(delimiter);

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

async function exec(
  cmd: string,
  args: string[],
  opts?: { cwd?: string; env?: Record<string, string> },
): Promise<string> {
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
    console.error('[DockerManager] Verify Docker is installed and available on PATH.');
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
        const tag = repoAndTag.length > 1 ? repoAndTag[repoAndTag.length - 1] : 'unknown';
        return { tag, fullName, size, created, id };
      })
      .filter((img) => img.fullName.startsWith(`${IMAGE_REPO}:`) && img.tag !== '<none>');
  };

  // Strategy 1: JSON format with filter (most reliable on modern Docker)
  try {
    const output = await exec('docker', [
      'images',
      '--format',
      'json',
      '--filter',
      `reference=${IMAGE_REPO}`,
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
        const tag = row.Tag?.trim() || 'unknown';
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
      '--format',
      '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
      '--filter',
      `reference=${IMAGE_REPO}`,
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
      '--format',
      '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
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
function pullImage(tag: string): Promise<string> {
  return new Promise((resolve, reject) => {
    cancelPull(); // kill any existing pull first

    const proc = spawn('docker', ['pull', `${IMAGE_REPO}:${tag}`], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildProcessEnv(),
    });
    pullProcess = proc;

    let stdout = '';
    let stderr = '';

    proc.stdout?.on('data', (data: Buffer) => {
      stdout += data.toString();
    });
    proc.stderr?.on('data', (data: Buffer) => {
      stderr += data.toString();
    });

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
async function startContainer(options: StartContainerOptions): Promise<string> {
  const {
    mode,
    runtimeProfile,
    imageTag,
    tlsEnv,
    hfToken,
    hfTokenDecision,
    installWhisper,
    installNemo,
    installVibeVoiceAsr,
    mainTranscriberModel,
    liveTranscriberModel,
    diarizationModel,
  } = options;
  const composeEnv: Record<string, string> = { ...tlsEnv };
  const normalizedHfDecision = normalizeHfTokenDecision(hfTokenDecision);

  // Prefer a local image tag for dev workflows when no explicit tag is provided.
  let resolvedTag = imageTag;
  if (!resolvedTag) {
    const localImages = await listImages();
    if (localImages.length > 0) {
      resolvedTag = localImages[0].tag;
    }
  }

  // Pass the selected image tag to docker-compose (requires a local image to be available)
  if (resolvedTag) {
    composeEnv['TAG'] = resolvedTag;
  } else {
    throw new Error('No image tag specified and no local images found. Pull an image first.');
  }

  if (mode === 'remote') {
    composeEnv['TLS_ENABLED'] = 'true';

    // Resolve host TLS certificate paths and pass them to docker-compose so
    // the bind mounts (${TLS_CERT_PATH}:/certs/cert.crt:ro etc.) resolve to
    // real files instead of the .empty sentinel directory.
    if (!tlsEnv?.TLS_CERT_PATH || !tlsEnv?.TLS_KEY_PATH) {
      const tls = resolveTlsCertPaths();
      composeEnv['TLS_CERT_PATH'] = tls.certPath;
      composeEnv['TLS_KEY_PATH'] = tls.keyPath;
    }
  }

  // For CPU mode, force CUDA invisible so the server deterministically uses CPU
  if (runtimeProfile === 'cpu') {
    composeEnv['CUDA_VISIBLE_DEVICES'] = '';
  }

  // Pass HuggingFace token to the container for diarization model access
  if (hfToken !== undefined) {
    composeEnv['HUGGINGFACE_TOKEN'] = hfToken;
  }
  if (normalizedHfDecision) {
    composeEnv['HUGGINGFACE_TOKEN_DECISION'] = normalizedHfDecision;
  }

  const envUpdates: Record<string, string> = {};
  if (hfToken !== undefined) {
    envUpdates['HUGGINGFACE_TOKEN'] = hfToken;
  }
  if (normalizedHfDecision) {
    envUpdates['HUGGINGFACE_TOKEN_DECISION'] = normalizedHfDecision;
  }

  if (installWhisper !== undefined) {
    const whisperValue = installWhisper ? 'true' : 'false';
    composeEnv['INSTALL_WHISPER'] = whisperValue;
    envUpdates['INSTALL_WHISPER'] = whisperValue;
  }

  // Pass NeMo install preference to the container for Parakeet ASR support
  if (installNemo !== undefined) {
    const nemoValue = installNemo ? 'true' : 'false';
    composeEnv['INSTALL_NEMO'] = nemoValue;
    envUpdates['INSTALL_NEMO'] = nemoValue;
  }

  // Pass VibeVoice-ASR install preference to the container (optional backend dependency)
  if (installVibeVoiceAsr !== undefined) {
    const vibevoiceValue = installVibeVoiceAsr ? 'true' : 'false';
    composeEnv['INSTALL_VIBEVOICE_ASR'] = vibevoiceValue;
    envUpdates['INSTALL_VIBEVOICE_ASR'] = vibevoiceValue;
  }

  // Pass ASR model selections to the container (empty string = use config.yaml default)
  if (mainTranscriberModel !== undefined) {
    composeEnv['MAIN_TRANSCRIBER_MODEL'] = mainTranscriberModel;
    envUpdates['MAIN_TRANSCRIBER_MODEL'] = mainTranscriberModel;
  }
  if (liveTranscriberModel !== undefined) {
    composeEnv['LIVE_TRANSCRIBER_MODEL'] = liveTranscriberModel;
    envUpdates['LIVE_TRANSCRIBER_MODEL'] = liveTranscriberModel;
  }
  if (diarizationModel !== undefined) {
    composeEnv['DIARIZATION_MODEL'] = diarizationModel;
    envUpdates['DIARIZATION_MODEL'] = diarizationModel;
  }

  upsertComposeEnvValues(envUpdates);

  // Rotate the persistent server log — adds a session marker and trims old sessions.
  rotateServerLog();

  const fileArgs = composeFileArgs(runtimeProfile);

  // --no-build: the build section is for manual dev builds only; the packaged
  //   app copies compose files to a writable dir where the relative build
  //   context (../..) resolves to the wrong location.
  // --pull never: image pulling is handled explicitly by pullImage(); letting
  //   compose pull during "up" can fail on private registries without auth.
  return exec('docker', ['compose', ...fileArgs, 'up', '-d', '--no-build', '--pull', 'never'], {
    cwd: getComposeDir(),
    env: composeEnv,
  });
}

/**
 * Stop the container via docker compose.
 */
async function stopContainer(): Promise<string> {
  try {
    return await exec('docker', ['compose', 'stop'], { cwd: getComposeDir() });
  } catch (composeErr: any) {
    console.warn(
      '[DockerManager] docker compose stop failed; falling back to docker stop:',
      composeErr?.message ?? composeErr,
    );
    try {
      return await forceStopContainer(10);
    } catch (forceErr: any) {
      const composeMsg = composeErr?.message ?? String(composeErr);
      const forceMsg = forceErr?.message ?? String(forceErr);
      throw new Error(`${composeMsg}; fallback docker stop failed: ${forceMsg}`);
    }
  }
}

/**
 * Force-stop the managed container by explicit container name.
 * This bypasses compose parsing (for example when env interpolation fails).
 */
async function forceStopContainer(timeoutSeconds = 3): Promise<string> {
  const seconds = Math.max(0, Math.floor(timeoutSeconds));
  try {
    return await exec('docker', ['stop', '--time', String(seconds), CONTAINER_NAME]);
  } catch (err: any) {
    const msg = err?.message ?? String(err);
    // Treat "already stopped / missing" as success from a shutdown perspective.
    if (/No such container|is not running/i.test(msg)) {
      return msg;
    }
    throw err;
  }
}

/**
 * Remove the container (docker compose down).
 */
async function removeContainer(): Promise<string> {
  return exec('docker', ['compose', 'down'], { cwd: getComposeDir() });
}

// ─── Volume Operations ──────────────────────────────────────────────────────

const VOLUME_LABELS: Record<string, string> = {
  [VOLUME_NAMES.data]: 'Data Volume',
  [VOLUME_NAMES.models]: 'Models Volume',
  [VOLUME_NAMES.runtime]: 'Runtime Volume',
};

/**
 * Get info about all TranscriptionSuite Docker volumes.
 */
async function getVolumes(): Promise<VolumeInfo[]> {
  const names = Object.values(VOLUME_NAMES);
  const results: VolumeInfo[] = [];
  const volumeSizeByName = await getDockerReportedVolumeSizes();

  for (const name of names) {
    try {
      const output = await exec('docker', [
        'volume',
        'inspect',
        '--format',
        '{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}',
        name,
      ]);
      const [volName, driver, mountpoint] = output.split('\t');

      results.push({
        name: volName,
        label: VOLUME_LABELS[volName] || volName,
        driver,
        mountpoint,
        size: volumeSizeByName[volName] ?? volumeSizeByName[name],
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
 * Ask Docker daemon for per-volume disk usage.
 *
 * This avoids host-level mountpoint access (and sudo) and works on Linux,
 * macOS, and Windows Docker backends.
 */
async function getDockerReportedVolumeSizes(): Promise<Record<string, string>> {
  const map: Record<string, string> = {};

  const addRows = (rows: DockerDfVolumeRow[]): void => {
    for (const row of rows) {
      const volumeName = row.Name?.trim();
      const volumeSize = row.Size?.trim();
      if (volumeName && volumeSize) {
        map[volumeName] = volumeSize;
      }
    }
  };

  try {
    const rowsOutput = await exec('docker', [
      'system',
      'df',
      '-v',
      '--format',
      '{{range .Volumes}}{{json .}}{{println}}{{end}}',
    ]);
    if (rowsOutput) {
      const rows: DockerDfVolumeRow[] = [];
      for (const line of rowsOutput.split(/\r?\n/).filter(Boolean)) {
        try {
          rows.push(JSON.parse(line) as DockerDfVolumeRow);
        } catch {
          // Skip malformed lines.
        }
      }
      addRows(rows);
    }
  } catch {
    // Fall through to alternate strategies.
  }

  if (Object.keys(map).length > 0) {
    return map;
  }

  try {
    const raw = await exec('docker', ['system', 'df', '-v', '--format', '{{json .Volumes}}']);
    const rows = JSON.parse(raw) as DockerDfVolumeRow[];
    addRows(rows);
  } catch {
    // Fall through to plain-text parsing.
  }

  if (Object.keys(map).length > 0) {
    return map;
  }

  try {
    const raw = await exec('docker', ['system', 'df', '-v']);
    const lines = raw.split(/\r?\n/);
    const sectionStart = lines.findIndex((line) => /local volumes space usage/i.test(line));
    if (sectionStart === -1) {
      return map;
    }

    let headerFound = false;
    for (let i = sectionStart + 1; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) {
        if (headerFound) break;
        continue;
      }
      if (!headerFound) {
        if (/volume name/i.test(line) && /size/i.test(line)) {
          headerFound = true;
        }
        continue;
      }
      const cols = line.split(/\s{2,}/).filter(Boolean);
      if (cols.length >= 3) {
        const volumeName = cols[0];
        const volumeSize = cols[cols.length - 1];
        if (volumeName && volumeSize) {
          map[volumeName] = volumeSize;
        }
      }
    }
  } catch {
    // Keep map empty if all non-interactive strategies fail.
  }

  return map;
}

/**
 * Remove a Docker volume by name. Container must be stopped first.
 */
async function removeVolume(name: string): Promise<string> {
  return exec('docker', ['volume', 'rm', name]);
}

/**
 * Read a single key from the compose .env file.
 * Returns the value string if the key exists and has a non-empty value, otherwise null.
 */
function readComposeEnvValue(key: string): string | null {
  const composeEnvPath = path.join(getComposeDir(), '.env');
  let lines: string[] = [];
  try {
    lines = fs.readFileSync(composeEnvPath, 'utf8').split(/\r?\n/);
  } catch {
    return null;
  }
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx === -1) continue;
    const lineKey = trimmed.slice(0, eqIdx).trim();
    if (lineKey === key) {
      const value = trimmed.slice(eqIdx + 1).trim();
      return value.length > 0 ? value : null;
    }
  }
  return null;
}

/**
 * Check whether a Docker volume with the given name exists.
 */
async function volumeExists(name: string): Promise<boolean> {
  try {
    await exec('docker', ['volume', 'inspect', '--format', '{{.Name}}', name]);
    return true;
  } catch {
    return false;
  }
}

function parseOptionalDependencyBootstrapFeature(
  value: unknown,
): OptionalDependencyBootstrapFeatureStatus | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const record = value as Record<string, unknown>;
  if (typeof record.available !== 'boolean') return undefined;

  const parsed: OptionalDependencyBootstrapFeatureStatus = {
    available: record.available,
  };
  if (typeof record.reason === 'string') {
    const reason = record.reason.trim();
    if (reason) {
      parsed.reason = reason;
    }
  }
  return parsed;
}

/**
 * Read persisted bootstrap feature status from the runtime volume when the host
 * mountpoint is directly accessible (Linux Docker Engine / rootless Docker).
 *
 * On Docker Desktop (macOS/Windows) Docker may report a VM-internal mountpoint
 * that is not host-readable; in that case this returns null and callers should
 * fall back to prompt/config heuristics.
 */
async function readOptionalDependencyBootstrapStatus(): Promise<OptionalDependencyBootstrapStatus | null> {
  try {
    const mountpoint = await exec('docker', [
      'volume',
      'inspect',
      '--format',
      '{{.Mountpoint}}',
      VOLUME_NAMES.runtime,
    ]);
    if (!mountpoint) return null;

    const statusPath = path.join(mountpoint, 'bootstrap-status.json');
    const parsed = JSON.parse(fs.readFileSync(statusPath, 'utf8')) as {
      features?: {
        whisper?: unknown;
        nemo?: unknown;
        vibevoice_asr?: unknown;
      };
    };

    const whisper = parseOptionalDependencyBootstrapFeature(parsed.features?.whisper);
    const nemo = parseOptionalDependencyBootstrapFeature(parsed.features?.nemo);
    const vibevoiceAsr = parseOptionalDependencyBootstrapFeature(parsed.features?.vibevoice_asr);
    if (!whisper && !nemo && !vibevoiceAsr) {
      return null;
    }

    return {
      source: 'runtime-volume-bootstrap-status',
      ...(whisper ? { whisper } : {}),
      ...(nemo ? { nemo } : {}),
      ...(vibevoiceAsr ? { vibevoiceAsr } : {}),
    };
  } catch {
    return null;
  }
}

// ─── Server Log Persistence ─────────────────────────────────────────────────

const SESSION_MARKER = '══════ SERVER START';
const MAX_LOG_SESSIONS = 5;
const MAX_SERVER_LOG_LINES = 10_000;

/**
 * Resolve the path to the persistent server log file inside the user config dir.
 */
function getServerLogPath(): string {
  const logDir = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  return path.join(logDir, 'server.log');
}

/**
 * Mark a new server session in the persistent log file.
 *
 * Reads the existing log, appends a session marker, trims to keep only the
 * last {@link MAX_LOG_SESSIONS} sessions, and overwrites the file.
 *
 * Called at the beginning of {@link startContainer} before the container is
 * recreated.  Subsequent log lines are appended by {@link appendLogLine}.
 */
function rotateServerLog(): void {
  try {
    const logPath = getServerLogPath();

    // Read existing persisted log (if any).
    let existing = '';
    try {
      existing = fs.readFileSync(logPath, 'utf-8');
    } catch {
      // File doesn't exist yet — fine.
    }

    // Append a session marker for the new start.
    const marker = `${SESSION_MARKER} ${new Date().toISOString()} ══════\n`;
    const combined = existing + marker;

    // Trim to keep only the last MAX_LOG_SESSIONS sessions.
    const parts = combined.split(SESSION_MARKER);
    // parts[0] is anything before the very first marker (usually empty).
    // Each subsequent element is one session (marker suffix + logs).
    const sessionTrimmed =
      parts.length > MAX_LOG_SESSIONS
        ? SESSION_MARKER + parts.slice(-MAX_LOG_SESSIONS).join(SESSION_MARKER)
        : combined;

    // Also enforce a hard line cap, keeping the most recent lines.
    const sessionLines = sessionTrimmed.split('\n');
    const trimmed =
      sessionLines.length > MAX_SERVER_LOG_LINES
        ? sessionLines.slice(-MAX_SERVER_LOG_LINES).join('\n')
        : sessionTrimmed;

    fs.writeFileSync(logPath, trimmed, 'utf-8');
  } catch (err) {
    console.warn('[DockerManager] Failed to rotate server log:', err);
  }
}

/**
 * Append a single log line to the persistent server log file.
 * Called for every line received via the docker log stream.
 */
function appendLogLine(line: string): void {
  try {
    fs.appendFileSync(getServerLogPath(), line + '\n', 'utf-8');
  } catch {
    // Best-effort — don't crash on write failures.
  }
}

// ─── Log Streaming ──────────────────────────────────────────────────────────

const LOG_RING_BUFFER_MAX = 1000;
let logProcess: ChildProcess | null = null;
const logSubscribers = new Set<(line: string) => void>();
const logLineBuffer: string[] = [];

function resolveDockerTailArg(tail?: number): string {
  if (typeof tail !== 'number' || !Number.isFinite(tail) || tail < 0) {
    return 'all';
  }
  return String(Math.floor(tail));
}

/**
 * Central dispatcher for every incoming docker log line.
 * Writes to disk, appends to the in-memory ring buffer, and notifies all
 * active subscribers.
 */
function dispatchLogLine(line: string): void {
  appendLogLine(line);
  if (logLineBuffer.length >= LOG_RING_BUFFER_MAX) {
    logLineBuffer.shift();
  }
  logLineBuffer.push(line);
  for (const cb of logSubscribers) {
    cb(line);
  }
}

/**
 * Start the persistent background docker log stream if not already running.
 * Idempotent — safe to call multiple times or when already streaming.
 * Disk writes happen regardless of whether any UI subscriber is attached.
 */
function startBackgroundLogStream(): void {
  if (logProcess) return;

  let stdoutRemainder = '';
  let stderrRemainder = '';

  logProcess = spawn(
    'docker',
    ['logs', '--follow', '--timestamps', '--tail', 'all', CONTAINER_NAME],
    {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildProcessEnv(),
    },
  );

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
        dispatchLogLine(line);
      }
    }
  };

  logProcess.stdout?.on('data', (data: Buffer) => handle(data, 'stdout'));
  logProcess.stderr?.on('data', (data: Buffer) => handle(data, 'stderr'));

  logProcess.on('close', () => {
    // Flush any partial line buffered at process close.
    if (stdoutRemainder.length > 0) {
      dispatchLogLine(stdoutRemainder);
      stdoutRemainder = '';
    }
    if (stderrRemainder.length > 0) {
      dispatchLogLine(stderrRemainder);
      stderrRemainder = '';
    }
    logProcess = null;
  });
}

/**
 * Subscribe to the continuous docker log stream.
 * Replays the in-memory ring buffer to the caller synchronously (so the UI
 * gets historical lines before live ones), then adds it as a live subscriber
 * and ensures the background process is running.
 */
function subscribeToLogStream(callback: (line: string) => void): void {
  // Replay history before registering so the caller sees past lines first.
  for (const line of logLineBuffer) {
    callback(line);
  }
  logSubscribers.add(callback);
  startBackgroundLogStream();
}

/**
 * Unsubscribe a callback from the live log stream.
 * Does NOT stop the background process — disk writing continues uninterrupted.
 */
function unsubscribeFromLogStream(callback: (line: string) => void): void {
  logSubscribers.delete(callback);
}

/**
 * Stop the background log stream process and clear all subscribers and the
 * ring buffer. Should only be called during app shutdown or after the
 * container is fully removed.
 */
function stopBackgroundLogStream(): void {
  if (logProcess) {
    logProcess.kill();
    logProcess = null;
  }
  logSubscribers.clear();
  logLineBuffer.length = 0;
}

/**
 * Get recent container logs (non-streaming).
 */
async function getLogs(tail?: number): Promise<string[]> {
  try {
    const output = await exec('docker', [
      'logs',
      '--timestamps',
      '--tail',
      resolveDockerTailArg(tail),
      CONTAINER_NAME,
    ]);
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
      console.warn(
        '[DockerManager] NVIDIA container toolkit: not found (install nvidia-container-toolkit and configure CDI)',
      );
    }
  }
  return { gpu, toolkit };
}

// ─── Model Cache Inspection ─────────────────────────────────────────────────

export interface ModelCacheEntry {
  exists: boolean;
  size?: string;
}

/**
 * Check whether HuggingFace model repos exist in the models volume.
 *
 * Runs `docker exec ls /models/hub/` inside the running container and
 * checks for `models--{org}--{name}` directories.
 *
 * Returns a record mapping each model ID to `{ exists, size? }`.
 * `size` is a human-readable `du -sh` value for cached models.
 */
async function checkModelsCached(modelIds: string[]): Promise<Record<string, ModelCacheEntry>> {
  const result: Record<string, ModelCacheEntry> = {};

  // Default all to missing
  for (const id of modelIds) {
    result[id] = { exists: false };
  }

  try {
    const output = await exec('docker', ['exec', CONTAINER_NAME, 'ls', '/models/hub/']);

    const entries = new Set(
      output
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean),
    );

    for (const id of modelIds) {
      // HuggingFace convention: "Systran/faster-whisper-large-v3" → "models--Systran--faster-whisper-large-v3"
      const cacheName = `models--${id.trim().replace(/\//g, '--')}`;
      const exists = entries.has(cacheName);
      if (!exists) {
        result[id] = { exists: false };
        continue;
      }

      let size: string | undefined;
      try {
        const duOutput = await exec('docker', [
          'exec',
          CONTAINER_NAME,
          'du',
          '-sh',
          `/models/hub/${cacheName}`,
        ]);
        const parsedSize = duOutput.split(/\s+/)[0]?.trim();
        if (parsedSize) size = parsedSize;
      } catch {
        // Keep exists=true even when size lookup fails.
      }
      result[id] = size ? { exists: true, size } : { exists: true };
    }
  } catch {
    // Container not running or volume empty — all remain { exists: false }
  }

  return result;
}

// ─── Model Cache Operations ─────────────────────────────────────────────────

/**
 * Remove a model's cache directory from the Docker volume.
 *
 * Deletes the HuggingFace hub directory `models--{org}--{name}` inside
 * the running container at `/models/hub/`.
 */
async function removeModelCache(modelId: string): Promise<void> {
  const cacheName = `models--${modelId.trim().replace(/\//g, '--')}`;
  await exec('docker', ['exec', CONTAINER_NAME, 'rm', '-rf', `/models/hub/${cacheName}`]);
}

/**
 * Download a model's weights to the HuggingFace cache inside the container
 * (without GPU-loading it).
 *
 * Uses `huggingface_hub.snapshot_download` which is available in the
 * server container image.  The download timeout is extended to 10 minutes.
 */
async function downloadModelToCache(modelId: string): Promise<void> {
  const trimmedModelId = modelId.trim();
  if (!trimmedModelId) {
    throw new Error('Model ID is required');
  }

  // Pass the model ID as an argv value instead of interpolating it into code.
  // Use the runtime venv's Python, which has huggingface_hub installed.
  const pyCmd =
    "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], cache_dir='/models/hub')";
  await execFileAsync(
    'docker',
    ['exec', CONTAINER_NAME, '/runtime/.venv/bin/python3', '-c', pyCmd, trimmedModelId],
    {
      maxBuffer: 10 * 1024 * 1024,
      timeout: 600_000, // 10 minutes for large models
    },
  );
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
  forceStopContainer,
  removeContainer,
  getVolumes,
  removeVolume,
  readComposeEnvValue,
  volumeExists,
  readOptionalDependencyBootstrapStatus,
  startBackgroundLogStream,
  subscribeToLogStream,
  unsubscribeFromLogStream,
  stopBackgroundLogStream,
  getLogs,
  checkModelsCached,
  removeModelCache,
  downloadModelToCache,
  VOLUME_NAMES,
  CONTAINER_NAME,
  IMAGE_REPO,
};
