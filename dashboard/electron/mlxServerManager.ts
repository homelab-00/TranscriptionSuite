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

import { ChildProcess, spawn } from 'child_process';
import { app, BrowserWindow } from 'electron';
import * as fs from 'fs';
import * as path from 'path';

export type MLXServerStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';

export interface MLXStartOptions {
  port: number;
  hfToken?: string;
  mainTranscriberModel?: string;
  liveTranscriberModel?: string;
  diarizationModel?: string;
}

const MAX_LOG_LINES = 500;

export class MLXServerManager {
  private _process: ChildProcess | null = null;
  private _status: MLXServerStatus = 'stopped';
  private _logs: string[] = [];
  private _getWindow: () => BrowserWindow | null;

  constructor(getWindow: () => BrowserWindow | null) {
    this._getWindow = getWindow;
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

    const uvicornPath = this._resolveUvicornPath();
    if (!uvicornPath) {
      this._setStatus('error');
      this._emit('mlx:statusChanged', 'error');
      throw new Error(
        'Cannot find uvicorn binary. Run `uv sync --extra mlx` inside server/backend first.',
      );
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
    const userConfigPath = path.join(app.getPath('userData'), 'config.yaml');
    if (!fs.existsSync(userConfigPath)) {
      // Template search: one level above serverBackendDir works for both
      // dev (server/backend/ → server/config.yaml) and packaged
      // (<resourcesPath>/backend/ → <resourcesPath>/config.yaml) layouts.
      const templatePath = path.resolve(serverBackendDir, '../config.yaml');
      try {
        fs.mkdirSync(path.dirname(userConfigPath), { recursive: true });
        fs.copyFileSync(templatePath, userConfigPath);
        this._appendLog(`[MLX] Copied config from ${templatePath} → ${userConfigPath}`);
      } catch {
        // Template not found (should not happen in a properly built package).
        // Write a minimal stub so the server can at least start.
        fs.mkdirSync(path.dirname(userConfigPath), { recursive: true });
        fs.writeFileSync(userConfigPath, '# TranscriptionSuite configuration\n', 'utf-8');
        this._appendLog('[MLX] Warning: no config template found; wrote minimal config stub.');
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
        this._emit('mlx:logLine', line);
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
        this._emit('mlx:logLine', `[stderr] ${line}`);
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
  // Private helpers
  // ──────────────────────────────────────────────────────────────────────────

  private _resolveUvicornPath(): string | null {
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

    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return candidate;
    }
    return null;
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
