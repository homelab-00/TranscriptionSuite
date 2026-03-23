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

    const env: Record<string, string> = {
      ...process.env as Record<string, string>,
      DATA_DIR: dataDir,
      HF_HOME: hfHome,
      LOG_DIR: path.join(dataDir, 'logs'),
      LOG_LEVEL: 'INFO',
    };
    if (opts.hfToken) env.HF_TOKEN = opts.hfToken;
    if (opts.mainTranscriberModel) env.MAIN_TRANSCRIBER_MODEL = opts.mainTranscriberModel;

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

    this._setStatus('starting');
    this._emit('mlx:statusChanged', 'starting');
    this._appendLog(`[MLX] Starting uvicorn on port ${opts.port}…`);

    const child = spawn(
      uvicornPath,
      ['server.api.main:app', '--host', '0.0.0.0', '--port', String(opts.port)],
      {
        cwd: serverBackendDir, // server/backend/ is the package root for uvicorn
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
      }
      // Transition to running once first output arrives (uvicorn prints startup info).
      if (this._status === 'starting') {
        this._setStatus('running');
        this._emit('mlx:statusChanged', 'running');
      }
    });

    child.stderr?.on('data', (data: Buffer) => {
      const lines = data.toString().split('\n').filter(Boolean);
      for (const line of lines) {
        this._appendLog(`[stderr] ${line}`);
        this._emit('mlx:logLine', `[stderr] ${line}`);
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
