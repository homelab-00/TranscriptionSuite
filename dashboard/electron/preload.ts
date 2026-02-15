import { contextBridge, ipcRenderer, desktopCapturer } from 'electron';

/**
 * Preload script — exposes a safe IPC bridge to the renderer process.
 * The renderer accesses these via `window.electronAPI`.
 */

export type TrayState =
  | 'idle' | 'active' | 'connecting' | 'recording' | 'processing'
  | 'live-listening' | 'live-processing' | 'muted' | 'complete'
  | 'error' | 'disconnected';

export interface TrayMenuState {
  serverRunning?: boolean;
  isRecording?: boolean;
  isLive?: boolean;
  isMuted?: boolean;
}

export type RuntimeProfile = 'gpu' | 'cpu';

export interface StartContainerOptions {
  mode: 'local' | 'remote';
  runtimeProfile: RuntimeProfile;
  tlsEnv?: Record<string, string>;
}

export interface ElectronAPI {
  config: {
    get: (key: string) => Promise<unknown>;
    set: (key: string, value: unknown) => Promise<void>;
    getAll: () => Promise<Record<string, unknown>>;
  };
  app: {
    getVersion: () => Promise<string>;
    getPlatform: () => string;
    openExternal: (url: string) => Promise<void>;
  };
  docker: {
    available: () => Promise<boolean>;
    listImages: () => Promise<Array<{ tag: string; fullName: string; size: string; created: string; id: string }>>;
    pullImage: (tag: string) => Promise<string>;
    removeImage: (tag: string) => Promise<string>;
    getContainerStatus: () => Promise<{ exists: boolean; running: boolean; status: string; health?: string; startedAt?: string }>;
    startContainer: (options: StartContainerOptions) => Promise<string>;
    stopContainer: () => Promise<string>;
    removeContainer: () => Promise<string>;
    getVolumes: () => Promise<Array<{ name: string; label: string; driver: string; mountpoint: string; size?: string }>>;
    removeVolume: (name: string) => Promise<string>;
    getLogs: (tail?: number) => Promise<string[]>;
    startLogStream: (tail?: number) => Promise<void>;
    stopLogStream: () => Promise<void>;
    onLogLine: (callback: (line: string) => void) => () => void;
  };
  tray: {
    setTooltip: (tooltip: string) => Promise<void>;
    setState: (state: TrayState) => Promise<void>;
    setMenuState: (menuState: TrayMenuState) => Promise<void>;
    onAction: (callback: (action: string) => void) => () => void;
  };
  audio: {
    getDesktopSources: () => Promise<Array<{ id: string; name: string; thumbnail: string }>>;
  };
  updates: {
    getStatus: () => Promise<UpdateStatus | null>;
    checkNow: () => Promise<UpdateStatus>;
  };
}

export interface ComponentUpdateStatus {
  current: string | null;
  latest: string | null;
  updateAvailable: boolean;
  error: string | null;
}

export interface UpdateStatus {
  lastChecked: string;
  app: ComponentUpdateStatus;
  server: ComponentUpdateStatus;
}

contextBridge.exposeInMainWorld('electronAPI', {
  config: {
    get: (key: string) => ipcRenderer.invoke('config:get', key),
    set: (key: string, value: unknown) => ipcRenderer.invoke('config:set', key, value),
    getAll: () => ipcRenderer.invoke('config:getAll'),
  },
  app: {
    getVersion: () => ipcRenderer.invoke('app:getVersion'),
    getPlatform: () => process.platform,
    openExternal: (url: string) => ipcRenderer.invoke('app:openExternal', url),
  },
  docker: {
    available: () => ipcRenderer.invoke('docker:available'),
    listImages: () => ipcRenderer.invoke('docker:listImages'),
    pullImage: (tag: string) => ipcRenderer.invoke('docker:pullImage', tag),
    removeImage: (tag: string) => ipcRenderer.invoke('docker:removeImage', tag),
    getContainerStatus: () => ipcRenderer.invoke('docker:getContainerStatus'),
    startContainer: (options: StartContainerOptions) => ipcRenderer.invoke('docker:startContainer', options),
    stopContainer: () => ipcRenderer.invoke('docker:stopContainer'),
    removeContainer: () => ipcRenderer.invoke('docker:removeContainer'),
    getVolumes: () => ipcRenderer.invoke('docker:getVolumes'),
    removeVolume: (name: string) => ipcRenderer.invoke('docker:removeVolume', name),
    getLogs: (tail?: number) => ipcRenderer.invoke('docker:getLogs', tail),
    startLogStream: (tail?: number) => ipcRenderer.invoke('docker:startLogStream', tail),
    stopLogStream: () => ipcRenderer.invoke('docker:stopLogStream'),
    onLogLine: (callback: (line: string) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
      ipcRenderer.on('docker:logLine', handler);
      return () => ipcRenderer.removeListener('docker:logLine', handler);
    },
  },
  tray: {
    setTooltip: (tooltip: string) => ipcRenderer.invoke('tray:setTooltip', tooltip),
    setState: (state: TrayState) => ipcRenderer.invoke('tray:setState', state),
    setMenuState: (menuState: TrayMenuState) => ipcRenderer.invoke('tray:setMenuState', menuState),
    onAction: (callback: (action: string) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, action: string) => callback(action);
      ipcRenderer.on('tray:action', handler);
      return () => ipcRenderer.removeListener('tray:action', handler);
    },
  },
  audio: {
    getDesktopSources: async () => {
      const sources = await desktopCapturer.getSources({
        types: ['window', 'screen'],
        thumbnailSize: { width: 150, height: 150 },
      });
      return sources.map((source) => ({
        id: source.id,
        name: source.name,
        thumbnail: source.thumbnail.toDataURL(),
      }));
    },
  },
  updates: {
    getStatus: () => ipcRenderer.invoke('updates:getStatus'),
    checkNow: () => ipcRenderer.invoke('updates:checkNow'),
  },
} satisfies ElectronAPI);
