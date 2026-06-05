/**
 * MLX Server Manager — manages the bare-metal uvicorn server process for
 * Apple Silicon (Metal/MLX) runtime mode.
 *
 * The native server is started by spawning the uvicorn binary from the Python
 * virtualenv.  All environment variables needed by the backend (DATA_DIR,
 * HF_HOME, HF_TOKEN, model selections, log config) are injected at spawn time.
 *
 * Two uvicorn search paths are tried in order:
 *   1. `<projectRoot>/server/backend/.venv/bin/uvicorn`  (development)
 *   2. `<resourcesPath>/backend/.venv/bin/uvicorn`       (packaged)
 */

import { ChildProcess, spawn, execFile } from 'child_process';
import { promisify } from 'util';
import { app, BrowserWindow } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import type { MlxLogSink } from './mlxLogSink.js';

const execFileAsync = promisify(execFile);

export type MLXServerStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';

export interface MLXStartOptions {
  port: number;
  hfToken?: string;
  mainTranscriberModel?: string;
  liveTranscriberModel?: string;
  diarizationModel?: string;
}

export interface MLXModelCacheEntry {
  exists: boolean;
  size?: string;
}

const MAX_LOG_LINES = 500;

export class MLXServerManager {
  private _process: ChildProcess | null = null;
  private _status: MLXServerStatus = 'stopped';
  private _logs: string[] = [];
  private _getWindow: () => BrowserWindow | null;
  private _sink: MlxLogSink | null;

  constructor(getWindow: () => BrowserWindow | null, sink?: MlxLogSink) {
    this._getWindow = getWindow;
    this._sink = sink ?? null;
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Public API
  // ──────────────────────────────────────────────────────────────────────────

  getStatus(): MLXServerStatus {
    return this._status;
  }

  getLogs(tail = 200): string[] {
    return this._logs.slice(-tail);
  }

  async start(opts: MLXStartOptions): Promise<void> {
    if (this._process) {
      if (this._status === 'running' || this._status === 'starting') return;
      // Process lingering from a previous error — clean up.
      await this.stop();
    }

    const candidates = this._uvicornCandidates();
    const uvicornPath = candidates.find((c) => fs.existsSync(c)) ?? null;
    if (!uvicornPath) {
      const message = this._diagnoseMissingUvicorn(candidates);
      const lines = message.split('\n');
      // Surface the FULL diagnostic (headline + probed paths) to the Metal log
      // (disk + panel) BEFORE throwing so "check logs" is actionable instead of
      // empty (GH #124 symptom 3): start() otherwise throws before the first
      // _appendLog, leaving the log ring empty.
      for (const line of lines) {
        this._appendLog(`[MLX] ${line}`);
      }
      this._setStatus('error');
      this._emit('mlx:statusChanged', 'error');
      // Throw only the headline so the renderer toast stays single-line and
      // actionable; the multi-line path detail lives in the log above.
      throw new Error(lines[0]);
    }

    const dataDir = this._resolveDataDir();
    const hfHome = this._resolveHfHome();

    // macOS .app bundles launched from Finder inherit only a minimal PATH
    // (/usr/bin:/bin:/usr/sbin:/sbin) — Homebrew's bin directories are not
    // included.  Prepend the most common Homebrew prefix locations so that
    // system tools like ffmpeg that the Python backend shells out to are found.
    const homebrewBins = ['/opt/homebrew/bin', '/usr/local/bin'].join(':');
    const inheritedPath = process.env.PATH ?? '/usr/bin:/bin:/usr/sbin:/sbin';
    const augmentedPath = inheritedPath.includes('/opt/homebrew')
      ? inheritedPath
      : `${homebrewBins}:${inheritedPath}`;

    const env: Record<string, string> = {
      ...(process.env as Record<string, string>),
      DATA_DIR: dataDir,
      HF_HOME: hfHome,
      LOG_DIR: path.join(dataDir, 'logs'),
      LOG_LEVEL: 'INFO',
      // Force line-buffered stdout so the Electron parent sees output
      // immediately instead of waiting for the 8KB pipe buffer to fill.
      PYTHONUNBUFFERED: '1',
      PATH: augmentedPath,
    };
    if (opts.hfToken) env.HF_TOKEN = opts.hfToken;
    if (opts.mainTranscriberModel) env.MAIN_TRANSCRIBER_MODEL = opts.mainTranscriberModel;
    if (opts.liveTranscriberModel) env.LIVE_TRANSCRIBER_MODEL = opts.liveTranscriberModel;
    if (opts.diarizationModel) env.DIARIZATION_MODEL = opts.diarizationModel;

    // Ensure required directories exist.
    for (const dir of [
      dataDir,
      path.join(dataDir, 'logs'),
      path.join(dataDir, 'audio'),
      path.join(dataDir, 'tokens'),
    ]) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // server/backend/ dir: 3 levels up from the uvicorn binary file
    //   uvicorn → bin → .venv → backend
    const serverBackendDir = path.resolve(uvicornPath, '../../..');

    // The hatch editable install requires a self-referential symlink
    // server/backend/server → . so that Python can find the `server` package.
    // It is gitignored and may be absent after a fresh clone — create it if needed.
    const serverSymlink = path.join(serverBackendDir, 'server');
    if (!fs.existsSync(serverSymlink)) {
      try {
        fs.symlinkSync('.', serverSymlink);
        this._appendLog('[MLX] Created server/backend/server symlink for package resolution.');
      } catch (e) {
        this._appendLog(`[MLX] Warning: could not create server symlink: ${e}`);
      }
    }

    // Ensure a config.yaml exists at the user data path before starting the
    // server.  The Python backend's config.py searches for the file at startup
    // and raises RuntimeError if none is found.  The Electron IPC handler
    // `app:ensureServerConfig` normally creates this file, but it is only
    // invoked from the renderer — which loads *after* this auto-start fires.
    // We replicate the same logic here so the server always has a config file.
    //
    // Writes use O_EXCL semantics (COPYFILE_EXCL / flag 'wx') so the
    // existence check and the write are a single atomic syscall — avoids a
    // TOCTOU race if another process creates the file mid-call.
    const userConfigPath = path.join(app.getPath('userData'), 'config.yaml');
    // Template search: one level above serverBackendDir works for both
    // dev (server/backend/ → server/config.yaml) and packaged
    // (<resourcesPath>/backend/ → <resourcesPath>/config.yaml) layouts.
    const templatePath = path.resolve(serverBackendDir, '../config.yaml');
    fs.mkdirSync(path.dirname(userConfigPath), { recursive: true });
    try {
      fs.copyFileSync(templatePath, userConfigPath, fs.constants.COPYFILE_EXCL);
      this._appendLog(`[MLX] Copied config from ${templatePath} → ${userConfigPath}`);
    } catch (err) {
      const code = (err as NodeJS.ErrnoException)?.code;
      if (code === 'EEXIST') {
        // File already exists — another process beat us, or prior run created it.
        // Either way, the precondition ("config file present") is satisfied.
        this._appendLog(`[MLX] Config already present at ${userConfigPath}`);
      } else {
        // Template not found (should not happen in a properly built package).
        // Write a minimal stub so the server can at least start.
        try {
          fs.writeFileSync(userConfigPath, '# TranscriptionSuite configuration\n', {
            encoding: 'utf-8',
            flag: 'wx',
          });
          this._appendLog('[MLX] Warning: no config template found; wrote minimal config stub.');
        } catch (stubErr) {
          const stubCode = (stubErr as NodeJS.ErrnoException)?.code;
          if (stubCode === 'EEXIST') {
            this._appendLog(`[MLX] Config already present at ${userConfigPath}`);
          } else {
            throw stubErr;
          }
        }
      }
    }

    this._setStatus('starting');
    this._emit('mlx:statusChanged', 'starting');
    this._appendLog(`[MLX] Starting uvicorn on port ${opts.port}…`);

    // Use 'python -m uvicorn' rather than the uvicorn console-script so that
    // the invocation stays portable after the .app bundle is copied/moved
    // (console-scripts embed an absolute shebang pointing to the venv path at
    // build time, which breaks when the app is placed in a different location).
    // The python binary in the venv is a symlink to uv's managed Python; that
    // target is stable on the user's machine, and CPython resolves pyvenv.cfg
    // relative to the symlink location, so site-packages are found correctly.
    const binDir = path.dirname(uvicornPath);
    const pythonBin =
      (['python3', 'python'] as const).map((n) => path.join(binDir, n)).find(fs.existsSync) ??
      uvicornPath;

    // Project root: two levels above server/backend/
    // We intentionally do NOT use serverBackendDir as cwd because server/backend/
    // contains a top-level `logging/` package that shadows the Python stdlib
    // `logging` module when server/backend/ is added to sys.path via cwd.
    // The editable install (.pth file in the venv) puts server/backend/ on
    // sys.path unconditionally, so server.api.main is still fully importable
    // from the project root.
    const projectRoot = path.resolve(serverBackendDir, '../..');

    const child = spawn(
      pythonBin,
      ['-m', 'uvicorn', 'server.api.main:app', '--host', '0.0.0.0', '--port', String(opts.port)],
      {
        cwd: projectRoot,
        env,
        // Don't inherit parent stdio — capture separately.
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );

    this._process = child;

    child.stdout?.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean);
      for (const line of lines) {
        this._appendLog(line);
        // Transition to running only when the server reports it is ready
        // to accept connections (lifespan complete, model loaded).
        if (this._status === 'starting' && line.includes('startup complete')) {
          this._setStatus('running');
          this._emit('mlx:statusChanged', 'running');
        }
      }
    });

    child.stderr?.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean);
      for (const line of lines) {
        this._appendLog(`[stderr] ${line}`);
        // uvicorn also signals readiness on stderr.
        if (this._status === 'starting' && line.includes('Application startup complete')) {
          this._setStatus('running');
          this._emit('mlx:statusChanged', 'running');
        }
      }
    });

    child.on('error', (err: Error) => {
      this._appendLog(`[MLX] Process error: ${err.message}`);
      this._setStatus('error');
      this._emit('mlx:statusChanged', 'error');
      this._process = null;
    });

    child.on('exit', (code: number | null, signal: string | null) => {
      const msg =
        code !== null
          ? `[MLX] Process exited with code ${code}`
          : `[MLX] Process killed by signal ${signal}`;
      this._appendLog(msg);

      if (this._status !== 'stopping') {
        // Unexpected exit.
        this._setStatus('error');
        this._emit('mlx:statusChanged', 'error');
      } else {
        this._setStatus('stopped');
        this._emit('mlx:statusChanged', 'stopped');
      }
      this._process = null;
    });
  }

  async stop(): Promise<void> {
    if (!this._process) {
      this._setStatus('stopped');
      return;
    }
    this._setStatus('stopping');
    this._emit('mlx:statusChanged', 'stopping');
    this._appendLog('[MLX] Stopping server…');

    return new Promise((resolve) => {
      const child = this._process!;
      const timeout = setTimeout(() => {
        child.kill('SIGKILL');
        resolve();
      }, 10_000);

      child.once('exit', () => {
        clearTimeout(timeout);
        this._process = null;
        this._setStatus('stopped');
        this._emit('mlx:statusChanged', 'stopped');
        resolve();
      });

      child.kill('SIGTERM');
    });
  }

  /** Called during app graceful shutdown — same as stop() but synchronous-friendly. */
  destroy(): Promise<void> {
    return this.stop();
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Native model-cache operations (Docker-free, for the Metal/MLX profile)
  //
  // These mirror dockerManager's downloadModelToCache/checkModelsCached/
  // removeModelCache but run directly on the host: the HuggingFace cache lives
  // at <HF_HOME>/hub on the local filesystem, and the download is a
  // `snapshot_download` via the MLX venv's Python. None of these require the
  // Metal server process to be running.
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Download a model's weights into the local HuggingFace cache
   * (<HF_HOME>/hub) without GPU-loading it. Runs `snapshot_download` via the
   * MLX venv's Python as an independent subprocess, so it works whether or not
   * the Metal server is running.
   */
  async downloadModelToCache(modelId: string): Promise<void> {
    const trimmed = this._assertSafeModelId(modelId);

    const python = this._resolveVenvPython();
    if (!python) {
      throw new Error(
        'The Metal Python environment was not found, so models cannot be ' +
          `downloaded. Reinstall from "${this._metalDmgName()}".`,
      );
    }

    const hfHome = this._resolveHfHome();
    const hubDir = path.join(hfHome, 'hub');
    // Pass the model ID and cache dir as argv values — never interpolated into
    // the Python source — to avoid any code-injection surface.
    const pyCmd =
      'import sys; from huggingface_hub import snapshot_download; ' +
      'snapshot_download(sys.argv[1], cache_dir=sys.argv[2])';
    try {
      await execFileAsync(python, ['-c', pyCmd, trimmed, hubDir], {
        maxBuffer: 10 * 1024 * 1024,
        timeout: 600_000, // 10 minutes for large models
        env: { ...process.env, HF_HOME: hfHome },
      });
    } catch (err: unknown) {
      const stderr: string = (err as { stderr?: string })?.stderr ?? '';
      if (stderr.includes('ModuleNotFoundError') || stderr.includes('No module named')) {
        throw new Error(
          'The Metal Python environment is incomplete (huggingface_hub was not ' +
            `found). The app bundle may be damaged — reinstall from "${this._metalDmgName()}".`,
        );
      }
      if (stderr.includes('GatedRepoError') || stderr.includes('403 Client Error')) {
        throw new Error(
          `Access denied for "${trimmed}". This is a gated model — ` +
            `visit https://huggingface.co/${trimmed} to accept the license, ` +
            `then add your HuggingFace token in Settings.`,
        );
      }
      throw err;
    }
  }

  /**
   * Check which HuggingFace repos already exist in the local cache.
   * Returns a record mapping each model ID to `{ exists, size? }`.
   * Pure host-filesystem inspection — does not require the server running.
   */
  async checkModelsCached(modelIds: string[]): Promise<Record<string, MLXModelCacheEntry>> {
    const result: Record<string, MLXModelCacheEntry> = {};
    const hubDir = path.join(this._resolveHfHome(), 'hub');
    const resolvedHub = path.resolve(hubDir);

    for (const id of modelIds) {
      result[id] = { exists: false };
      const trimmed = id.trim();
      // Skip unsafe IDs (mutating ops throw via _assertSafeModelId; this batch
      // check just reports them as not-cached). Keep the char set in sync.
      if (!trimmed || trimmed.includes('..') || trimmed.includes('\\') || trimmed.includes('\0'))
        continue;

      // HuggingFace convention: "org/name" → "models--org--name" under hub/.
      const cacheName = `models--${trimmed.replace(/\//g, '--')}`;
      const dir = path.resolve(path.join(hubDir, cacheName));
      if (path.dirname(dir) !== resolvedHub) continue; // not a direct child of hub
      if (!fs.existsSync(dir)) continue;

      let size: string | undefined;
      try {
        const { stdout } = await execFileAsync('du', ['-sh', dir], { timeout: 15_000 });
        const parsed = stdout.split(/\s+/)[0]?.trim();
        if (parsed) size = parsed;
      } catch {
        // Keep exists=true even when the size lookup fails.
      }
      result[id] = size ? { exists: true, size } : { exists: true };
    }
    return result;
  }

  /**
   * Remove a model's cache directory from the local HuggingFace cache.
   * Validates the ID and refuses to touch anything outside <HF_HOME>/hub
   * (path-traversal guard for the host filesystem).
   */
  async removeModelCache(modelId: string): Promise<void> {
    const trimmed = this._assertSafeModelId(modelId);
    const hubDir = path.join(this._resolveHfHome(), 'hub');
    const cacheName = `models--${trimmed.replace(/\//g, '--')}`;
    const dir = path.resolve(path.join(hubDir, cacheName));
    if (path.dirname(dir) !== path.resolve(hubDir)) {
      throw new Error('Refusing to remove a cache directory outside the hub directory');
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Private helpers
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Locate the MLX venv's Python interpreter (python3 preferred). Derived from
   * the same venv that hosts uvicorn, so huggingface_hub is guaranteed present.
   * Returns null when no venv is found (e.g. the dashboard-only "thin" build).
   */
  private _resolveVenvPython(): string | null {
    const uvicornPath = this._uvicornCandidates().find((c) => fs.existsSync(c));
    if (!uvicornPath) return null;
    const binDir = path.dirname(uvicornPath);
    return (
      (['python3', 'python'] as const).map((n) => path.join(binDir, n)).find(fs.existsSync) ?? null
    );
  }

  /**
   * Validate a model ID before it influences a host filesystem path or a
   * subprocess. Rejects traversal sequences and control characters. Forward
   * slashes are allowed (legitimate in HuggingFace "org/name" IDs) — callers
   * map them to the "models--org--name" cache convention, and the resolved-path
   * containment check (`path.dirname(dir) === <hub>`) is the real backstop.
   */
  private _assertSafeModelId(modelId: string): string {
    const trimmed = modelId.trim();
    if (!trimmed || trimmed.includes('..') || trimmed.includes('\\') || trimmed.includes('\0')) {
      throw new Error(`Invalid model id: ${modelId}`);
    }
    return trimmed;
  }

  private _uvicornCandidates(): string[] {
    const candidates: string[] = [];

    // Development: app.getAppPath() = <project>/dashboard/ → go up one level.
    // This is the reliable Electron API for locating the package.json directory
    // and works correctly in both dev (npx electron .) and packaged builds.
    const appDir = app.getAppPath();
    candidates.push(path.join(appDir, '..', 'server/backend/.venv/bin/uvicorn'));

    // Packaged: resources/backend/.venv/bin/uvicorn
    if (process.resourcesPath) {
      candidates.push(path.join(process.resourcesPath, 'backend/.venv/bin/uvicorn'));
    }

    return candidates;
  }

  /**
   * Build an actionable error message when the uvicorn binary can't be found.
   *
   * The resolution logic is correct (verified against v1.3.3↔v1.3.5: byte-identical,
   * and the CI logs show both Metal DMGs were built with a working venv), so a miss is
   * almost always ENVIRONMENTAL: the user installed the thin dashboard-only DMG, or a
   * manual bundle swap lost the venv. Distinguish the cases so the popup/log tells the
   * user exactly what to do, instead of the developer-only "run uv sync" hint (GH #124).
   */
  private _diagnoseMissingUvicorn(candidates: string[]): string {
    // Only show paths relevant to the runtime context — a "Probed:" block, omitted
    // entirely when there are no paths (avoids a dangling "• " bullet).
    const probedBlock = (paths: string[]): string =>
      paths.length ? `\nProbed:\n  • ${paths.join('\n  • ')}` : '';

    // Packaged app: tell a thin DMG (no backend at all) apart from a corrupted bundle.
    // Gate on app.isPackaged — in dev, process.resourcesPath is also set (to Electron's
    // own resources), so resourcesPath alone would misclassify a dev machine.
    if (app.isPackaged && process.resourcesPath) {
      const resources = process.resourcesPath;
      const backendDir = path.join(resources, 'backend');
      // In a packaged context only the resourcesPath candidate(s) are meaningful;
      // the dev candidate (appDir/../server/backend/…) would just confuse the user.
      const packagedProbed = candidates.filter((c) => c.startsWith(resources));

      if (!fs.existsSync(backendDir)) {
        // No bundled backend at all → almost always the dashboard-only (thin) DMG.
        // MLX/Metal is Apple-Silicon only; Intel Macs never get a bundled Metal build,
        // so do not send an x64 user after an arm64-only DMG (GH #124 review).
        if (process.arch !== 'arm64') {
          return (
            'This is the dashboard-only build, and Metal (MLX) acceleration is not ' +
            'available on Intel Macs. Start the server with Docker (GPU or CPU), or ' +
            'connect the dashboard to a remote server instead.\n' +
            `Checked: ${backendDir} (not found).`
          );
        }
        return (
          'This is the dashboard-only build — it does not include the Metal (MLX) ' +
          'Python backend, so the Metal server cannot start. Download ' +
          `"${this._metalDmgName()}" (the build whose name ends in "-metal") and reinstall.\n` +
          `Checked: ${backendDir} (not found).`
        );
      }

      // Backend present but uvicorn missing → incomplete/corrupted bundle.
      return (
        'The Metal backend is installed but its Python environment is incomplete ' +
        `(uvicorn was not found). The app bundle may be damaged — reinstall from ` +
        `"${this._metalDmgName()}".` +
        probedBlock(packagedProbed)
      );
    }

    // Development (running from source): the venv simply has not been built yet.
    return (
      'Cannot find uvicorn binary. Run `uv sync --extra mlx` inside server/backend first.' +
      probedBlock(candidates)
    );
  }

  /**
   * Name of the bundled Metal DMG the user should reinstall. Resolves the app
   * version defensively: app.getVersion() reads Info.plist/package.json, which can
   * throw on exactly the kind of damaged bundle this diagnostic exists to report —
   * a throw here would replace the actionable message with an opaque error and
   * re-create GH #124 symptom 3. Fall back to a still-actionable name.
   */
  private _metalDmgName(): string {
    let version = '<version>';
    try {
      version = app.getVersion();
    } catch {
      // Keep the actionable "-metal" suffix even without a resolvable version.
    }
    return `TranscriptionSuite-${version}-arm64-mac-metal.dmg`;
  }

  private _resolveDataDir(): string {
    // Match Python's get_user_config_dir() for macOS:
    // ~/Library/Application Support/TranscriptionSuite/data
    const userData = app.getPath('userData'); // .../<appName>
    return path.join(userData, 'data');
  }

  private _resolveHfHome(): string {
    const userData = app.getPath('userData');
    return path.join(userData, 'models');
  }

  private _appendLog(line: string): void {
    this._logs.push(line);
    if (this._logs.length > MAX_LOG_LINES) {
      this._logs = this._logs.slice(-MAX_LOG_LINES);
    }
    // Route every line through the injected sink (which handles disk
    // persistence + buffering until the renderer is ready) when present.
    // When absent (no-sink fallback for unit tests), preserve the legacy
    // direct-IPC behavior so existing tests continue to pass.
    if (this._sink) {
      this._sink.append(line);
    } else {
      this._emit('mlx:logLine', line);
    }
  }

  private _setStatus(status: MLXServerStatus): void {
    this._status = status;
  }

  private _emit(channel: string, ...args: unknown[]): void {
    const win = this._getWindow();
    if (win && !win.isDestroyed()) {
      win.webContents.send(channel, ...args);
    }
  }
}
