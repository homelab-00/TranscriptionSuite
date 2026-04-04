/**
 * Container management abstraction for the Electron main process.
 *
 * Supports both Docker and Podman — the runtime is auto-detected at startup
 * via containerRuntime.ts and all CLI commands use the resolved binary name.
 *
 * Uses container CLI via child_process — no Dockerode dependency.
 * All methods are async and designed to be called from IPC handlers.
 *
 * Compose file layering:
 *   base:         docker-compose.yml            (service, env, volumes)
 *   linux host:   docker-compose.linux-host.yml  (host networking)
 *   desktop VM:   docker-compose.desktop-vm.yml  (bridge + port mapping, macOS/Windows)
 *   GPU:          docker-compose.gpu.yml         (NVIDIA reservation, Docker)
 *                 podman-compose.gpu.yml         (CDI device passthrough, Podman)
 */

import { execFile, execFileSync, spawn, ChildProcess } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import os from 'os';
import crypto from 'crypto';
import { app } from 'electron';
import {
  type ContainerRuntimeKind,
  getRuntimeBin,
  getContainerRuntime,
  getDetectionResult,
  resetDetection,
  resolveRootlessSocket,
  getSocketPaths,
} from './containerRuntime.js';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Constants ──────────────────────────────────────────────────────────────

const IMAGE_REPO = 'ghcr.io/homelab-00/transcriptionsuite-server';
export const CONTAINER_NAME = 'transcriptionsuite-container';

/** Host-side path to the startup events file (set during startContainer). */
let _startupEventsFilePath: string | null = null;

/** Get the current startup events file path (null if container not started). */
function getStartupEventsFilePath(): string | null {
  return _startupEventsFilePath;
}

/** Vulkan sidecar image — upstream whisper.cpp with Vulkan GPU acceleration. */
const VULKAN_SIDECAR_IMAGE = 'ghcr.io/ggml-org/whisper.cpp:main-vulkan';

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

// Keep in sync with src/types/runtime.ts (canonical) and src/types/electron.d.ts
/** Runtime profile: GPU (NVIDIA CUDA), Vulkan (AMD/Intel GPU), CPU-only, or Metal (Apple Silicon MLX) */
export type RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'metal';
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
  whispercppModel?: string;
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

/** Default server port — must match dashboard/src/config/store.ts::DEFAULT_SERVER_PORT */
const DEFAULT_SERVER_PORT = 9786;

/**
 * Read the configured server port from the electron-store JSON on disk.
 * Falls back to {@link DEFAULT_SERVER_PORT} if the file is missing or the key is absent.
 */
function readPortFromStore(): number {
  try {
    const storePath = path.join(app.getPath('userData'), 'dashboard-config.json');
    const raw = fs.readFileSync(storePath, 'utf8');
    const data = JSON.parse(raw) as Record<string, unknown>;
    const port = data['server.port'] ?? data['connection.port'];
    if (typeof port === 'number' && port > 0 && port < 65536) return port;
  } catch {
    // fall through
  }
  return DEFAULT_SERVER_PORT;
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
 * Collect non-internal IPv4 addresses from all network interfaces.
 * Used to populate the SAN (Subject Alternative Name) field when
 * auto-generating self-signed LAN certificates.
 */
function getLanIpAddresses(): string[] {
  const interfaces = os.networkInterfaces();
  const ips: string[] = [];
  for (const [, addrs] of Object.entries(interfaces)) {
    if (!addrs) continue;
    for (const addr of addrs) {
      if (addr.family === 'IPv4' && !addr.internal) {
        ips.push(addr.address);
      }
    }
  }
  return ips;
}

/**
 * Auto-generate a self-signed TLS certificate + key for LAN mode.
 *
 * The cert is valid for 10 years and includes SANs for all detected
 * LAN IP addresses plus localhost / 127.0.0.1.  This allows clients
 * on the same network to connect via any of the server's IPs.
 *
 * Uses `openssl` CLI which is available on Linux and macOS by default.
 * On Windows, it's commonly available via Git for Windows or WSL.
 *
 * @returns true if the files were generated, false if openssl is unavailable
 */
function generateSelfSignedLanCert(certPath: string, keyPath: string): boolean {
  // Ensure parent directories exist
  const certDir = path.dirname(certPath);
  const keyDir = path.dirname(keyPath);
  fs.mkdirSync(certDir, { recursive: true });
  if (keyDir !== certDir) fs.mkdirSync(keyDir, { recursive: true });

  // Collect SANs: all LAN IPs + loopback + localhost
  const lanIps = getLanIpAddresses();
  const sanEntries: string[] = ['DNS:localhost', 'IP:127.0.0.1', ...lanIps.map((ip) => `IP:${ip}`)];
  const sanString = sanEntries.join(',');

  // Build openssl command
  // -x509: self-signed; -newkey rsa:2048: generate new 2048-bit RSA key;
  // -nodes: no passphrase; -days 3650: valid ~10 years;
  // -subj: minimal subject; -addext: SAN extension.
  const opensslBinary = process.platform === 'win32' ? 'openssl.exe' : 'openssl';
  const args = [
    'req',
    '-x509',
    '-newkey',
    'rsa:2048',
    '-keyout',
    keyPath,
    '-out',
    certPath,
    '-days',
    '3650',
    '-nodes',
    '-subj',
    '/CN=TranscriptionSuite LAN',
    '-addext',
    `subjectAltName=${sanString}`,
  ];

  try {
    execFileSync(opensslBinary, args, {
      timeout: 30_000,
      stdio: 'pipe',
    });
    console.log(
      `[DockerManager] Auto-generated self-signed LAN certificate:\n` +
        `  Cert: ${certPath}\n` +
        `  Key:  ${keyPath}\n` +
        `  SANs: ${sanString}`,
    );
    return true;
  } catch (err: any) {
    console.warn(
      `[DockerManager] Failed to auto-generate LAN certificate (openssl): ${err.message}`,
    );
    return false;
  }
}

/**
 * Extract the Tailscale hostname from a certificate's SAN entries.
 * Returns the first *.ts.net DNS name, or null if none found.
 */
function extractTailscaleHostname(x509: crypto.X509Certificate): string | null {
  const san = x509.subjectAltName; // e.g. "DNS:machine.tailnet.ts.net"
  if (!san) return null;
  for (const entry of san.split(',')) {
    const trimmed = entry.trim();
    if (trimmed.startsWith('DNS:') && trimmed.endsWith('.ts.net')) {
      return trimmed.slice(4); // strip "DNS:" prefix
    }
  }
  return null;
}

/**
 * Attempt to renew a Tailscale TLS certificate by running `tailscale cert`.
 * Tries without sudo first (works when Tailscale operator is configured);
 * falls back to sudo on Linux/macOS.
 * @returns true if renewal succeeded and files were written
 */
function tryRenewTailscaleCert(hostname: string, certDest: string, keyDest: string): boolean {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-cert-'));
  const tmpCert = path.join(tmpDir, `${hostname}.crt`);
  const tmpKey = path.join(tmpDir, `${hostname}.key`);

  const attempts: [string, string[]][] = [
    ['tailscale', ['cert', '--cert-file', tmpCert, '--key-file', tmpKey, hostname]],
  ];
  if (process.platform !== 'win32') {
    attempts.push([
      'sudo',
      ['tailscale', 'cert', '--cert-file', tmpCert, '--key-file', tmpKey, hostname],
    ]);
  }

  for (const [cmd, args] of attempts) {
    try {
      execFileSync(cmd, args, { timeout: 30_000, stdio: 'pipe' });
      if (fs.existsSync(tmpCert) && fs.existsSync(tmpKey)) {
        fs.mkdirSync(path.dirname(certDest), { recursive: true });
        fs.mkdirSync(path.dirname(keyDest), { recursive: true });
        fs.copyFileSync(tmpCert, certDest);
        fs.copyFileSync(tmpKey, keyDest);
        try {
          fs.unlinkSync(tmpCert);
          fs.unlinkSync(tmpKey);
          fs.rmdirSync(tmpDir);
        } catch {
          /* best-effort cleanup */
        }
        return true;
      }
    } catch {
      // Try next attempt
    }
  }

  try {
    fs.rmSync(tmpDir, { recursive: true });
  } catch {
    /* best-effort cleanup */
  }
  return false;
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
  const certMissing = !fs.existsSync(certPath);
  const keyMissing = !fs.existsSync(keyPath);

  if ((certMissing || keyMissing) && profile === 'lan') {
    // Auto-generate self-signed certs for LAN mode — the client pins
    // the certificate fingerprint for LAN connections, so self-signed is fine.
    console.log(`[DockerManager] LAN cert/key not found at configured paths — auto-generating...`);
    const generated = generateSelfSignedLanCert(certPath, keyPath);
    if (!generated) {
      throw new Error(
        `LAN TLS certificate files not found and auto-generation failed.\n\n` +
          `Cert: ${certPath}\nKey:  ${keyPath}\n\n` +
          `Please install openssl or manually create the certificate files.\n` +
          `On Arch/Ubuntu: sudo pacman -S openssl / sudo apt install openssl`,
      );
    }
  } else if (certMissing) {
    const hint =
      profile === 'tailscale'
        ? 'Generate certificates with:  sudo tailscale cert <your-machine>.tail<xxxx>.ts.net\n' +
          'Then rename and move them to the path configured in config.yaml.'
        : 'Create or obtain a TLS certificate for your LAN hostname/IP\n' +
          'and place it at the path configured in config.yaml.';
    throw new Error(`TLS certificate file not found: ${certPath}\n\n${hint}`);
  } else if (keyMissing) {
    throw new Error(
      `TLS key file not found: ${keyPath}\n\n` +
        `Please ensure the key file exists at the configured path.`,
    );
  }

  // ---------- Check certificate expiry ----------
  const EXPIRY_WARN_DAYS = 7;
  try {
    const certPem = fs.readFileSync(certPath);
    const x509 = new crypto.X509Certificate(certPem);
    const expiryDate = new Date(x509.validTo);
    const now = new Date();
    const daysUntilExpiry = (expiryDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);

    if (daysUntilExpiry <= 0) {
      if (profile === 'tailscale') {
        const hostname = extractTailscaleHostname(x509);
        if (hostname) {
          const renewed = tryRenewTailscaleCert(hostname, certPath, keyPath);
          if (renewed) {
            console.log(
              `[DockerManager] Auto-renewed expired Tailscale certificate for ${hostname}`,
            );
          } else {
            throw new Error(
              `TLS certificate expired on ${expiryDate.toLocaleDateString()}.\n\n` +
                `Auto-renewal failed. Please renew manually:\n` +
                `  sudo tailscale cert ${hostname}\n` +
                `Then copy the new cert/key to:\n` +
                `  Cert: ${certPath}\n  Key:  ${keyPath}`,
            );
          }
        } else {
          throw new Error(
            `TLS certificate expired on ${expiryDate.toLocaleDateString()}.\n\n` +
              `Renew with:  sudo tailscale cert <your-machine>.tail<xxxx>.ts.net\n` +
              `Then copy the new cert/key to:\n` +
              `  Cert: ${certPath}\n  Key:  ${keyPath}`,
          );
        }
      } else {
        throw new Error(
          `TLS certificate expired on ${expiryDate.toLocaleDateString()}.\n\n` +
            `Delete the old certificate files and restart — ` +
            `a new self-signed certificate will be auto-generated.\n` +
            `  Cert: ${certPath}\n  Key:  ${keyPath}`,
        );
      }
    } else if (daysUntilExpiry <= EXPIRY_WARN_DAYS) {
      console.warn(
        `[DockerManager] TLS certificate expires in ${Math.ceil(daysUntilExpiry)} day(s) ` +
          `(${expiryDate.toLocaleDateString()}). Consider renewing soon.`,
      );
      if (profile === 'tailscale') {
        const hostname = extractTailscaleHostname(x509);
        if (hostname) {
          const renewed = tryRenewTailscaleCert(hostname, certPath, keyPath);
          if (renewed) {
            console.log(
              `[DockerManager] Preemptively renewed Tailscale certificate for ${hostname}`,
            );
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.message.includes('TLS certificate expired')) throw err;
    console.warn('[DockerManager] Could not check certificate expiry:', err);
  }

  return { certPath, keyPath, profile };
}

/**
 * Check whether the Tailscale TLS certificate files exist at the paths configured
 * in config.yaml.  Used by the renderer (via IPC) to decide whether to show the
 * remote profile chooser dialog before starting the container.
 *
 * Returns `true` when:
 * - The active profile is already `'lan'` (dialog is irrelevant), OR
 * - Both the configured `host_cert_path` and `host_key_path` files exist on disk.
 *
 * Returns `false` when either file is missing or the paths are not configured,
 * meaning the user hasn't set up Tailscale yet and should be prompted.
 */
function checkTailscaleCertsExist(): boolean {
  const profile = readRemoteTlsProfile();
  if (profile === 'lan') return true;

  // NOTE: The config.yaml reading block below is intentionally parallel to the one
  // in resolveTlsCertPaths(). If the loading logic changes there, update here too.
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

  const rawCertPath =
    extractYamlScalar(userText, 'host_cert_path') ??
    extractYamlScalar(templateText, 'host_cert_path');
  const rawKeyPath =
    extractYamlScalar(userText, 'host_key_path') ??
    extractYamlScalar(templateText, 'host_key_path');

  if (!rawCertPath || !rawKeyPath) return false;

  const certPath = expandTilde(rawCertPath.trim());
  const keyPath = expandTilde(rawKeyPath.trim());

  return fs.existsSync(certPath) && fs.existsSync(keyPath);
}

// ─── Compose File Selection ─────────────────────────────────────────────────

/**
 * Build the list of compose file args (-f ...) based on platform, runtime profile,
 * and container runtime (Docker vs Podman).
 */
function composeFileArgs(
  runtimeProfile: RuntimeProfile,
  runtimeKind: ContainerRuntimeKind = 'docker',
): string[] {
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
    if (runtimeKind === 'podman') {
      files.push('podman-compose.gpu.yml');
    } else if (detectedGpuMode === 'cdi') {
      files.push('docker-compose.gpu-cdi.yml');
    } else {
      files.push('docker-compose.gpu.yml'); // legacy nvidia runtime
    }
  }

  // Vulkan sidecar overlay (AMD/Intel GPU via whisper.cpp)
  if (runtimeProfile === 'vulkan') {
    files.push('docker-compose.vulkan.yml');
  }

  // Flatten into compose args
  return files.flatMap((f) => ['-f', f]);
}

function buildProcessEnv(
  extraEnv?: Record<string, string>,
  runtimeKind?: ContainerRuntimeKind,
): NodeJS.ProcessEnv {
  const delimiter = path.delimiter;
  const currentPath = process.env.PATH ?? '';
  const defaultPathEntries =
    process.platform === 'win32'
      ? ['C:\\Program Files\\Docker\\Docker\\resources\\bin']
      : ['/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  const mergedPath = Array.from(
    new Set([...currentPath.split(delimiter).filter(Boolean), ...defaultPathEntries]),
  ).join(delimiter);

  const socketEnv: Record<string, string> = {};
  const kind = runtimeKind ?? 'docker';
  const socketPaths = getSocketPaths(kind);
  const explicitHost =
    process.env[socketPaths.envVar] || process.env.DOCKER_HOST || extraEnv?.[socketPaths.envVar];

  if (!explicitHost && process.platform === 'linux' && typeof process.getuid === 'function') {
    const resolved = resolveRootlessSocket(kind, process.getuid());
    if (resolved) {
      socketEnv[resolved.envVar] = resolved.socketUri;
    }
  }

  return {
    ...process.env,
    PATH: mergedPath,
    ...socketEnv,
    ...extraEnv,
  };
}

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Cached runtime kind for synchronous access after initial detection */
let detectedRuntimeKind: ContainerRuntimeKind | null = null;

/** Detected GPU toolkit mode: CDI (modern) or legacy (nvidia runtime hook) */
let detectedGpuMode: 'cdi' | 'legacy' | null = null;

async function exec(
  cmd: string,
  args: string[],
  opts?: { cwd?: string; env?: Record<string, string> },
): Promise<string> {
  try {
    const { stdout } = await execFileAsync(cmd, args, {
      cwd: opts?.cwd,
      env: buildProcessEnv(opts?.env, detectedRuntimeKind ?? undefined),
      maxBuffer: 10 * 1024 * 1024, // 10MB
      timeout: 120_000, // 2 minutes
    });
    return stdout.trim();
  } catch (err: any) {
    const msg = err.stderr?.trim() || err.message || 'Unknown container runtime error';
    throw new Error(msg);
  }
}

/** Get the resolved runtime binary, caching the kind for buildProcessEnv */
async function runtimeBin(): Promise<string> {
  const bin = await getRuntimeBin();
  const runtime = await getContainerRuntime();
  detectedRuntimeKind = runtime?.kind ?? null;
  return bin;
}

/** Guidance string from the most recent detection, if any */
let _detectionGuidance: string | null = null;

/**
 * Detect container runtime (Docker or Podman) availability.
 *
 * Delegates to containerRuntime.ts for auto-detection, which probes
 * Docker first, then Podman, using daemon connectivity checks.
 *
 * All stages log diagnostics to the main-process console for debugging.
 */
async function dockerAvailable(): Promise<boolean> {
  const result = await getDetectionResult();

  _detectionGuidance = result.guidance ?? null;

  if (result.runtime) {
    detectedRuntimeKind = result.runtime.kind;
    console.log(
      `[DockerManager] ${result.runtime.displayName} detected (binary: ${result.runtime.bin})`,
    );
    return true;
  }

  if (result.binaryFoundButNotRunning) {
    if (result.socketDead) {
      console.warn(
        `[DockerManager] ${result.binaryFound} binary works but API socket is not listening`,
      );
      if (result.guidance) {
        console.warn(`[DockerManager] ${result.guidance}`);
      }
    } else {
      console.log(
        `[DockerManager] ${result.binaryFound} binary found but daemon/service is not running`,
      );
    }
  } else {
    console.error('[DockerManager] No container runtime found (Docker or Podman).');
    console.error('[DockerManager] Verify Docker or Podman is installed and available on PATH.');
  }

  return false;
}

function getDetectionGuidance(): string | null {
  return _detectionGuidance;
}

/**
 * Reset cached runtime detection. Call when the user clicks "Retry Detection".
 */
function retryDetection(): void {
  resetDetection();
  detectedRuntimeKind = null;
  _detectionGuidance = null;
}

// ─── Image Operations ───────────────────────────────────────────────────────

/** Active pull process — tracked so it can be cancelled */
let pullProcess: ChildProcess | null = null;

/** Active sidecar pull process — independent from main image pull */
let sidecarPullProcess: ChildProcess | null = null;

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
    const output = await exec(await runtimeBin(), [
      'images',
      '--format',
      'json',
      '--filter',
      `reference=${IMAGE_REPO}`,
    ]);
    if (!output) {
      console.log(
        '[DockerManager] listImages: json+filter returned empty output, trying next strategy',
      );
    } else {
      type ImageRecord = {
        // Docker NDJSON fields (PascalCase)
        Repository?: string;
        Tag?: string;
        Size?: string;
        CreatedAt?: string;
        ID?: string;
        // Podman JSON array fields (PascalCase — Go template / newer Podman)
        RepoTags?: string[];
        Names?: string[];
        Id?: string;
        Created?: number | string;
        // Podman JSON array fields (lowercase — documented podman-images JSON format)
        id?: string;
        names?: string[];
        created?: number | string;
        size?: number | string;
      };

      const parseImageRecord = (row: ImageRecord): DockerImage[] => {
        const results: DockerImage[] = [];
        const repo = row.Repository?.trim() ?? '';
        const tagField = row.Tag?.trim() ?? '';

        if (repo || tagField) {
          // Docker format: separate Repository and Tag fields.
          const tag = tagField || 'unknown';
          if (tag !== '<none>') {
            results.push({
              tag,
              fullName: `${repo}:${tag}`,
              size: row.Size?.trim() ?? '',
              created: row.CreatedAt?.trim() ?? '',
              id: row.ID?.trim() ?? '',
            });
          }
        } else {
          // Podman format: full "repo:tag" refs.
          // Podman's --format json uses lowercase field names (names, id, created, size);
          // Go-template / newer Podman versions use PascalCase (Names, RepoTags, Id).
          const refs: string[] = row.RepoTags ?? row.Names ?? row.names ?? [];
          const resolvedId = (row.ID ?? row.Id ?? row.id)?.trim() ?? '';
          const resolvedCreated = row.CreatedAt?.trim() ?? String(row.Created ?? row.created ?? '');
          const resolvedSize = row.Size?.trim() ?? (row.size != null ? String(row.size) : '');
          for (const ref of refs) {
            const trimmed = ref.trim();
            if (!trimmed.startsWith(`${IMAGE_REPO}:`)) continue;
            const lastColon = trimmed.lastIndexOf(':');
            const tag = lastColon > -1 ? trimmed.slice(lastColon + 1) : 'unknown';
            if (tag === '<none>') continue;
            results.push({
              tag,
              fullName: trimmed,
              size: resolvedSize,
              created: resolvedCreated,
              id: resolvedId,
            });
          }
        }
        return results;
      };

      const parsed: DockerImage[] = [];
      let parsedAnyJson = false;

      // Try whole-output parse first (handles Podman's pretty-printed JSON arrays).
      try {
        const wholeOutput = JSON.parse(output) as ImageRecord | ImageRecord[];
        const rows: ImageRecord[] = Array.isArray(wholeOutput) ? wholeOutput : [wholeOutput];
        parsedAnyJson = true;
        for (const row of rows) {
          parsed.push(...parseImageRecord(row));
        }
      } catch {
        // Not a single JSON value — try line-by-line NDJSON (Docker path).
        for (const line of output.split('\n').filter(Boolean)) {
          try {
            const rawParsed = JSON.parse(line) as ImageRecord | ImageRecord[];
            const rows: ImageRecord[] = Array.isArray(rawParsed) ? rawParsed : [rawParsed];
            parsedAnyJson = true;
            for (const row of rows) {
              parsed.push(...parseImageRecord(row));
            }
          } catch {
            // Ignore malformed JSON line and continue.
          }
        }
      }

      if (parsedAnyJson && parsed.length > 0) {
        console.log(`[DockerManager] listImages: found ${parsed.length} image(s) via json+filter`);
        return parsed;
      }
      if (parsedAnyJson) {
        console.log(
          '[DockerManager] listImages: json+filter parsed OK but found 0 images, trying next strategy',
        );
      }
      // Fall through to next strategy if no JSON was parsed or 0 images found.
    }
  } catch (err: any) {
    console.warn('[DockerManager] listImages json+filter failed:', err.message);
  }

  // Strategy 2: Go template format with filter (original working approach)
  try {
    const legacyOutput = await exec(await runtimeBin(), [
      'images',
      '--format',
      '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}\t{{.ID}}',
      '--filter',
      `reference=${IMAGE_REPO}`,
    ]);
    const results = parseLegacyFormat(legacyOutput);
    if (results.length > 0) {
      console.log(
        `[DockerManager] listImages: found ${results.length} image(s) via template+filter`,
      );
      return results;
    }
    console.log('[DockerManager] listImages: template+filter found 0 images, trying next strategy');
  } catch (err: any) {
    console.warn('[DockerManager] listImages template+filter failed:', err.message);
  }

  // Strategy 3: No filter, manual filtering (broadest compatibility)
  try {
    const rawOutput = await exec(await runtimeBin(), [
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
async function pullImage(tag: string): Promise<string> {
  const bin = await runtimeBin();
  return new Promise((resolve, reject) => {
    cancelPull(); // kill any existing pull first

    const proc = spawn(bin, ['pull', `${IMAGE_REPO}:${tag}`], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildProcessEnv(undefined, detectedRuntimeKind ?? undefined),
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

// ─── Sidecar Image Operations ─────────────────────────────────────────────

/**
 * Check whether the Vulkan sidecar image exists locally.
 */
async function hasSidecarImage(): Promise<boolean> {
  try {
    await exec(await runtimeBin(), ['image', 'inspect', VULKAN_SIDECAR_IMAGE]);
    return true;
  } catch {
    return false;
  }
}

/**
 * Pull the Vulkan sidecar image from the registry.
 * Uses spawn so the process can be cancelled independently of the main pull.
 */
async function pullSidecarImage(): Promise<string> {
  const bin = await runtimeBin();
  return new Promise((resolve, reject) => {
    cancelSidecarPull(); // kill any existing sidecar pull first

    const proc = spawn(bin, ['pull', VULKAN_SIDECAR_IMAGE], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: buildProcessEnv(undefined, detectedRuntimeKind ?? undefined),
    });
    sidecarPullProcess = proc;

    let stdout = '';
    let stderr = '';

    proc.stdout?.on('data', (data: Buffer) => {
      stdout += data.toString();
    });
    proc.stderr?.on('data', (data: Buffer) => {
      stderr += data.toString();
    });

    proc.on('close', (code) => {
      if (sidecarPullProcess === proc) sidecarPullProcess = null;
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        reject(new Error(stderr.trim() || `Sidecar pull exited with code ${code}`));
      }
    });

    proc.on('error', (err) => {
      if (sidecarPullProcess === proc) sidecarPullProcess = null;
      reject(err);
    });
  });
}

/**
 * Cancel an in-progress sidecar image pull.
 * Returns true if a pull was actually cancelled.
 */
function cancelSidecarPull(): boolean {
  if (sidecarPullProcess) {
    sidecarPullProcess.kill('SIGTERM');
    sidecarPullProcess = null;
    return true;
  }
  return false;
}

/**
 * Check if a sidecar pull is currently in progress.
 */
function isSidecarPulling(): boolean {
  return sidecarPullProcess !== null;
}

/**
 * Remove a local image by tag.
 */
async function removeImage(tag: string): Promise<string> {
  return exec(await runtimeBin(), ['rmi', `${IMAGE_REPO}:${tag}`]);
}

// ─── Container Operations ───────────────────────────────────────────────────

/**
 * Get the current status of the transcription suite container.
 */
async function getContainerStatus(): Promise<ContainerStatus> {
  try {
    const output = await exec(await runtimeBin(), [
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
    whispercppModel,
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

  // Pass configured server port to Docker Compose — available for both
  // compose variable interpolation (port mapping) and container env override.
  composeEnv['SERVER_PORT'] = String(readPortFromStore());

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
  } else {
    // Explicitly write false so a stale 'true' from a previous remote start
    // doesn't persist in the .env file and mislead readComposeEnvValue().
    composeEnv['TLS_ENABLED'] = 'false';
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
  // Persist TLS mode so readComposeEnvValue('TLS_ENABLED') reflects reality
  envUpdates['TLS_ENABLED'] = mode === 'remote' ? 'true' : 'false';
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

  // Vulkan sidecar: set whisper-server URL based on networking mode and
  // optionally pass a custom GGML model path.
  if (runtimeProfile === 'vulkan') {
    const serverUrl =
      process.platform === 'linux' ? 'http://localhost:8080' : 'http://whisper-server:8080';
    composeEnv['WHISPERCPP_SERVER_URL'] = serverUrl;
    envUpdates['WHISPERCPP_SERVER_URL'] = serverUrl;

    if (whispercppModel) {
      composeEnv['WHISPERCPP_MODEL'] = whispercppModel;
      envUpdates['WHISPERCPP_MODEL'] = whispercppModel;
    }
  } else {
    // Clear stale vulkan env vars from a previous profile switch so they
    // don't linger in the .env file.
    envUpdates['WHISPERCPP_SERVER_URL'] = '';
    envUpdates['WHISPERCPP_MODEL'] = '';
  }

  upsertComposeEnvValues(envUpdates);

  // Create host directory for startup events file (bind-mounted into container).
  // The server writes JSON Lines here; Electron watches with fs.watch().
  // Use mkdtempSync to avoid predictable temp paths (CWE-377 symlink race).
  // Clean up previous session's events directory if it exists.
  if (_startupEventsFilePath) {
    const prevDir = path.dirname(_startupEventsFilePath);
    try {
      fs.rmSync(prevDir, { recursive: true, force: true });
    } catch {
      /* best-effort */
    }
  }
  const eventsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'transcription-suite-events-'));
  // Truncate any stale events file from a previous session
  const eventsFile = path.join(eventsDir, 'startup-events.jsonl');
  fs.writeFileSync(eventsFile, '', { encoding: 'utf-8', mode: 0o600 });
  composeEnv['STARTUP_EVENTS_DIR'] = eventsDir;
  _startupEventsFilePath = eventsFile;

  // Rotate the persistent server log — adds a session marker and trims old sessions.
  rotateServerLog();

  const fileArgs = composeFileArgs(runtimeProfile, detectedRuntimeKind ?? undefined);

  const upArgs = ['compose', ...fileArgs, 'up', '-d'];
  // --no-build: the build section is for manual dev builds only; the packaged
  //   app copies compose files to a writable dir where the relative build
  //   context (../..) resolves to the wrong location.
  // NOTE: podman-compose does not support --no-build
  //   (see https://github.com/containers/podman-compose/issues/816).
  //   Safe to omit: the image exists locally so compose won't auto-build.
  // Pull policy: compose defaults to "missing" (pull only if not local).
  //   The main image is pre-pulled by pullImage(); sidecar images (e.g.
  //   whisper.cpp for Vulkan) are pulled automatically on first compose up.
  if (detectedRuntimeKind !== 'podman') {
    upArgs.push('--no-build');
  }
  return exec(await runtimeBin(), upArgs, {
    cwd: getComposeDir(),
    env: composeEnv,
  });
}

/**
 * Stop the container via docker compose.
 */
async function stopContainer(): Promise<string> {
  try {
    return await exec(await runtimeBin(), ['compose', 'stop'], { cwd: getComposeDir() });
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
    return await exec(await runtimeBin(), ['stop', '--time', String(seconds), CONTAINER_NAME]);
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
  return exec(await runtimeBin(), ['compose', 'down'], { cwd: getComposeDir() });
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
      const output = await exec(await runtimeBin(), [
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
    const rowsOutput = await exec(await runtimeBin(), [
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
    const raw = await exec(await runtimeBin(), [
      'system',
      'df',
      '-v',
      '--format',
      '{{json .Volumes}}',
    ]);
    const rows = JSON.parse(raw) as DockerDfVolumeRow[];
    addRows(rows);
  } catch {
    // Fall through to plain-text parsing.
  }

  if (Object.keys(map).length > 0) {
    return map;
  }

  try {
    const raw = await exec(await runtimeBin(), ['system', 'df', '-v']);
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
  return exec(await runtimeBin(), ['volume', 'rm', name]);
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
    await exec(await runtimeBin(), ['volume', 'inspect', '--format', '{{.Name}}', name]);
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
    const mountpoint = await exec(await runtimeBin(), [
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

/** Timestamp of the current container session, set during log rotation. */
let containerSessionStart: string | undefined;

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
  containerSessionStart = new Date().toISOString();
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
    // Docker accepts "all"; Podman requires an integer (0 = all logs by default).
    return detectedRuntimeKind === 'podman' ? '0' : 'all';
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
 * Start the persistent background container log stream if not already running.
 * Idempotent — safe to call multiple times or when already streaming.
 * Disk writes happen regardless of whether any UI subscriber is attached.
 */
async function startBackgroundLogStream(): Promise<void> {
  if (logProcess) return;

  const bin = await runtimeBin();
  let stdoutRemainder = '';
  let stderrRemainder = '';

  const args = ['logs', '--follow', '--timestamps'];
  if (containerSessionStart) {
    args.push('--since', containerSessionStart);
  } else {
    // Fallback: no session marker yet, only stream new lines
    args.push('--tail', '0');
  }
  args.push(CONTAINER_NAME);

  logProcess = spawn(bin, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: buildProcessEnv(undefined, detectedRuntimeKind ?? undefined),
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
async function subscribeToLogStream(callback: (line: string) => void): Promise<void> {
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
  bootstrapParserAttached = false;
}

/**
 * Get recent container logs (non-streaming).
 */
async function getLogs(tail?: number): Promise<string[]> {
  try {
    const output = await exec(await runtimeBin(), [
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

// ─── Bootstrap Download Event Parser ────────────────────────────────────────
//
// Parses container log lines for install start/complete/fail patterns and
// emits structured download events.  Covers both [bootstrap] dependency
// installs and server-side model preloading.  Subscribers register via
// subscribeToDownloadEvents() — typically the IPC bridge in main.ts.

export type DownloadEventType = 'runtime-dep' | 'ml-model' | 'model-preload';

export interface BootstrapDownloadEvent {
  action: 'start' | 'complete' | 'fail';
  id: string;
  type: DownloadEventType;
  label: string;
  error?: string;
}

interface BootstrapPattern {
  /** Substring to match inside the log line. */
  match: string;
  action: BootstrapDownloadEvent['action'];
  id: string;
  type: DownloadEventType;
  label: string;
  /** When true, extract text after the match string as the error message. */
  extractError?: boolean;
}

const BOOTSTRAP_PATTERNS: BootstrapPattern[] = [
  // ── Runtime dependencies ──────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing Python runtime dependencies',
    action: 'start',
    id: 'bootstrap-runtime-deps',
    type: 'runtime-dep',
    label: 'Runtime Dependencies',
  },
  {
    match: '[bootstrap] Runtime dependencies installed',
    action: 'complete',
    id: 'bootstrap-runtime-deps',
    type: 'runtime-dep',
    label: 'Runtime Dependencies',
  },
  // ── faster-whisper ────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing faster-whisper family dependencies',
    action: 'start',
    id: 'bootstrap-faster-whisper',
    type: 'runtime-dep',
    label: 'faster-whisper',
  },
  {
    match: '[bootstrap] faster-whisper family dependencies installed',
    action: 'complete',
    id: 'bootstrap-faster-whisper',
    type: 'runtime-dep',
    label: 'faster-whisper',
  },
  {
    match: '[bootstrap] faster-whisper dependency installation failed:',
    action: 'fail',
    id: 'bootstrap-faster-whisper',
    type: 'runtime-dep',
    label: 'faster-whisper',
    extractError: true,
  },
  // ── NeMo toolkit ──────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing NeMo toolkit',
    action: 'start',
    id: 'bootstrap-nemo',
    type: 'runtime-dep',
    label: 'NeMo Toolkit',
  },
  {
    match: '[bootstrap] NeMo toolkit installed',
    action: 'complete',
    id: 'bootstrap-nemo',
    type: 'runtime-dep',
    label: 'NeMo Toolkit',
  },
  {
    match: '[bootstrap] NeMo toolkit installation failed:',
    action: 'fail',
    id: 'bootstrap-nemo',
    type: 'runtime-dep',
    label: 'NeMo Toolkit',
    extractError: true,
  },
  // ── VibeVoice-ASR ─────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing VibeVoice-ASR',
    action: 'start',
    id: 'bootstrap-vibevoice',
    type: 'runtime-dep',
    label: 'VibeVoice-ASR',
  },
  {
    match: '[bootstrap] VibeVoice-ASR support installed',
    action: 'complete',
    id: 'bootstrap-vibevoice',
    type: 'runtime-dep',
    label: 'VibeVoice-ASR',
  },
  {
    match: '[bootstrap] VibeVoice-ASR installation failed:',
    action: 'fail',
    id: 'bootstrap-vibevoice',
    type: 'runtime-dep',
    label: 'VibeVoice-ASR',
    extractError: true,
  },
  // ── Model preload (server runtime, post-bootstrap) ────────────────────────
  {
    match: 'Loading transcription model from cache',
    action: 'start',
    id: 'model-preload',
    type: 'model-preload',
    label: 'Loading Model',
  },
  {
    match: 'STT model loaded and ready',
    action: 'complete',
    id: 'model-preload',
    type: 'model-preload',
    label: 'Loading Model',
  },
  {
    match: 'Model preload failed',
    action: 'fail',
    id: 'model-preload',
    type: 'model-preload',
    label: 'Loading Model',
  },
];

const downloadEventSubscribers = new Set<(event: BootstrapDownloadEvent) => void>();

/**
 * Log subscriber that scans each line for bootstrap install patterns.
 * Attached automatically when any download-event subscriber is registered.
 */
function bootstrapLogParser(line: string): void {
  for (const pattern of BOOTSTRAP_PATTERNS) {
    if (!line.includes(pattern.match)) continue;

    const event: BootstrapDownloadEvent = {
      action: pattern.action,
      id: pattern.id,
      type: pattern.type,
      label: pattern.label,
    };

    if (pattern.extractError) {
      const idx = line.indexOf(pattern.match) + pattern.match.length;
      event.error = line.slice(idx).trim() || 'Unknown error';
    }

    for (const cb of downloadEventSubscribers) {
      cb(event);
    }
    return; // First match wins per line
  }
}

/** Whether the parser is currently registered as a log subscriber. */
let bootstrapParserAttached = false;

function subscribeToDownloadEvents(callback: (event: BootstrapDownloadEvent) => void): void {
  downloadEventSubscribers.add(callback);
  if (!bootstrapParserAttached) {
    // Replay the ring buffer so bootstrap events that arrived before this
    // subscriber registered are not silently lost.
    for (const line of logLineBuffer) {
      bootstrapLogParser(line);
    }
    logSubscribers.add(bootstrapLogParser);
    bootstrapParserAttached = true;
  }
}

function unsubscribeFromDownloadEvents(callback: (event: BootstrapDownloadEvent) => void): void {
  downloadEventSubscribers.delete(callback);
  if (downloadEventSubscribers.size === 0 && bootstrapParserAttached) {
    logSubscribers.delete(bootstrapLogParser);
    bootstrapParserAttached = false;
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
    const isPodman = detectedRuntimeKind === 'podman';

    // Check 1: Modern CDI (Container Device Interface) — nvidia-container-toolkit 1.14+
    // Preferred over legacy mode; required by Podman, works with all driver versions.
    try {
      const cdiOutput = await exec('nvidia-ctk', ['cdi', 'list']);
      if (cdiOutput.includes('nvidia.com/gpu')) {
        toolkit = true;
        detectedGpuMode = 'cdi';
        console.log('[DockerManager] NVIDIA container toolkit: CDI mode detected');
      }
    } catch {
      // nvidia-ctk not available or CDI not configured
    }

    // Check 2: Legacy nvidia runtime registered in Docker (not applicable to Podman).
    // Fallback for older setups that haven't migrated to CDI yet.
    if (!toolkit && !isPodman) {
      try {
        const bin = await runtimeBin();
        const info = await exec(bin, ['info', '--format', '{{json .Runtimes}}']);
        if (info.includes('nvidia')) {
          toolkit = true;
          detectedGpuMode = 'legacy';
          console.log('[DockerManager] NVIDIA container toolkit: legacy runtime detected');
        }
      } catch (err: any) {
        console.warn('[DockerManager] runtime info for toolkit check failed:', err.message);
      }
    }

    if (!toolkit) {
      const hint = isPodman
        ? 'install nvidia-container-toolkit and run: nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml'
        : 'install nvidia-container-toolkit and configure CDI';
      console.warn(`[DockerManager] NVIDIA container toolkit: not found (${hint})`);
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

  const bin = await runtimeBin();

  // Split into GGML flat-file models and HuggingFace hub models
  const ggmlIds = modelIds.filter((id) => isGgmlFileName(id));
  const hubIds = modelIds.filter((id) => !isGgmlFileName(id));

  // Check GGML models: flat files at /models/{fileName}
  for (const id of ggmlIds) {
    try {
      const sanitized = path.basename(id.trim());
      await exec(bin, ['exec', CONTAINER_NAME, 'test', '-f', `/models/${sanitized}`]);
      let size: string | undefined;
      try {
        const duOutput = await exec(bin, [
          'exec',
          CONTAINER_NAME,
          'du',
          '-sh',
          `/models/${sanitized}`,
        ]);
        const parsedSize = duOutput.split(/\s+/)[0]?.trim();
        if (parsedSize) size = parsedSize;
      } catch {
        /* Keep exists=true even when size lookup fails. */
      }
      result[id] = size ? { exists: true, size } : { exists: true };
    } catch {
      result[id] = { exists: false };
    }
  }

  // Check HuggingFace hub models: directories at /models/hub/models--{org}--{name}
  if (hubIds.length > 0) {
    try {
      const output = await exec(bin, ['exec', CONTAINER_NAME, 'ls', '/models/hub/']);

      const entries = new Set(
        output
          .split(/\r?\n/)
          .map((l) => l.trim())
          .filter(Boolean),
      );

      for (const id of hubIds) {
        // HuggingFace convention: "Systran/faster-whisper-large-v3" → "models--Systran--faster-whisper-large-v3"
        const cacheName = `models--${id.trim().replace(/\//g, '--')}`;
        const exists = entries.has(cacheName);
        if (!exists) {
          result[id] = { exists: false };
          continue;
        }

        let size: string | undefined;
        try {
          const duOutput = await exec(bin, [
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
      // Container not running or volume empty — hub models remain { exists: false }
    }
  }

  return result;
}

// ─── Model Cache Operations ─────────────────────────────────────────────────

/**
 * Remove a model's cache from the Docker volume.
 *
 * GGML flat-file models: deletes `/models/{fileName}`.
 * HuggingFace hub models: deletes the `models--{org}--{name}` directory at `/models/hub/`.
 */
async function removeModelCache(modelId: string): Promise<void> {
  const trimmed = modelId.trim();
  if (isGgmlFileName(trimmed)) {
    const sanitized = path.basename(trimmed);
    await exec(await runtimeBin(), ['exec', CONTAINER_NAME, 'rm', '-f', `/models/${sanitized}`]);
  } else {
    const cacheName = `models--${trimmed.replace(/\//g, '--')}`;
    await exec(await runtimeBin(), [
      'exec',
      CONTAINER_NAME,
      'rm',
      '-rf',
      `/models/hub/${cacheName}`,
    ]);
  }
}

/** Returns true if the given name looks like a GGML flat-file model (ggml-*.bin or *.gguf). */
function isGgmlFileName(name: string): boolean {
  return /(?:(?:^|\/)ggml-.*\.bin$|\.gguf$)/i.test(name.trim());
}

/**
 * Download a GGML flat-file model from the ggerganov/whisper.cpp HuggingFace repo
 * directly into `/models/` on the models volume inside the running container.
 *
 * Uses `wget` inside the container so no Python huggingface_hub dependency is needed.
 * Downloads to a `.tmp` suffix first; renames to the final name on success.
 * On failure, the partial `.tmp` file is deleted before re-throwing.
 */
async function downloadGgmlModel(fileName: string): Promise<void> {
  // Sanitize: accept only the basename to prevent path traversal
  const sanitized = path.basename(fileName.trim());
  if (!isGgmlFileName(sanitized)) {
    throw new Error(`Invalid GGML file name: ${fileName}`);
  }

  const url = `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${sanitized}`;
  const dest = `/models/${sanitized}`;
  const tmp = `${dest}.tmp`;
  const bin = await runtimeBin();

  try {
    await execFileAsync(bin, ['exec', CONTAINER_NAME, 'wget', '-q', '-O', tmp, url], {
      maxBuffer: 1 * 1024 * 1024,
      timeout: 1_800_000, // 30 minutes for large models
    });
    // Atomically rename temp file to final destination
    await exec(bin, ['exec', CONTAINER_NAME, 'mv', tmp, dest]);
  } catch (err) {
    // Best-effort cleanup of partial download — ignore cleanup errors
    try {
      await exec(bin, ['exec', CONTAINER_NAME, 'rm', '-f', tmp]);
    } catch {
      /* ignore */
    }
    throw err;
  }
}

/**
 * Check whether a GGML flat-file model exists in `/models/` on the models volume.
 */
async function isGgmlModelDownloaded(fileName: string): Promise<boolean> {
  const sanitized = path.basename(fileName.trim());
  if (!isGgmlFileName(sanitized)) return false;
  try {
    await exec(await runtimeBin(), ['exec', CONTAINER_NAME, 'test', '-f', `/models/${sanitized}`]);
    return true;
  } catch {
    return false;
  }
}

/**
 * Download a model's weights to the models volume inside the container
 * (without GPU-loading it).
 *
 * GGML flat-file models (ggml-*.bin / *.gguf) are downloaded via direct HTTP
 * from huggingface.co/ggerganov/whisper.cpp into `/models/`.
 *
 * All other models use `huggingface_hub.snapshot_download` into `/models/hub/`.
 * The download timeout is extended to 10 minutes for HuggingFace hub models.
 */
async function downloadModelToCache(modelId: string): Promise<void> {
  const trimmedModelId = modelId.trim();
  if (!trimmedModelId) {
    throw new Error('Model ID is required');
  }

  // Route GGML flat-file models to the dedicated download path
  if (isGgmlFileName(trimmedModelId)) {
    return downloadGgmlModel(trimmedModelId);
  }

  // Pass the model ID as an argv value instead of interpolating it into code.
  // Use the runtime venv's Python, which has huggingface_hub installed.
  const pyCmd =
    "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], cache_dir='/models/hub')";
  const bin = await runtimeBin();
  try {
    await execFileAsync(
      bin,
      ['exec', CONTAINER_NAME, '/runtime/.venv/bin/python3', '-c', pyCmd, trimmedModelId],
      {
        maxBuffer: 10 * 1024 * 1024,
        timeout: 600_000, // 10 minutes for large models
      },
    );
  } catch (err: any) {
    const stderr: string = err?.stderr ?? '';
    if (stderr.includes('ModuleNotFoundError') || stderr.includes('No module named')) {
      throw new Error(
        'Server is still starting up (installing dependencies). ' +
          'Please wait for the server to finish initializing before downloading models.',
      );
    }
    if (stderr.includes('GatedRepoError') || stderr.includes('403 Client Error')) {
      throw new Error(
        `Access denied for "${trimmedModelId}". This is a gated model — ` +
          `visit https://huggingface.co/${trimmedModelId} to accept the license, ` +
          `then add your HuggingFace token in Settings.`,
      );
    }
    throw err;
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

/** Get the detected runtime kind for UI display (e.g. 'Docker' vs 'Podman'). */
async function getRuntimeKind(): Promise<string | null> {
  const runtime = await getContainerRuntime();
  return runtime?.displayName ?? null;
}

export const dockerManager = {
  dockerAvailable,
  getDetectionGuidance,
  retryDetection,
  getRuntimeKind,
  checkGpu,
  listImages,
  pullImage,
  cancelPull,
  isPulling,
  hasSidecarImage,
  pullSidecarImage,
  cancelSidecarPull,
  isSidecarPulling,
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
  isGgmlModelDownloaded,
  checkTailscaleCertsExist,
  subscribeToDownloadEvents,
  unsubscribeFromDownloadEvents,
  getStartupEventsFilePath,
  VOLUME_NAMES,
  CONTAINER_NAME,
  IMAGE_REPO,
};
