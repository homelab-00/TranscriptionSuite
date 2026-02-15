import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import Store from 'electron-store';
import { dockerManager } from './dockerManager.js';

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
    'server.host': 'localhost',
    'server.port': 8000,
    'server.https': false,
  },
});

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
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
    // In dev mode, load from Vite dev server
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    // In production, load the built index.html
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// --- IPC Handlers ---

// Config: get/set client settings via electron-store
ipcMain.handle('config:get', async (_event, key: string) => {
  return store.get(key) ?? null;
});

ipcMain.handle('config:set', async (_event, key: string, value: unknown) => {
  store.set(key, value);
});

ipcMain.handle('config:getAll', async () => {
  return store.store; // returns the full store object
});

// App metadata
ipcMain.handle('app:getVersion', () => {
  return app.getVersion();
});

// --- Docker Management IPC ---

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

// --- App Lifecycle ---

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    // macOS: re-create window when dock icon is clicked and no windows are open
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  app.quit();
});
