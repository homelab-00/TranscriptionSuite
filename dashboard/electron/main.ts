import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import Store from 'electron-store';
import { dockerManager } from './dockerManager.js';
import { TrayManager, type TrayState } from './trayManager.js';
import { UpdateManager } from './updateManager.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const isDev = !app.isPackaged;

// ─── Persistent Config Store ────────────────────────────────────────────────
const store = new Store({
  name: 'dashboard-config',
  defaults: {
    'connection.localHost': 'localhost',
    'connection.remoteHost': '',
    'connection.useRemote': false,
    'connection.authToken': '',
    'connection.port': 8000,
    'connection.useHttps': false,
    'audio.gracePeriod': 0.5,
    'diarization.constrainSpeakers': false,
    'diarization.numSpeakers': 2,
    'notebook.autoAdd': true,
    'app.autoCopy': false,
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
    'updates.lastStatus': null,
    'updates.lastNotified': { appLatest: '', serverLatest: '' },
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
      await dockerManager.startContainer('local');
      trayManager.setMenuState({ serverRunning: true });
    } catch (err) {
      console.error('Tray: failed to start server', err);
    }
  },
  stopServer: async () => {
    try {
      await dockerManager.stopContainer();
      trayManager.setMenuState({ serverRunning: false, isRecording: false, isLive: false });
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
  toggleMute: () => {
    mainWindow?.webContents.send('tray:action', 'toggle-mute');
  },
});

// ─── Window Creation ────────────────────────────────────────────────────────

function createWindow(): void {
  const startMinimized = store.get('app.startMinimized') as boolean;

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: !startMinimized,
    frame: true,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

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
  return app.getVersion();
});

// ─── Docker Management IPC ──────────────────────────────────────────────────

ipcMain.handle('docker:available', async () => {
  return dockerManager.dockerAvailable();
});

ipcMain.handle('docker:listImages', async () => {
  return dockerManager.listImages();
});

ipcMain.handle('docker:pullImage', async (_event, tag: string) => {
  return dockerManager.pullImage(tag);
});

ipcMain.handle('docker:removeImage', async (_event, tag: string) => {
  return dockerManager.removeImage(tag);
});

ipcMain.handle('docker:getContainerStatus', async () => {
  return dockerManager.getContainerStatus();
});

ipcMain.handle('docker:startContainer', async (_event, mode: 'local' | 'remote', env?: Record<string, string>) => {
  return dockerManager.startContainer(mode, env);
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

ipcMain.handle('docker:removeVolume', async (_event, name: string) => {
  return dockerManager.removeVolume(name);
});

ipcMain.handle('docker:getLogs', async (_event, tail?: number) => {
  return dockerManager.getLogs(tail);
});

// ─── Docker Log Streaming IPC ───────────────────────────────────────────────

ipcMain.handle('docker:startLogStream', async (_event, tail?: number) => {
  dockerManager.startLogStream((line: string) => {
    mainWindow?.webContents.send('docker:logLine', line);
  }, tail ?? 100);
});

ipcMain.handle('docker:stopLogStream', async () => {
  dockerManager.stopLogStream();
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

ipcMain.handle('tray:setMenuState', async (_event, menuState: { serverRunning?: boolean; isRecording?: boolean; isLive?: boolean; isMuted?: boolean }) => {
  trayManager.setMenuState(menuState);
});

// ─── App Lifecycle ──────────────────────────────────────────────────────────

let isQuitting = false;

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
      }
    });
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', async (event) => {
  if (isQuitting) return; // Already in quit sequence
  isQuitting = true;

  const shouldStopServer = store.get('app.stopServerOnQuit') as boolean;
  if (shouldStopServer) {
    event.preventDefault();
    try {
      console.log('Stopping server on quit…');
      await dockerManager.stopContainer();
    } catch (err) {
      console.error('Failed to stop server on quit:', err);
    } finally {
      trayManager.destroy();
      updateManager.destroy();
      app.quit();
    }
  } else {
    trayManager.destroy();
    updateManager.destroy();
  }
});

app.on('window-all-closed', () => {
  // On Linux/Windows, don't quit when window is closed (tray is active)
});
