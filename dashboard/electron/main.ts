import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { app, BrowserWindow, clipboard, ipcMain, shell, dialog } from 'electron';
import Store from 'electron-store';
import {
  dockerManager,
  type HfTokenDecision,
  type StartContainerOptions,
} from './dockerManager.js';
import { TrayManager, type TrayState } from './trayManager.js';
import { UpdateManager } from './updateManager.js';

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

// Ensure userData path uses PascalCase: ~/.config/TranscriptionSuite (not lowercase)
app.setPath('userData', path.join(app.getPath('appData'), 'TranscriptionSuite'));

const isDev = !app.isPackaged;
const CLIENT_LOG_DIR = 'logs';
const CLIENT_LOG_FILE = 'client-debug.log';
const STOP_SERVER_ON_QUIT_TIMEOUT_MS = 30_000;

function ensureClientLogFilePath(): string {
  const logDir = path.join(app.getPath('userData'), CLIENT_LOG_DIR);
  fs.mkdirSync(logDir, { recursive: true });
  const logFilePath = path.join(logDir, CLIENT_LOG_FILE);
  // Use atomic create-if-not-exists to avoid TOCTOU race between existsSync and writeFileSync
  try {
    fs.writeFileSync(logFilePath, '', { flag: 'wx' });
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e;
  }
  return logFilePath;
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

// ─── Persistent Config Store ────────────────────────────────────────────────
const store = new Store({
  name: 'dashboard-config',
  accessPropertiesByDotNotation: false,
  defaults: {
    'connection.localHost': 'localhost',
    'connection.remoteHost': '',
    'connection.useRemote': false,
    'connection.authToken': '',
    'connection.port': 8000,
    'connection.useHttps': false,
    'session.audioSource': 'mic',
    'session.micDevice': 'Default Microphone',
    'session.systemDevice': 'Default Output',
    'session.mainLanguage': 'Auto Detect',
    'session.liveLanguage': 'Auto Detect',
    'audio.gracePeriod': 0.5,
    'diarization.constrainSpeakers': false,
    'diarization.numSpeakers': 2,
    'notebook.autoAdd': true,
    'app.autoCopy': true,
    'app.showNotifications': true,
    'app.stopServerOnQuit': true,
    'app.startMinimized': false,
    'app.updateChecksEnabled': false,
    'app.updateCheckIntervalMode': '24h',
    'app.updateCheckCustomHours': 24,
    'ui.sidebarCollapsed': false,
    'server.host': 'localhost',
    'server.port': 8000,
    'server.https': false,
    'server.hfToken': '',
    'server.hfTokenDecision': 'unset',
    'server.containerExistsLastSeen': false,
    'updates.lastStatus': null,
    'updates.lastNotified': { appLatest: '', serverLatest: '' },
    'server.runtimeProfile': 'gpu',
  },
});

let mainWindow: BrowserWindow | null = null;

// ─── Tray Manager ───────────────────────────────────────────────────────────

const trayManager = new TrayManager(isDev, () => mainWindow);

// ─── Update Manager ─────────────────────────────────────────────────────────

const updateManager = new UpdateManager(store);

// Wire tray context-menu actions → IPC messages to the renderer
trayManager.setActions({
  startServer: async () => {
    try {
      const runtimeProfile = (store.get('server.runtimeProfile') as string) || 'gpu';
      const hfToken = ((store.get('server.hfToken') as string) || '').trim();
      const rawHfDecision = store.get('server.hfTokenDecision');
      const hfDecision: HfTokenDecision =
        rawHfDecision === 'provided' || rawHfDecision === 'skipped' || rawHfDecision === 'unset'
          ? rawHfDecision
          : hfToken
            ? 'provided'
            : 'unset';

      await dockerManager.startContainer({
        mode: 'local',
        runtimeProfile: runtimeProfile as 'gpu' | 'cpu',
        hfToken,
        hfTokenDecision: hfDecision,
      });
      trayManager.setMenuState({ serverRunning: true, isStandby: true });
    } catch (err) {
      console.error('Tray: failed to start server', err);
    }
  },
  stopServer: async () => {
    try {
      await dockerManager.stopContainer();
      trayManager.setMenuState({
        serverRunning: false,
        isRecording: false,
        isLive: false,
        isStandby: false,
      });
    } catch (err) {
      console.error('Tray: failed to stop server', err);
    }
  },
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
    ? path.join(__dirname, '../../build/assets/logo.png')
    : path.join(process.resourcesPath, 'logo.png');

  mainWindow = new BrowserWindow({
    width: 1530,
    height: 860,
    minWidth: 960,
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
    if (/^https?:\/\//i.test(url)) {
      void shell.openExternal(url);
      return { action: 'deny' };
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
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.removeMenu();

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ─── IPC Handlers ───────────────────────────────────────────────────────────

// Config: get/set client settings via electron-store
ipcMain.handle('config:get', async (_event, key: string) => {
  return store.get(key) ?? null;
});

ipcMain.handle('config:set', async (_event, key: string, value: unknown) => {
  store.set(key, value);
  // Reconfigure update manager when update-related settings change
  if (key.startsWith('app.updateCheck')) {
    updateManager.reconfigure();
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
  // TranscriptionSuite stores config in ~/.config/TranscriptionSuite
  const homeDir = app.getPath('home');
  const configDir = path.join(homeDir, '.config', 'TranscriptionSuite');
  return configDir;
});

ipcMain.handle('app:getClientLogPath', () => {
  return ensureClientLogFilePath();
});

ipcMain.handle('app:appendClientLogLine', async (_event, line: string) => {
  const logFilePath = ensureClientLogFilePath();
  const normalizedLine = String(line).replace(/\r?\n/g, ' ');
  await fs.promises.appendFile(logFilePath, `${normalizedLine}\n`, 'utf8');
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

// ─── Docker Management IPC ──────────────────────────────────────────────────

ipcMain.handle('docker:available', async () => {
  return dockerManager.dockerAvailable();
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

ipcMain.handle('docker:removeImage', async (_event, tag: string) => {
  return dockerManager.removeImage(tag);
});

ipcMain.handle('docker:getContainerStatus', async () => {
  return dockerManager.getContainerStatus();
});

ipcMain.handle('docker:startContainer', async (_event, options: StartContainerOptions) => {
  return dockerManager.startContainer(options);
});

ipcMain.handle('docker:stopContainer', async () => {
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

ipcMain.handle('docker:removeVolume', async (_event, name: string) => {
  return dockerManager.removeVolume(name);
});

ipcMain.handle('docker:readComposeEnvValue', async (_event, key: string) => {
  return dockerManager.readComposeEnvValue(key);
});

ipcMain.handle('docker:volumeExists', async (_event, name: string) => {
  return dockerManager.volumeExists(name);
});

ipcMain.handle('docker:getLogs', async (_event, tail?: number) => {
  return dockerManager.getLogs(tail);
});

// ─── Docker Log Streaming IPC ───────────────────────────────────────────────

ipcMain.handle('docker:startLogStream', async (_event, tail?: number) => {
  dockerManager.startLogStream((line: string) => {
    mainWindow?.webContents.send('docker:logLine', line);
  }, tail);
});

ipcMain.handle('docker:stopLogStream', async () => {
  dockerManager.stopLogStream();
});

// ─── Audio IPC ──────────────────────────────────────────────────────────────

// desktopCapturer was removed in Electron 35+; use session-based display media handler instead.
// For now, provide a stub that returns empty sources. System audio capture uses
// navigator.mediaDevices.getDisplayMedia() in the renderer directly.
ipcMain.handle('audio:getDesktopSources', async () => {
  try {
    // Try dynamic import in case a future Electron re-exports it
    const { desktopCapturer } = await import('electron');
    if (desktopCapturer) {
      const sources = await desktopCapturer.getSources({
        types: ['window', 'screen'],
        thumbnailSize: { width: 150, height: 150 },
      });
      return sources.map((source: any) => ({
        id: source.id,
        name: source.name,
        thumbnail: source.thumbnail.toDataURL(),
      }));
    }
  } catch {
    // desktopCapturer not available in this Electron version
  }
  return [];
});

// ─── Clipboard IPC ──────────────────────────────────────────────────────────

ipcMain.handle('clipboard:writeText', (_event, text: string) => {
  clipboard.writeText(text);
});

// ─── Update Check IPC ───────────────────────────────────────────────────────

ipcMain.handle('updates:getStatus', async () => {
  return updateManager.getStatus();
});

ipcMain.handle('updates:checkNow', async () => {
  return updateManager.check();
});

// ─── Tray IPC Handlers ─────────────────────────────────────────────────────

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
    },
  ) => {
    trayManager.setMenuState(menuState);
  },
);

// ─── App Lifecycle ──────────────────────────────────────────────────────────

let isQuitting = false;
let shutdownPromise: Promise<void> | null = null;

/**
 * Persistent shutdown logger — writes to both console and a log file so that
 * shutdown diagnostics survive Wayland stdout teardown.
 */
function shutdownLog(message: string): void {
  const line = `${new Date().toISOString()} ${message}`;
  console.log(line);
  try {
    const logDir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, 'shutdown.log'), line + '\n');
  } catch {
    // Best-effort — don't let logging failures block shutdown
  }
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

    trayManager.destroy();
    updateManager.destroy();
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

app.whenReady().then(() => {
  trayManager.create();
  updateManager.start();
  createWindow();

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
