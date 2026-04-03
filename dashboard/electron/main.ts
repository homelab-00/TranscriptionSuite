import crypto from 'crypto';
import fs from 'fs';
import net from 'net';
import os from 'os';
import path from 'path';
import https from 'https';
import http from 'http';
import { fileURLToPath } from 'url';
import { execFile, execFileSync, spawn } from 'child_process';
import { promisify } from 'util';
import {
  app,
  BrowserWindow,
  clipboard,
  desktopCapturer,
  ipcMain,
  Notification,
  session,
  shell,
  dialog,
} from 'electron';

const execFileAsync = promisify(execFile);
import Store from 'electron-store';
import { CONTAINER_NAME, dockerManager, type StartContainerOptions } from './dockerManager.js';
import { StartupEventWatcher } from './startupEventWatcher.js';
import { MLXServerManager, type MLXStartOptions } from './mlxServerManager.js';
import { TrayManager, type TrayState } from './trayManager.js';
import { UpdateManager } from './updateManager.js';
import {
  registerShortcuts,
  unregisterShortcuts,
  handleCliAction,
  getPortalShortcuts,
  rebindPortalShortcuts,
  isWaylandPortalActive,
} from './shortcutManager.js';
import { pasteAtCursor } from './pasteAtCursor.js';
import { WatcherManager } from './watcherManager.js';

// When launched via a wrapper (e.g. AppImage through GearLevel), the stdout/stderr
// pipes may already be closed.  Any console.log/warn/error call will then raise
// EPIPE which Node promotes to an uncaught exception, showing the Electron error
// dialog.  Silently dropping EPIPE on these streams is the standard Node.js fix.
for (const stream of [process.stdout, process.stderr] as NodeJS.WriteStream[]) {
  stream.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code !== 'EPIPE') throw err;
  });
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// AppImage on Linux: the afterPack build hook wraps the Electron binary with a
// shell script that passes --no-sandbox as a real CLI argument (the zygote sandbox
// check runs before this JS executes, so the flag must be in argv from the start).
// This appendSwitch call is a belt-and-suspenders fallback for non-AppImage cases
// or if the wrapper is bypassed.
if (process.platform === 'linux' && process.env.APPIMAGE) {
  app.commandLine.appendSwitch('no-sandbox');
}

// GlobalShortcutsPortal Chromium feature flag removed — our D-Bus module
// (waylandShortcuts.ts) handles portal communication directly, which avoids
// duplicate portal sessions and lets us set human-readable descriptions.

// ─── System audio loopback flags ────────────────────────────────────────────
// These must be set before app.whenReady() so Chromium picks them up.
if (process.platform === 'linux') {
  // Disable VA-API probing — NVIDIA GPUs don't support it (they use NVDEC),
  // so Chromium's vaInitialize() fails with a scary but harmless error.
  app.commandLine.appendSwitch(
    'disable-features',
    'VaapiVideoDecoder,VaapiVideoEncoder,VaapiVideoDecodeLinuxGL',
  );
  app.commandLine.appendSwitch('enable-features', 'PulseaudioLoopbackForScreenShare');
} else if (process.platform === 'darwin') {
  app.commandLine.appendSwitch(
    'enable-features',
    'MacLoopbackAudioForScreenShare,MacSckSystemAudioLoopbackOverride',
  );
}
// Windows: native WASAPI loopback — no flags needed.

// Ensure all Electron paths use PascalCase: ~/.config/TranscriptionSuite (not lowercase).
// Both 'userData' AND 'crashDumps' must be set explicitly — Electron derives them
// independently, and 'crashDumps' defaults to ~/.config/{package.name}/Crashpad (which
// would be lowercase because npm requires lowercase package names).
app.setPath('userData', path.join(app.getPath('appData'), 'TranscriptionSuite'));
app.setPath('crashDumps', path.join(app.getPath('appData'), 'TranscriptionSuite', 'Crashpad'));

const isDev = !app.isPackaged;
const CLIENT_LOG_DIR = 'logs';
const CLIENT_LOG_FILE = 'client-debug.log';
const CLIENT_SESSION_MARKER = '══════ CLIENT START';
const MAX_CLIENT_LOG_SESSIONS = 5;
const MAX_CLIENT_LOG_LINES = 10_000;
const STOP_SERVER_ON_QUIT_TIMEOUT_MS = 30_000;
const LEGACY_ELECTRON_DEBUG_LOG_FILE = path.resolve(__dirname, '../electron-debug.log');
const MAIN_PROCESS_LOG_SOURCE = 'Electron';
const MAIN_PROCESS_LOG_REMAINDER_MAX = 32_768;
let clientLogFileSessionInitialized = false;
let mainWindow: BrowserWindow | null = null;

type ClientLogType = 'info' | 'success' | 'error' | 'warning';

interface ClientLogLinePayload {
  timestamp: string;
  source: string;
  message: string;
  type: ClientLogType;
}

const MAIN_PROCESS_LOG_REMAINDERS: Record<'stdout' | 'stderr', string> = {
  stdout: '',
  stderr: '',
};
let mainProcessLogRouterInstalled = false;
let legacyElectronDebugLogMigrated = false;

// Buffer log entries emitted before the renderer window is ready.
// Flushed once mainWindow.webContents fires 'did-finish-load'.
let earlyLogBuffer: ClientLogLinePayload[] | null = [];

function flushEarlyLogBuffer(): void {
  if (!earlyLogBuffer || !mainWindow) return;
  const buffered = earlyLogBuffer;
  earlyLogBuffer = null;
  for (const payload of buffered) {
    try {
      mainWindow.webContents.send('app:clientLogLine', payload);
    } catch {
      // Ignore delivery failures.
    }
  }
}

function ensureClientLogFilePath(): string {
  const logDir = path.join(app.getPath('userData'), CLIENT_LOG_DIR);
  fs.mkdirSync(logDir, { recursive: true });
  const logFilePath = path.join(logDir, CLIENT_LOG_FILE);

  if (!clientLogFileSessionInitialized) {
    try {
      // Read existing log (if any).
      let existing = '';
      try {
        existing = fs.readFileSync(logFilePath, 'utf-8');
      } catch {
        // File doesn't exist yet — fine.
      }

      // Append a session marker for the new start.
      const marker = `${CLIENT_SESSION_MARKER} ${new Date().toISOString()} ══════\n`;
      const combined = existing + marker;

      // Trim to keep only the last MAX_CLIENT_LOG_SESSIONS sessions.
      const parts = combined.split(CLIENT_SESSION_MARKER);
      const sessionTrimmed =
        parts.length > MAX_CLIENT_LOG_SESSIONS
          ? CLIENT_SESSION_MARKER +
            parts.slice(-MAX_CLIENT_LOG_SESSIONS).join(CLIENT_SESSION_MARKER)
          : combined;

      // Also enforce a hard line cap, keeping the most recent lines.
      const sessionLines = sessionTrimmed.split('\n');
      const trimmed =
        sessionLines.length > MAX_CLIENT_LOG_LINES
          ? sessionLines.slice(-MAX_CLIENT_LOG_LINES).join('\n')
          : sessionTrimmed;

      fs.writeFileSync(logFilePath, trimmed, 'utf-8');
    } catch (err) {
      console.warn('[Main] Failed to rotate client log:', err);
    }
    clientLogFileSessionInitialized = true;
  }

  return logFilePath;
}

function nowTimestamp(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function normalizeLogMessage(message: string): string {
  return message.replace(/\r?\n/g, ' ').trim();
}

function classifyMainProcessLogType(message: string, stream: 'stdout' | 'stderr'): ClientLogType {
  if (/(^|\b)(error|exception|fatal|traceback|uncaught|failed)(\b|$)/i.test(message)) {
    return 'error';
  }
  if (/(^|\b)(warn|warning|deprecated)(\b|$)/i.test(message)) {
    return 'warning';
  }
  if (/(^|\b)(ready|started|healthy|connected|success)(\b|$)/i.test(message)) {
    return 'success';
  }
  if (stream === 'stderr') {
    return 'warning';
  }
  return 'info';
}

function appendRoutedClientLogLine(message: string, type: ClientLogType): void {
  const normalizedMessage = normalizeLogMessage(message);
  if (!normalizedMessage) {
    return;
  }

  const fileTimestamp = new Date().toISOString();
  const fileLine = `[${fileTimestamp}] [${MAIN_PROCESS_LOG_SOURCE}] ${normalizedMessage}`;
  try {
    const logFilePath = ensureClientLogFilePath();
    fs.appendFileSync(logFilePath, `${fileLine}\n`, 'utf8');
  } catch {
    // Best-effort only — do not block logging output.
  }

  const payload: ClientLogLinePayload = {
    timestamp: nowTimestamp(),
    source: MAIN_PROCESS_LOG_SOURCE,
    message: normalizedMessage,
    type,
  };

  if (earlyLogBuffer) {
    // Window not ready yet — buffer for later delivery.
    earlyLogBuffer.push(payload);
  } else {
    try {
      mainWindow?.webContents.send('app:clientLogLine', payload);
    } catch {
      // Ignore renderer delivery failures.
    }
  }
}

// Chromium internal stderr noise that has no functional impact.
// These are logged at ERROR level by Chromium's C++ code but are actually
// harmless probes or race conditions — suppress them from the client log.
const SUPPRESSED_STDERR_PATTERNS: RegExp[] = [
  // VA-API probe failure on NVIDIA GPUs (belt-and-suspenders alongside disable-features)
  /vaInitialize failed/,
  // systemd scope race with --no-sandbox AppImage
  /StartTransientUnit.*UnitExists/,
];

function routeMainProcessLogLine(rawLine: string, stream: 'stdout' | 'stderr'): void {
  const normalizedLine = normalizeLogMessage(rawLine);
  if (!normalizedLine) {
    return;
  }
  if (stream === 'stderr' && SUPPRESSED_STDERR_PATTERNS.some((re) => re.test(normalizedLine))) {
    return;
  }
  appendRoutedClientLogLine(normalizedLine, classifyMainProcessLogType(normalizedLine, stream));
}

function trimMainProcessRemainder(line: string): string {
  if (line.length <= MAIN_PROCESS_LOG_REMAINDER_MAX) {
    return line;
  }
  return line.slice(-MAIN_PROCESS_LOG_REMAINDER_MAX);
}

function routeMainProcessLogChunk(chunkText: string, stream: 'stdout' | 'stderr'): void {
  if (!chunkText) return;
  const normalizedChunk = chunkText.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const pending = MAIN_PROCESS_LOG_REMAINDERS[stream];
  const combined = pending + normalizedChunk;
  const lines = combined.split('\n');
  const remainder = lines.pop() ?? '';
  MAIN_PROCESS_LOG_REMAINDERS[stream] = trimMainProcessRemainder(remainder);
  for (const line of lines) {
    routeMainProcessLogLine(line, stream);
  }
}

function flushMainProcessLogRemainders(): void {
  for (const stream of ['stdout', 'stderr'] as const) {
    const pending = MAIN_PROCESS_LOG_REMAINDERS[stream];
    if (!pending) continue;
    MAIN_PROCESS_LOG_REMAINDERS[stream] = '';
    routeMainProcessLogLine(pending, stream);
  }
}

function chunkToText(chunk: unknown, encoding?: BufferEncoding): string {
  if (typeof chunk === 'string') {
    return chunk;
  }
  if (Buffer.isBuffer(chunk)) {
    return chunk.toString(encoding);
  }
  if (chunk instanceof Uint8Array) {
    return Buffer.from(chunk).toString(encoding);
  }
  return String(chunk);
}

function installMainProcessLogRouter(): void {
  if (mainProcessLogRouterInstalled) {
    return;
  }

  for (const [streamName, stream] of [
    ['stdout', process.stdout],
    ['stderr', process.stderr],
  ] as const) {
    const originalWrite = stream.write.bind(stream);

    const routedWrite: typeof stream.write = (
      chunk: string | Uint8Array,
      encoding?: BufferEncoding | ((error: Error | null | undefined) => void),
      callback?: (error: Error | null | undefined) => void,
    ): boolean => {
      const resolvedEncoding = typeof encoding === 'string' ? encoding : undefined;
      try {
        routeMainProcessLogChunk(chunkToText(chunk, resolvedEncoding), streamName);
      } catch {
        // Ignore routing failures so stdout/stderr behavior is unchanged.
      }
      return originalWrite(chunk, encoding as any, callback as any);
    };

    stream.write = routedWrite;
  }

  mainProcessLogRouterInstalled = true;
}

function ingestLegacyElectronDebugLog(): void {
  if (!fs.existsSync(LEGACY_ELECTRON_DEBUG_LOG_FILE)) {
    return;
  }

  try {
    const legacyContent = fs.readFileSync(LEGACY_ELECTRON_DEBUG_LOG_FILE, 'utf8');
    for (const line of legacyContent.split(/\r?\n/)) {
      routeMainProcessLogLine(line, 'stdout');
    }
  } catch {
    // Best-effort only — continue startup if read fails.
    return;
  }

  try {
    fs.rmSync(LEGACY_ELECTRON_DEBUG_LOG_FILE, { force: true });
  } catch {
    // Ignore cleanup failures.
  }
}

function migrateLegacyElectronDebugLogIfNeeded(): void {
  if (legacyElectronDebugLogMigrated) {
    return;
  }
  legacyElectronDebugLogMigrated = true;
  ingestLegacyElectronDebugLog();
}

function getResolvedAppVersion(): string {
  const version = app.getVersion();
  if (version && version !== '0.0.0') {
    return version;
  }

  try {
    const packageJsonPath = path.resolve(__dirname, '../package.json');
    const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8')) as {
      version?: string;
    };
    if (packageJson.version) {
      return packageJson.version;
    }
  } catch {
    // Fall back to app.getVersion() result.
  }

  return version;
}

installMainProcessLogRouter();

// ─── Persistent Config Store ────────────────────────────────────────────────
const store = new Store({
  name: 'dashboard-config',
  accessPropertiesByDotNotation: false,
  defaults: {
    'connection.localHost': 'localhost',
    'connection.remoteHost': '',
    'connection.lanHost': '',
    'connection.remoteProfile': 'tailscale',
    'connection.useRemote': false,
    'connection.authToken': '',
    'connection.port': 9786,
    'connection.useHttps': false,
    'session.audioSource': 'mic',
    'session.micDevice': 'Default Microphone',
    'session.systemDevice': 'Default Output',
    'session.mainLanguage': 'Auto Detect',
    'session.liveLanguage': 'Auto Detect',
    'audio.gracePeriod': 1.0,
    'diarization.constrainSpeakers': true,
    'diarization.numSpeakers': 2,
    'notebook.autoAdd': false,
    'app.autoCopy': true,
    'app.showNotifications': true,
    'app.stopServerOnQuit': true,
    'app.startMinimized': false,
    'app.updateChecksEnabled': false,
    'app.updateCheckIntervalMode': '24h',
    'app.updateCheckCustomHours': 24,
    'app.modelSelectionOnboardingCompleted': false,
    'output.hideTimestamps': false,
    'ui.sidebarCollapsed': false,
    'server.host': 'localhost',
    'server.port': 9786,
    'server.https': false,
    'server.hfToken': '',
    'server.hfTokenDecision': 'unset',
    'server.containerExistsLastSeen': false,
    'updates.lastStatus': null,
    'updates.lastNotified': { appLatest: '', serverLatest: '' },
    'server.runtimeProfile': 'gpu',
    'server.mainModelSelection': 'nvidia/parakeet-tdt-0.6b-v3',
    'server.mainCustomModel': '',
    'server.liveModelSelection': 'Systran/faster-whisper-medium',
    'server.liveCustomModel': '',
    'server.diarizationModelSelection': 'pyannote/speaker-diarization-community-1',
    'server.diarizationCustomModel': '',
    'shortcuts.startRecording': 'Alt+Ctrl+Z',
    'shortcuts.stopTranscribe': 'Alt+Ctrl+X',
    'app.pasteAtCursor': false,
    'app.cumulativeUsageMs': 0,
    'app.starPopupShown': false,
    'folderWatch.sessionPath': '',
    'folderWatch.notebookPath': '',
  },
});

// Migrate any explicitly-stored old port (8000) to the current default (9786).
// store.has() guards against matching the electron-store default for unset keys.
for (const key of ['connection.port', 'server.port'] as const) {
  if (store.has(key) && store.get(key) === 8000) store.set(key, 9786);
}

// ─── Tray Manager ───────────────────────────────────────────────────────────

const trayManager = new TrayManager(isDev, () => mainWindow);

// ─── Watcher Manager ─────────────────────────────────────────────────────────

const watcherManager = new WatcherManager(() => mainWindow);

const mlxServerManager = new MLXServerManager(() => mainWindow ?? null);

// ─── Update Manager ─────────────────────────────────────────────────────────

const updateManager = new UpdateManager(store);

// Wire tray context-menu actions → IPC messages to the renderer
trayManager.setActions({
  startRecording: () => {
    mainWindow?.webContents.send('tray:action', 'start-recording');
  },
  stopRecording: () => {
    mainWindow?.webContents.send('tray:action', 'stop-recording');
  },
  cancelRecording: () => {
    mainWindow?.webContents.send('tray:action', 'cancel-recording');
  },
  toggleMute: () => {
    mainWindow?.webContents.send('tray:action', 'toggle-mute');
  },
  startLiveMode: () => {
    mainWindow?.webContents.send('tray:action', 'start-live-mode');
  },
  stopLiveMode: () => {
    mainWindow?.webContents.send('tray:action', 'stop-live-mode');
  },
  toggleLiveMute: () => {
    mainWindow?.webContents.send('tray:action', 'toggle-live-mute');
  },
  toggleModels: () => {
    mainWindow?.webContents.send('tray:action', 'toggle-models');
  },
  transcribeFile: async () => {
    const win = mainWindow;
    if (!win) return;
    const result = await dialog.showOpenDialog(win, {
      title: 'Select Audio File to Transcribe',
      filters: [
        { name: 'Audio Files', extensions: ['mp3', 'wav', 'm4a', 'flac', 'ogg', 'webm', 'opus'] },
      ],
      properties: ['openFile'],
    });
    if (!result.canceled && result.filePaths.length > 0) {
      win.webContents.send('tray:action', 'transcribe-file', result.filePaths[0]);
      if (!win.isVisible()) {
        win.show();
        win.focus();
      }
    }
  },
});

// ─── Window Creation ────────────────────────────────────────────────────────

function createWindow(): void {
  const startMinimized = store.get('app.startMinimized') as boolean;

  const iconPath = isDev
    ? path.join(__dirname, '../../docs/assets/logo.png')
    : path.join(process.resourcesPath, 'logo.png');

  mainWindow = new BrowserWindow({
    width: 1530,
    height: 860,
    minWidth: 1262,
    minHeight: 600,
    show: !startMinimized,
    icon: iconPath,
    frame: true,
    autoHideMenuBar: true,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // External URLs: open in system browser
    if (/^https?:\/\//i.test(url)) {
      void shell.openExternal(url);
      return { action: 'deny' };
    }
    // Same-origin blank windows (React Portal pop-outs): allow with native frame
    if (url === '' || url === 'about:blank') {
      return {
        action: 'allow',
        overrideBrowserWindowOptions: {
          frame: true,
          autoHideMenuBar: true,
          backgroundColor: '#0f172a',
          icon: iconPath,
          webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: false,
          },
        },
      };
    }
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const isLocalDevUrl = /^https?:\/\/(localhost|127\.0\.0\.1):3000(\/|$)/i.test(url);
    const isPackagedFileUrl = url.startsWith('file://');
    if (!isLocalDevUrl && !isPackagedFileUrl && /^https?:\/\//i.test(url)) {
      event.preventDefault();
      void shell.openExternal(url);
    }
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    // Block all DevTools entry points in production.
    mainWindow.webContents.on('before-input-event', (event, input) => {
      const ctrl = input.control || input.meta;
      if (
        input.key === 'F12' ||
        (ctrl && input.shift && ['i', 'j', 'c'].includes(input.key.toLowerCase()))
      ) {
        event.preventDefault();
      }
    });
    // Defense-in-depth: close DevTools if opened by any other means.
    mainWindow.webContents.on('devtools-opened', () => {
      mainWindow?.webContents.closeDevTools();
    });
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.removeMenu();

  // Flush any log entries buffered before the renderer was ready.
  mainWindow.webContents.on('did-finish-load', () => {
    flushEarlyLogBuffer();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ─── IPC Handlers ───────────────────────────────────────────────────────────

// Microtask coalescing flag for shortcut re-registration (see config:set handler).
let shortcutReregisterScheduled = false;

// Config: get/set client settings via electron-store
// Use store.has() so that unset keys return null rather than the electron-store
// default value. This lets the renderer-side defaults (DEFAULT_CONFIG / ??-chains)
// remain the single source of truth and prevents silent default-value surprises
// when defaults are changed between releases.
ipcMain.handle('config:get', async (_event, key: string) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return store.has(key as any) ? store.get(key as any) : null;
});

ipcMain.handle('config:set', async (_event, key: string, value: unknown) => {
  store.set(key, value);
  // Reconfigure update manager when update-related settings change
  if (key.startsWith('app.updateCheck')) {
    updateManager.reconfigure();
  }
  // Re-register shortcuts when accelerators change.
  // Best-effort coalescing: if multiple shortcuts.* writes land in the same
  // microtask checkpoint they merge into one call.  IPC handlers may run on
  // separate event-loop turns, so the serialization guard in registerShortcuts()
  // is the primary protection against concurrent D-Bus sessions.
  if (key.startsWith('shortcuts.')) {
    if (!shortcutReregisterScheduled) {
      shortcutReregisterScheduled = true;
      queueMicrotask(() => {
        shortcutReregisterScheduled = false;
        registerShortcuts(store, () => mainWindow).catch((err) =>
          console.warn('[Shortcuts] Re-registration failed:', err),
        );
      });
    }
  }
});

ipcMain.handle('config:getAll', async () => {
  return store.store;
});

// App metadata
ipcMain.handle('app:getVersion', () => {
  return getResolvedAppVersion();
});

ipcMain.handle('app:openExternal', async (_event, url: string) => {
  if (!/^https?:\/\//i.test(url)) {
    throw new Error(`Blocked non-http(s) URL: ${url}`);
  }
  await shell.openExternal(url);
});

ipcMain.handle('app:openPath', async (_event, filePath: string) => {
  return shell.openPath(filePath);
});

ipcMain.handle('app:getConfigDir', () => {
  return app.getPath('userData');
});

ipcMain.handle('app:ensureServerConfig', async () => {
  const configDir = app.getPath('userData');
  const configPath = path.join(configDir, 'config.yaml');

  fs.mkdirSync(configDir, { recursive: true });

  // Try to copy the default config from the server directory.
  const candidates = [
    // Dev mode: repo server/config.yaml
    path.resolve(__dirname, '../../server/config.yaml'),
    // Packaged: bundled extra resource
    path.join(process.resourcesPath ?? '', 'config.yaml'),
  ];

  for (const src of candidates) {
    try {
      fs.copyFileSync(src, configPath, fs.constants.COPYFILE_EXCL);
      return configPath;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
        return configPath;
      }
      // Try next candidate.
    }
  }

  // No template found — create a minimal stub so the file exists.
  try {
    fs.writeFileSync(
      configPath,
      [
        '# ============================================================================',
        '# TranscriptionSuite — User Configuration',
        '# ============================================================================',
        '# This file overrides the container defaults.',
        '# See the full reference at: server/config.yaml in the project repository.',
        '#',
        '# Uncomment and edit any section you want to customise.',
        '',
        '# main_transcriber:',
        '#   model: "nvidia/parakeet-tdt-0.6b-v3"',
        '#   compute_type: "default"',
        '#   device: "cuda"',
        '',
        '# diarization:',
        '#   parallel: false',
        '',
      ].join('\n'),
      { encoding: 'utf-8', flag: 'wx' },
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
  }
  return configPath;
});

// ---------------------------------------------------------------------------
// Server config — local-first file editing
// ---------------------------------------------------------------------------

/** Return the path to the bundled template config.yaml (dev or packaged). */
function getTemplateConfigPath(): string | null {
  const candidates = [
    // Dev mode: repo server/config.yaml
    path.resolve(__dirname, '../../server/config.yaml'),
    // Packaged: bundled extra resource
    path.join(process.resourcesPath ?? '', 'config.yaml'),
  ];
  for (const p of candidates) {
    try {
      fs.accessSync(p, fs.constants.R_OK);
      return p;
    } catch {
      // try next
    }
  }
  return null;
}

/** Read the bundled template config.yaml as text. */
ipcMain.handle('serverConfig:readTemplate', async () => {
  const templatePath = getTemplateConfigPath();
  if (!templatePath) return null;
  return fs.readFileSync(templatePath, 'utf-8');
});

/** Read the user's local config.yaml (sparse overrides). Returns null if missing. */
ipcMain.handle('serverConfig:readLocal', async () => {
  const configDir = app.getPath('userData');
  const configPath = path.join(configDir, 'config.yaml');
  try {
    return fs.readFileSync(configPath, 'utf-8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
});

/** Write text to the user's local config.yaml. Creates parent dirs if needed. */
ipcMain.handle('serverConfig:writeLocal', async (_event, yamlText: string) => {
  const configDir = app.getPath('userData');
  const configPath = path.join(configDir, 'config.yaml');
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(configPath, yamlText, 'utf-8');
});

ipcMain.handle('app:removeConfigAndCache', async () => {
  const userDataDir = app.getPath('userData');
  // Linux default: $XDG_CACHE_HOME or ~/.cache
  let cacheBaseDir = process.env.XDG_CACHE_HOME || path.join(app.getPath('home'), '.cache');
  try {
    // Electron 20+ exposes app.getPath('cache') which returns the OS-appropriate base
    // cache dir without the app name (Linux: ~/.cache, macOS: ~/Library/Caches,
    // Windows: %LOCALAPPDATA%).
    cacheBaseDir = (app as unknown as { getPath: (name: string) => string }).getPath('cache');
  } catch {
    // Fallback for older Electron builds.
    if (process.platform === 'win32') {
      // On Windows, Chromium cache lives inside userData (already deleted above),
      // so there is no separate external cache directory to remove. Point at the
      // parent of userDataDir so the subsequent rm is a harmless no-op.
      cacheBaseDir = path.dirname(userDataDir);
    } else if (process.platform === 'darwin') {
      cacheBaseDir = path.join(app.getPath('home'), 'Library', 'Caches');
    }
    // Linux: the XDG_CACHE_HOME default set above is already correct.
  }
  const externalCacheDir = path.join(cacheBaseDir, 'TranscriptionSuite');

  // Clear Chromium/Electron session data before deleting the directories so that
  // in-memory state is wiped and Electron does not immediately flush stale data
  // back to disk after the rm. This covers cookies, localStorage, sessionStorage,
  // IndexedDB, shader cache, service workers, etc.
  await Promise.all([
    session.defaultSession.clearStorageData(),
    session.defaultSession.clearCache(),
    session.defaultSession.clearHostResolverCache(),
    session.defaultSession.clearAuthCache(),
  ]);

  await Promise.all([
    fs.promises.rm(userDataDir, { recursive: true, force: true }),
    fs.promises.rm(externalCacheDir, { recursive: true, force: true }),
  ]);

  // Do NOT recreate userDataDir here — ensureClientLogFilePath() already calls
  // mkdirSync lazily, so explicitly recreating the directory would cause the config
  // folder to persist as an empty directory after "Clean All".
  clientLogFileSessionInitialized = false;
});

ipcMain.handle('app:getClientLogPath', () => {
  migrateLegacyElectronDebugLogIfNeeded();
  return ensureClientLogFilePath();
});

ipcMain.handle('app:appendClientLogLine', async (_event, line: string) => {
  const logFilePath = ensureClientLogFilePath();
  const normalizedLine = String(line).replace(/\r?\n/g, ' ');
  await fs.promises.appendFile(logFilePath, `${normalizedLine}\n`, 'utf8');
});

ipcMain.handle('app:readLogFiles', async (_event, tailLines: number) => {
  const logDir = path.join(app.getPath('userData'), 'logs');
  const clientLogPath = path.join(logDir, 'client-debug.log');
  const serverLogPath = path.join(logDir, 'server.log');

  const readTail = (filePath: string, maxLines: number): string => {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const lines = content.split('\n');
      return lines.slice(-maxLines).join('\n');
    } catch {
      return '';
    }
  };

  return {
    clientLog: readTail(clientLogPath, tailLines),
    serverLog: readTail(serverLogPath, tailLines),
    clientLogPath,
    serverLogPath,
  };
});

ipcMain.handle('app:readLocalFile', async (_event, filePath: string) => {
  const buffer = fs.readFileSync(filePath);
  const name = path.basename(filePath);
  const ext = path.extname(filePath).toLowerCase().slice(1);
  const mimeMap: Record<string, string> = {
    mp3: 'audio/mpeg',
    wav: 'audio/wav',
    m4a: 'audio/mp4',
    flac: 'audio/flac',
    ogg: 'audio/ogg',
    webm: 'audio/webm',
    opus: 'audio/opus',
  };
  return { name, buffer: buffer.buffer, mimeType: mimeMap[ext] || 'audio/mpeg' };
});

// ─── File I/O IPC (Session Import) ─────────────────────────────────────────

ipcMain.handle('app:getDownloadsPath', () => {
  return app.getPath('downloads');
});

ipcMain.handle('file:writeText', async (_event, filePath: string, content: string) => {
  // Validate the path is under a user-accessible directory (no path traversal)
  const resolved = path.resolve(filePath);
  await fs.promises.writeFile(resolved, content, 'utf-8');
});

ipcMain.handle('dialog:selectFolder', async () => {
  const mainWindow = BrowserWindow.getAllWindows()[0];
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ─── Docker Management IPC ──────────────────────────────────────────────────

ipcMain.handle('docker:available', async () => {
  return dockerManager.dockerAvailable();
});

ipcMain.handle('docker:retryDetection', async () => {
  dockerManager.retryDetection();
  return dockerManager.dockerAvailable();
});

ipcMain.handle('docker:getRuntimeKind', async () => {
  return dockerManager.getRuntimeKind();
});

ipcMain.handle('docker:getDetectionGuidance', async () => {
  return dockerManager.getDetectionGuidance();
});

ipcMain.handle('docker:checkGpu', async () => {
  return dockerManager.checkGpu();
});

ipcMain.handle('docker:listImages', async () => {
  return dockerManager.listImages();
});

ipcMain.handle('docker:pullImage', async (_event, tag: string) => {
  return dockerManager.pullImage(tag);
});

ipcMain.handle('docker:cancelPull', () => {
  return dockerManager.cancelPull();
});

ipcMain.handle('docker:isPulling', () => {
  return dockerManager.isPulling();
});

ipcMain.handle('docker:hasSidecarImage', async () => {
  return dockerManager.hasSidecarImage();
});

ipcMain.handle('docker:pullSidecarImage', async () => {
  return dockerManager.pullSidecarImage();
});

ipcMain.handle('docker:cancelSidecarPull', () => {
  return dockerManager.cancelSidecarPull();
});

ipcMain.handle('docker:isSidecarPulling', () => {
  return dockerManager.isSidecarPulling();
});

ipcMain.handle('docker:removeImage', async (_event, tag: string) => {
  return dockerManager.removeImage(tag);
});

ipcMain.handle('docker:getContainerStatus', async () => {
  return dockerManager.getContainerStatus();
});

// ─── Startup Event Watcher ────────────────────────────────────────────────
// Watches the bind-mounted startup-events.jsonl file and forwards parsed
// events to the renderer via IPC for the activityStore.

const startupEventWatcher = new StartupEventWatcher();

ipcMain.handle('docker:startContainer', async (_event, options: StartContainerOptions) => {
  const result = await dockerManager.startContainer(options);
  // Begin writing to server.log as soon as the container is running.
  dockerManager.startBackgroundLogStream();

  // Start watching startup events file (set during startContainer)
  const eventsFile = dockerManager.getStartupEventsFilePath();
  if (eventsFile) {
    startupEventWatcher.start(eventsFile, (event) => {
      mainWindow?.webContents.send('activity:event', event);
    });
  }

  return result;
});

ipcMain.handle('docker:stopContainer', async () => {
  startupEventWatcher.stop();
  return dockerManager.stopContainer();
});

ipcMain.handle('docker:removeContainer', async () => {
  return dockerManager.removeContainer();
});

ipcMain.handle('docker:getVolumes', async () => {
  return dockerManager.getVolumes();
});

ipcMain.handle('docker:checkModelsCached', async (_event, modelIds: string[]) => {
  return dockerManager.checkModelsCached(modelIds);
});

ipcMain.handle('docker:removeModelCache', async (_event, modelId: string) => {
  return dockerManager.removeModelCache(modelId);
});

ipcMain.handle('docker:downloadModelToCache', async (_event, modelId: string) => {
  return dockerManager.downloadModelToCache(modelId);
});

ipcMain.handle('docker:removeVolume', async (_event, name: string) => {
  return dockerManager.removeVolume(name);
});

ipcMain.handle('docker:readComposeEnvValue', async (_event, key: string) => {
  return dockerManager.readComposeEnvValue(key);
});

ipcMain.handle('docker:volumeExists', async (_event, name: string) => {
  return dockerManager.volumeExists(name);
});

ipcMain.handle('docker:readOptionalDependencyBootstrapStatus', async () => {
  return dockerManager.readOptionalDependencyBootstrapStatus();
});

ipcMain.handle('docker:checkTailscaleCertsExist', async () => {
  return dockerManager.checkTailscaleCertsExist();
});

ipcMain.handle('docker:getLogs', async (_event, tail?: number) => {
  return dockerManager.getLogs(tail);
});

// ─── Docker Log Streaming IPC ───────────────────────────────────────────────

// Stable callback reference so subscribe and unsubscribe target the same function.
let rendererLogCallback: ((line: string) => void) | null = null;

ipcMain.handle('docker:startLogStream', async () => {
  rendererLogCallback = (line: string) => {
    mainWindow?.webContents.send('docker:logLine', line);
  };
  dockerManager.subscribeToLogStream(rendererLogCallback);
});

ipcMain.handle('docker:stopLogStream', async () => {
  if (rendererLogCallback) {
    dockerManager.unsubscribeFromLogStream(rendererLogCallback);
    rendererLogCallback = null;
  }
});

// ─── Bootstrap Download Event Bridge ──────────────────────────────────────
// Permanent subscriber — forwards structured download events from the
// bootstrap log parser to the renderer so the download store can track
// in-container installs regardless of which UI tab is active.

dockerManager.subscribeToDownloadEvents((event) => {
  mainWindow?.webContents.send('docker:downloadEvent', event);
});

// ─── Audio IPC ──────────────────────────────────────────────────────────────

// Legacy stub — kept so older renderer builds don't crash on missing handler.
ipcMain.handle('audio:getDesktopSources', async () => []);

// --- Windows / macOS: getDisplayMedia loopback (no portal picker) -----------
// On Linux/Wayland the xdg-desktop-portal ALWAYS shows a screen picker for
// getDisplayMedia — setDisplayMediaRequestHandler cannot suppress it.  These
// handlers are therefore only useful on Windows & macOS.

ipcMain.handle('audio:enableSystemAudioLoopback', async () => {
  if (process.platform === 'linux') return; // no-op on Linux
  session.defaultSession.setDisplayMediaRequestHandler(async (_request, callback) => {
    const sources = await desktopCapturer.getSources({ types: ['screen'] });
    callback({ audio: 'loopback', video: sources[0], enableLocalEcho: false } as any);
  });
});

ipcMain.handle('audio:disableSystemAudioLoopback', async () => {
  if (process.platform === 'linux') return;
  session.defaultSession.setDisplayMediaRequestHandler(null as any);
});

// --- Linux: PulseAudio/PipeWire monitor-source loopback ---------------------
// Create a temporary virtual input device from the PulseAudio/PipeWire monitor
// source via module-remap-source.  The renderer then captures from it with
// plain getUserMedia — no xdg-desktop-portal, no screen picker.

let loopbackModuleId: number | null = null;

/** List audio output sinks (for the system-device dropdown on Linux). */
ipcMain.handle(
  'audio:listSinks',
  async (): Promise<Array<{ name: string; description: string }>> => {
    if (process.platform !== 'linux') return [];
    try {
      const { stdout } = await execFileAsync('pactl', ['-f', 'json', 'list', 'sinks']);
      const sinks = JSON.parse(stdout) as Array<{ name: string; description: string }>;
      return sinks.map((s) => ({ name: s.name, description: s.description }));
    } catch {
      return [];
    }
  },
);

/** Create a virtual mic from a sink's monitor source. */
ipcMain.handle('audio:createMonitorLoopback', async (_e, sinkName: string) => {
  // Clean up any previous loopback first
  if (loopbackModuleId !== null) {
    try {
      await execFileAsync('pactl', ['unload-module', String(loopbackModuleId)]);
    } catch {
      /* already gone */
    }
    loopbackModuleId = null;
  }
  const { stdout } = await execFileAsync('pactl', [
    'load-module',
    'module-remap-source',
    `master=${sinkName}.monitor`,
    'source_name=tsuite_loopback',
    'source_properties=device.description=TranscriptionSuite_Loopback',
  ]);
  loopbackModuleId = parseInt(stdout.trim(), 10);

  // Ensure both the master monitor source and the virtual remap source are at
  // 100 % (0 dB).  PipeWire/PulseAudio may inherit a lower volume from the
  // sink, causing very faint capture on some devices (e.g. headphone outputs
  // whose sink volume is low).  65536 = 100 % in PulseAudio volume units.
  try {
    await execFileAsync('pactl', ['set-source-volume', `${sinkName}.monitor`, '65536']);
  } catch {
    /* best-effort — some sinks may not allow volume changes */
  }
  try {
    await execFileAsync('pactl', ['set-source-volume', 'tsuite_loopback', '65536']);
  } catch {
    /* best-effort */
  }

  // Read back the effective volume to return as a diagnostic percentage.
  let volumePct: number | null = null;
  try {
    const { stdout: srcJson } = await execFileAsync('pactl', ['-f', 'json', 'list', 'sources']);
    const sources = JSON.parse(srcJson) as Array<{
      name: string;
      volume: Record<string, { value_percent: string }>;
    }>;
    const loopSrc = sources.find((s) => s.name === 'tsuite_loopback');
    if (loopSrc?.volume) {
      const firstCh = Object.values(loopSrc.volume)[0];
      if (firstCh?.value_percent) {
        volumePct = parseInt(firstCh.value_percent, 10);
      }
    }
  } catch {
    /* diagnostic only — non-fatal */
  }

  return { moduleId: loopbackModuleId, volumePct };
});

/** Remove the virtual mic. */
ipcMain.handle('audio:removeMonitorLoopback', async () => {
  if (loopbackModuleId === null) return;
  try {
    await execFileAsync('pactl', ['unload-module', String(loopbackModuleId)]);
  } catch {
    /* already gone */
  }
  loopbackModuleId = null;
});

// Safety-net: clean up the loopback module on quit so it doesn't linger.
app.on('will-quit', () => {
  if (loopbackModuleId !== null && process.platform === 'linux') {
    try {
      execFileSync('pactl', ['unload-module', String(loopbackModuleId)]);
    } catch {
      /* best-effort */
    }
    loopbackModuleId = null;
  }
});

// ─── Clipboard IPC ──────────────────────────────────────────────────────────

ipcMain.handle('clipboard:writeText', (_event, text: string) => {
  clipboard.writeText(text);
});

ipcMain.handle(
  'clipboard:pasteAtCursor',
  async (_event, text: string, options?: { preserveClipboard?: boolean }) => {
    try {
      await pasteAtCursor(text, options);
    } catch (err) {
      // Non-fatal — text is already in the clipboard for manual paste
      console.warn('[PasteAtCursor] Failed:', err);
    }
  },
);

// ─── Update Check IPC ───────────────────────────────────────────────────────

ipcMain.handle('updates:getStatus', async () => {
  return updateManager.getStatus();
});

ipcMain.handle('updates:checkNow', async () => {
  return updateManager.check();
});

// ─── Server Connection Probe IPC ────────────────────────────────────────────

/**
 * Read config.yaml values (mirrors dockerManager's resolveTlsCertPaths logic).
 * Returns the extract + expandTilde helpers and the raw YAML text so callers
 * can look up arbitrary configuration keys.
 */
function readTlsConfig() {
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
      /* next */
    }
  }
  let userText = '';
  try {
    userText = fs.readFileSync(userConfigPath, 'utf8');
  } catch {
    /* optional */
  }

  const extract = (text: string, key: string) => {
    const m = new RegExp(`^[ \\t]+${key}:[ \\t]*(["']?)([^"'\\r\\n#]+?)\\1[ \\t]*$`, 'm').exec(
      text,
    );
    return m ? m[2].trim() || undefined : undefined;
  };
  const expandTilde = (p: string) => {
    if (p === '~') return app.getPath('home');
    if (p.startsWith('~/') || p.startsWith('~\\'))
      return path.join(app.getPath('home'), p.slice(2));
    return p;
  };

  return { userText, templateText, extract, expandTilde };
}

/**
 * Try to read a PEM cert from a config.yaml key.  Returns the Buffer if
 * the file was readable, or `undefined` if the key is missing / file absent.
 */
function tryLoadCertFromConfig(
  cfg: ReturnType<typeof readTlsConfig>,
  key: string,
): Buffer | undefined {
  const raw = cfg.extract(cfg.userText, key) ?? cfg.extract(cfg.templateText, key);
  if (!raw) return undefined;
  try {
    return fs.readFileSync(cfg.expandTilde(raw));
  } catch {
    return undefined;
  }
}

/**
 * Build an https.Agent for LAN-profile connections that tolerates hostname
 * mismatch without the blanket `rejectUnauthorized: false` that CodeQL flags
 * (CWE-295, CWE-297).
 *
 * Uses a 3-tier fallback strategy:
 *
 *   Tier 1 — LAN cert pinning
 *     Load `lan_host_cert_path` from config.yaml, pin its SHA-256 fingerprint.
 *     Hostname mismatch is tolerated only if the peer cert matches our pin.
 *     Works when server was started with LAN profile.
 *
 *   Tier 2 — Tailscale cert pinning
 *     If LAN cert doesn't exist (server started with Tailscale profile), load
 *     `host_cert_path` (the Tailscale cert) and pin that fingerprint instead.
 *     Common case: server uses its LE-signed Tailscale cert, LAN client
 *     connects via IP — hostname won't match but cert is pinned.
 *
 *   Tier 3 — Chain-validated hostname skip
 *     If neither cert file is loadable, skip only hostname validation while
 *     keeping `rejectUnauthorized: true` (i.e. the cert chain must still be
 *     valid against the system CA store).  This handles LE-signed certs
 *     where the chain verifies fine but the hostname differs.
 *
 * All tiers avoid `rejectUnauthorized: false` → no CodeQL flag.
 */
function buildLanTlsAgent(): https.Agent {
  const cfg = readTlsConfig();

  // Helper: build a fingerprint-pinned agent from a PEM buffer.
  const pinned = (certPem: Buffer): https.Agent => {
    const x509 = new crypto.X509Certificate(certPem);
    const expectedFp = x509.fingerprint256;
    return new https.Agent({
      ca: [certPem],
      checkServerIdentity: (_host: string, peer: { fingerprint256?: string }) => {
        if (peer.fingerprint256 === expectedFp) return undefined;
        return new Error(
          'TLS certificate fingerprint mismatch — the server is not presenting the expected certificate',
        );
      },
    });
  };

  // Tier 1: LAN self-signed cert
  const lanCert = tryLoadCertFromConfig(cfg, 'lan_host_cert_path');
  if (lanCert) return pinned(lanCert);

  // Tier 2: Tailscale cert (server started with Tailscale profile, client on LAN)
  const tsCert = tryLoadCertFromConfig(cfg, 'host_cert_path');
  if (tsCert) return pinned(tsCert);

  // Tier 3: Skip hostname check only — cert chain must still validate
  // against the system CA store (e.g. LE-signed certs pass).
  return new https.Agent({
    checkServerIdentity: () => undefined,
  });
}

/** Probe a URL from the main process using Node.js http(s) for specific error codes. */
ipcMain.handle(
  'server:probeConnection',
  async (
    _event,
    url: string,
    skipCertVerify: boolean,
  ): Promise<{
    ok: boolean;
    httpStatus?: number;
    error?: string;
    errorCode?: string;
    body?: string;
  }> => {
    return new Promise((resolve) => {
      try {
        const parsed = new URL(url);
        const isHttps = parsed.protocol === 'https:';
        const mod = isHttps ? https : http;

        // For LAN profile: use a certificate-aware agent that tolerates
        // hostname mismatch without disabling validation entirely.
        const lanAgent = isHttps && skipCertVerify ? buildLanTlsAgent() : undefined;

        const options: https.RequestOptions = {
          hostname: parsed.hostname,
          port: parsed.port || (isHttps ? 443 : 80),
          path: parsed.pathname + parsed.search,
          method: 'GET',
          timeout: 10_000,
          ...(lanAgent ? { agent: lanAgent } : {}),
        };

        const req = mod.request(options, (res) => {
          // Collect the response body (up to 64 KB) so the renderer can
          // use it directly instead of making a redundant second request.
          const chunks: Buffer[] = [];
          let totalLen = 0;
          const MAX_BODY = 64 * 1024;
          res.on('data', (chunk: Buffer) => {
            if (totalLen < MAX_BODY) {
              chunks.push(chunk);
              totalLen += chunk.length;
            }
          });
          res.on('end', () => {
            const body = Buffer.concat(chunks).toString('utf-8').slice(0, MAX_BODY);
            resolve({
              ok: (res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 400,
              httpStatus: res.statusCode,
              body,
            });
          });
          res.on('error', () => {
            // Body read failed — still return probe result without body
            resolve({
              ok: (res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 400,
              httpStatus: res.statusCode,
            });
          });
        });

        req.on('error', (err: NodeJS.ErrnoException) => {
          const code = err.code ?? '';
          const port = parsed.port || (isHttps ? 443 : 80);
          const isTailscale = parsed.hostname.endsWith('.ts.net');
          let error: string;
          if (code === 'ENOTFOUND') {
            error = isTailscale
              ? `DNS: '${parsed.hostname}' not found — is Tailscale running on this machine?`
              : `DNS: '${parsed.hostname}' not found`;
          } else if (code === 'ECONNREFUSED') {
            error = `Connection refused on port ${port}`;
          } else if (code === 'ERR_TLS_CERT_ALTNAME_INVALID') {
            error = `TLS: certificate is for a different hostname`;
          } else if (code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE') {
            error = 'TLS: certificate not trusted';
          } else if (code === 'CERT_HAS_EXPIRED') {
            error = 'TLS: certificate expired';
          } else if (code === 'DEPTH_ZERO_SELF_SIGNED_CERT') {
            error = 'TLS: self-signed certificate';
          } else if (code === 'ETIMEDOUT' || code === 'ERR_CONNECTION_TIMED_OUT') {
            error = isTailscale
              ? `Connection timed out — check Tailscale status on both machines`
              : `Connection timed out — check if the server firewall allows port ${port}`;
          } else if (code.startsWith('ERR_TLS_') || code.startsWith('CERT_')) {
            error = `TLS error: ${err.message}`;
          } else {
            error = err.message || 'Unknown connection error';
          }
          resolve({ ok: false, error, errorCode: code });
        });

        req.on('timeout', () => {
          req.destroy();
          const isTsNet = parsed.hostname.endsWith('.ts.net');
          resolve({
            ok: false,
            error: isTsNet
              ? 'Connection timed out — check Tailscale status on both machines'
              : `Connection timed out — check if the server firewall allows port ${parsed.port || (isHttps ? 443 : 80)}`,
            errorCode: 'ETIMEDOUT',
          });
        });

        req.end();
      } catch (err) {
        resolve({
          ok: false,
          error: err instanceof Error ? err.message : 'Invalid URL',
          errorCode: 'ERR_INVALID_URL',
        });
      }
    });
  },
);

// ─── Tailscale Hostname IPC ─────────────────────────────────────────────────

/** Detect the local machine's Tailscale FQDN via `tailscale status --json`. */
ipcMain.handle('tailscale:getHostname', async (): Promise<string | null> => {
  try {
    const { stdout } = await execFileAsync('tailscale', ['status', '--json'], { timeout: 5000 });
    const parsed = JSON.parse(stdout) as { Self?: { DNSName?: string } };
    const dnsName = parsed?.Self?.DNSName;
    if (!dnsName) return null;
    // Strip trailing dot from FQDN (e.g. "desktop.my-server.ts.net." → "desktop.my-server.ts.net")
    return dnsName.replace(/\.$/, '');
  } catch {
    // Tailscale not installed or not running
    return null;
  }
});

// ─── Tray IPC Handlers ─────────────────────────────────────────────────────

/**
 * Check if the server port is accessible from a non-loopback interface.
 *
 * This helps detect firewall issues on the server machine when running in
 * remote mode: the server may be listening on 0.0.0.0:<port> but a host
 * firewall (ufw, firewalld, Windows Firewall) may be blocking inbound
 * connections.  We attempt a TCP connect from the loopback address to a
 * non-loopback IP to simulate what a LAN/Tailscale client would do.
 *
 * Returns { listening, firewallSuspect, hint }.
 */
ipcMain.handle(
  'server:checkFirewallPort',
  async (
    _event,
    port: number,
  ): Promise<{ listening: boolean; firewallSuspect: boolean; hint: string | null }> => {
    // Step 1: Is anything listening on 0.0.0.0:<port> locally?
    const localReachable = await new Promise<boolean>((resolve) => {
      const sock = net.createConnection({ host: '127.0.0.1', port, timeout: 3000 });
      sock.on('connect', () => {
        sock.destroy();
        resolve(true);
      });
      sock.on('error', () => resolve(false));
      sock.on('timeout', () => {
        sock.destroy();
        resolve(false);
      });
    });

    if (!localReachable) {
      return { listening: false, firewallSuspect: false, hint: null };
    }

    // Step 2: Find a non-loopback IPv4 address and try to connect via it.
    // If the connection times out but localhost worked, a firewall is likely blocking.
    const interfaces = os.networkInterfaces();
    let lanIp: string | null = null;
    for (const [, addrs] of Object.entries(interfaces)) {
      if (!addrs) continue;
      for (const addr of addrs) {
        if (addr.family === 'IPv4' && !addr.internal) {
          lanIp = addr.address;
          break;
        }
      }
      if (lanIp) break;
    }

    if (!lanIp) {
      // No LAN interfaces — can't test, assume OK
      return { listening: true, firewallSuspect: false, hint: null };
    }

    const externalReachable = await new Promise<boolean>((resolve) => {
      const sock = net.createConnection({ host: lanIp!, port, timeout: 3000 });
      sock.on('connect', () => {
        sock.destroy();
        resolve(true);
      });
      sock.on('error', () => resolve(false));
      sock.on('timeout', () => {
        sock.destroy();
        resolve(false);
      });
    });

    if (externalReachable) {
      return { listening: true, firewallSuspect: false, hint: null };
    }

    // Server listens locally but not on external IP → firewall is likely blocking
    const platform = process.platform;
    let hint: string;
    if (platform === 'linux') {
      hint = `Port ${port} appears blocked by your firewall. Try: sudo ufw allow ${port}/tcp`;
    } else if (platform === 'win32') {
      hint = `Port ${port} appears blocked by Windows Firewall. Open it in Windows Defender Firewall settings.`;
    } else {
      hint = `Port ${port} appears blocked by your firewall. Allow incoming connections on port ${port}.`;
    }
    return { listening: true, firewallSuspect: true, hint };
  },
);

ipcMain.handle('tray:setTooltip', async (_event, tooltip: string) => {
  trayManager.setTooltip(tooltip);
});

ipcMain.handle('tray:setState', async (_event, state: TrayState) => {
  trayManager.setState(state);
});

ipcMain.handle(
  'tray:setMenuState',
  async (
    _event,
    menuState: {
      serverRunning?: boolean;
      isRecording?: boolean;
      isLive?: boolean;
      isMuted?: boolean;
      modelsLoaded?: boolean;
      isLocalConnection?: boolean;
      canCancel?: boolean;
      isStandby?: boolean;
      canTranscribeFile?: boolean;
    },
  ) => {
    trayManager.setMenuState(menuState);
  },
);

// ─── App Lifecycle ──────────────────────────────────────────────────────────

let isQuitting = false;
let shutdownPromise: Promise<void> | null = null;
let sentinelPid: number | null = null;

/**
 * Spawn a sentinel process that watches for Electron PID death and stops the
 * Docker container. Uses `setsid` to create a new session so the sentinel
 * survives SIGBUS/SIGKILL of the parent process group. Linux only.
 */
function spawnContainerSentinel(): void {
  if (process.platform !== 'linux') return;

  const shouldStopServer = (store.get('app.stopServerOnQuit') as boolean) ?? true;
  const useRemote = (store.get('connection.useRemote') as boolean) ?? false;
  if (!shouldStopServer || useRemote) return;

  const pid = process.pid;
  const child = spawn(
    'setsid',
    [
      'sh',
      '-c',
      `while kill -0 ${pid} 2>/dev/null; do sleep 2; done; docker stop --time 10 ${CONTAINER_NAME} 2>/dev/null`,
    ],
    { detached: true, stdio: 'ignore' },
  );
  child.unref();
  sentinelPid = child.pid ?? null;
  if (sentinelPid === null) {
    shutdownLog('[Sentinel] Failed to spawn container sentinel (setsid not found?)');
    return;
  }
  shutdownLog(`[Sentinel] Spawned container sentinel (PID: ${sentinelPid})`);
}

/**
 * Log a shutdown diagnostic message. Writes to console, which is already
 * routed to client-debug.log by installMainProcessLogRouter — no separate
 * shutdown.log file is needed.
 */
function shutdownLog(message: string): void {
  console.log(`${new Date().toISOString()} ${message}`);
}

/**
 * Shared shutdown cleanup: stop the Docker container (if configured and in
 * local mode), destroy tray and update manager.  Idempotent — only runs once;
 * every caller awaits the same Promise.
 */
function gracefulShutdown(): Promise<void> {
  if (shutdownPromise) return shutdownPromise;
  isQuitting = true;

  shutdownPromise = (async () => {
    flushMainProcessLogRemainders();
    // Kill the container sentinel before we stop the container ourselves —
    // prevents both racing to docker-stop.
    if (sentinelPid !== null) {
      try {
        process.kill(sentinelPid, 'SIGTERM');
      } catch {
        /* already dead */
      }
      shutdownLog('[Sentinel] Killed container sentinel.');
      sentinelPid = null;
    }
    // Stop the background log stream so the disk writer shuts down cleanly.
    dockerManager.stopBackgroundLogStream();
    shutdownLog('[Shutdown] Graceful shutdown started.');

    const shouldStopServer = (store.get('app.stopServerOnQuit') as boolean) ?? true;
    const useRemote = (store.get('connection.useRemote') as boolean) ?? false;
    shutdownLog(`[Shutdown] stopServerOnQuit=${shouldStopServer}, useRemote=${useRemote}`);

    if (shouldStopServer && !useRemote) {
      try {
        shutdownLog('[Shutdown] Stopping server container (docker stop)…');
        await Promise.race([
          dockerManager.forceStopContainer(10),
          new Promise<never>((_, reject) =>
            setTimeout(
              () => reject(new Error(`Timed out after ${STOP_SERVER_ON_QUIT_TIMEOUT_MS}ms`)),
              STOP_SERVER_ON_QUIT_TIMEOUT_MS,
            ),
          ),
        ]);
        shutdownLog('[Shutdown] Server container stopped.');
      } catch (err) {
        shutdownLog(`[Shutdown] Container stop failed: ${err}`);
      }
    } else {
      shutdownLog('[Shutdown] Skipping container stop.');
    }

    unregisterShortcuts();
    trayManager.destroy();
    updateManager.destroy();
    await mlxServerManager.destroy();
    await watcherManager.destroyAll();
    shutdownLog('[Shutdown] Cleanup complete.');
  })();

  return shutdownPromise;
}

// Catch SIGINT / SIGTERM / SIGHUP so Docker cleanup runs even when the process
// is killed by a signal (Ctrl-C, terminal close, systemd stop, Wayland session
// teardown, etc.) rather than through Electron's normal app.quit() path.
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP'] as const) {
  process.on(sig, () => {
    shutdownLog(`[Shutdown] Received ${sig}`);
    gracefulShutdown().finally(() => app.exit(0));
  });
}

// SIGUSR1 → start recording, SIGUSR2 → stop recording (Wayland / CLI fallback)
if (process.platform !== 'win32') {
  process.on('SIGUSR1', () => {
    console.log('[Shortcuts] Received SIGUSR1 → start-recording');
    mainWindow?.webContents.send('tray:action', 'start-recording');
  });
  process.on('SIGUSR2', () => {
    console.log('[Shortcuts] Received SIGUSR2 → stop-recording');
    mainWindow?.webContents.send('tray:action', 'stop-recording');
  });
}

// ─── Single-Instance Lock ────────────────────────────────────────────────────
// Second instance forwards argv to the first via the 'second-instance' event,
// then exits.  This enables CLI-arg shortcut forwarding on Wayland.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

app.whenReady().then(() => {
  // ─── Certificate Error Handler (LAN profile) ────────────────────────────
  // Tailscale certs only cover *.ts.net FQDNs, not IP addresses. LAN
  // connections will always fail TLS hostname validation. Accept the cert
  // mismatch when the user has selected LAN remote profile.
  app.on('certificate-error', (event, _webContents, _url, _error, _certificate, callback) => {
    const remoteProfile = store.get('connection.remoteProfile') as string;
    const useRemote = store.get('connection.useRemote') as boolean;
    if (useRemote && remoteProfile === 'lan') {
      event.preventDefault();
      callback(true);
    } else {
      callback(false);
    }
  });

  trayManager.create();
  updateManager.start();
  createWindow();

  // If the container is already running (app restarted while server was up),
  // start streaming its logs to disk immediately — no UI interaction needed.
  dockerManager
    .getContainerStatus()
    .then((status) => {
      if (status.running) dockerManager.startBackgroundLogStream();
    })
    .catch(() => {
      // Best-effort — Docker may not be available yet.
    });

  // Crash-resilient container cleanup: sentinel survives SIGBUS/SIGKILL
  spawnContainerSentinel();

  // Auto-start the native MLX server if the Metal runtime profile is selected.
  const runtimeProfile = store.get('server.runtimeProfile') as string;
  if (runtimeProfile === 'metal') {
    const port = (store.get('server.port') as number) ?? 9786;
    const hfToken = (store.get('server.hfToken') as string) || undefined;
    const mainTranscriberModel =
      (store.get('server.mainModelSelection') as string) || 'mlx-community/whisper-small-asr-fp16';

    // Resolve live transcriber model from stored selection sentinels.
    const LIVE_SAME_AS_MAIN = 'Same as Main Transcriber';
    const LIVE_CUSTOM = 'Custom (HuggingFace repo)';
    const liveModelSelection = (store.get('server.liveModelSelection') as string) || '';
    const liveCustomModel = (store.get('server.liveCustomModel') as string) || '';
    let resolvedLiveModel: string;
    if (liveModelSelection === 'None (Disabled)' || liveModelSelection === '__none__') {
      resolvedLiveModel = '';
    } else if (!liveModelSelection || liveModelSelection === LIVE_SAME_AS_MAIN) {
      resolvedLiveModel = mainTranscriberModel;
    } else if (liveModelSelection === LIVE_CUSTOM) {
      resolvedLiveModel = liveCustomModel || mainTranscriberModel;
    } else {
      resolvedLiveModel = liveModelSelection;
    }
    // Normalize: if resolved model is MLX, fall back to faster-whisper.
    if (resolvedLiveModel && /mlx/i.test(resolvedLiveModel)) {
      resolvedLiveModel = 'Systran/faster-whisper-medium';
    }

    const diarizationModel = (store.get('server.diarizationModelSelection') as string) || undefined;

    mlxServerManager
      .start({
        port,
        hfToken,
        mainTranscriberModel,
        liveTranscriberModel: resolvedLiveModel || undefined,
        diarizationModel: diarizationModel || undefined,
      })
      .catch((err: unknown) => console.warn('[MLX] Auto-start failed:', err));
  }

  // Register global keyboard shortcuts (async — uses D-Bus portal on Wayland)
  registerShortcuts(store, () => mainWindow).catch((err) =>
    console.warn('[Shortcuts] Initial registration failed:', err),
  );

  // Forward CLI args from second instance to first instance
  app.on('second-instance', (_event, argv) => {
    handleCliAction(argv, () => mainWindow);
    // Bring window to front when second instance launched
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });

  // Handle close-to-tray: hide window instead of quitting
  if (mainWindow) {
    mainWindow.on('close', (event) => {
      if (!isQuitting) {
        event.preventDefault();
        mainWindow?.hide();
        trayManager.notifyWindowVisibilityChanged();
      }
    });

    // Keep tray menu label in sync when the window is shown by any means
    mainWindow.on('show', () => {
      trayManager.notifyWindowVisibilityChanged();
    });
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// ─── MLX Server IPC Handlers ────────────────────────────────────────────────

ipcMain.handle('mlx:start', async (_event, opts: MLXStartOptions) => {
  await mlxServerManager.start(opts);
});

ipcMain.handle('mlx:stop', async () => {
  await mlxServerManager.stop();
});

ipcMain.handle('mlx:getStatus', () => {
  return mlxServerManager.getStatus();
});

ipcMain.handle('mlx:getLogs', (_event, tail?: number) => {
  return mlxServerManager.getLogs(tail);
});

// ─── Watcher IPC Handlers ────────────────────────────────────────────────────

ipcMain.handle('watcher:startSession', async (_event, folderPath: string) => {
  await watcherManager.startSessionWatcher(folderPath);
});

ipcMain.handle('watcher:stopSession', async () => {
  await watcherManager.stopSessionWatcher();
});

ipcMain.handle('watcher:startNotebook', async (_event, folderPath: string) => {
  await watcherManager.startNotebookWatcher(folderPath);
});

ipcMain.handle('watcher:stopNotebook', async () => {
  await watcherManager.stopNotebookWatcher();
});

ipcMain.handle('watcher:clearLedger', async (_event, type: 'session' | 'notebook') => {
  if (type === 'session') watcherManager.clearSessionLedger();
  else watcherManager.clearNotebookLedger();
});

ipcMain.handle('watcher:checkPath', async (_event, folderPath: string) => {
  try {
    return fs.statSync(folderPath).isDirectory();
  } catch {
    return false;
  }
});

// ─── Shortcuts IPC Handlers ─────────────────────────────────────────────────

ipcMain.handle('shortcuts:getPortalBindings', async () => {
  return getPortalShortcuts();
});

ipcMain.handle('shortcuts:rebind', async () => {
  await rebindPortalShortcuts(store);
});

ipcMain.handle('shortcuts:isWaylandPortal', () => {
  return isWaylandPortalActive();
});

// Desktop notifications via Electron's async Notification module.
// The Web Notification API (`new Notification()` in the renderer) delegates to
// Chromium's libnotify_notification.cc which calls notify_notification_show()
// synchronously — blocking the main process for 100+ seconds when the D-Bus
// notification proxy is unresponsive.  This IPC channel uses Electron's own
// Notification class whose .show() is non-blocking.
ipcMain.handle(
  'notifications:show',
  async (
    _event,
    options: { title: string; body: string; silent?: boolean; timeoutMs?: number },
  ) => {
    const timeout = options.timeoutMs ?? 3000;
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => resolve(false), timeout);
      try {
        const notification = new Notification({
          title: options.title,
          body: options.body,
          silent: options.silent ?? true,
        });
        notification.on('show', () => {
          clearTimeout(timer);
          resolve(true);
        });
        notification.on('failed', () => {
          clearTimeout(timer);
          resolve(false);
        });
        notification.show();
      } catch {
        clearTimeout(timer);
        resolve(false);
      }
    });
  },
);

app.on('before-quit', (event) => {
  if (shutdownPromise) {
    // Shutdown already triggered (e.g. by signal handler) — let the quit
    // proceed naturally but chain app.exit as a safety net.
    shutdownPromise.finally(() => app.exit(0));
    return;
  }
  event.preventDefault();
  gracefulShutdown().finally(() => app.exit(0));
});

app.on('window-all-closed', () => {
  // On Linux/Windows, don't quit when window is closed (tray is active)
  // On macOS, standard behavior is to keep the app running in the dock
});
