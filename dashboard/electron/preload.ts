import { contextBridge, ipcRenderer } from 'electron';

/**
 * Preload script — exposes a safe IPC bridge to the renderer process.
 * The renderer accesses these via `window.electronAPI`.
 */

export type TrayState =
  | 'idle'
  | 'recording'
  | 'processing'
  | 'complete'
  | 'live-active'
  | 'recording-muted'
  | 'live-muted'
  | 'uploading'
  | 'models-unloaded'
  | 'error'
  | 'disconnected';

export interface TrayMenuState {
  serverRunning?: boolean;
  isRecording?: boolean;
  isLive?: boolean;
  isMuted?: boolean;
  modelsLoaded?: boolean;
  isLocalConnection?: boolean;
  canCancel?: boolean;
  isStandby?: boolean;
}

export type RuntimeProfile = 'gpu' | 'cpu';
export type HfTokenDecision = 'unset' | 'provided' | 'skipped';
export type ClientLogType = 'info' | 'success' | 'error' | 'warning';

export interface ClientLogLine {
  timestamp: string;
  source: string;
  message: string;
  type: ClientLogType;
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

export interface ElectronAPI {
  config: {
    get: (key: string) => Promise<unknown>;
    set: (key: string, value: unknown) => Promise<void>;
    getAll: () => Promise<Record<string, unknown>>;
  };
  app: {
    getVersion: () => Promise<string>;
    getPlatform: () => string;
    getSessionType: () => string;
    openExternal: (url: string) => Promise<void>;
    openPath: (filePath: string) => Promise<string>;
    getConfigDir: () => Promise<string>;
    ensureServerConfig: () => Promise<string>;
    removeConfigAndCache: () => Promise<void>;
    getClientLogPath: () => Promise<string>;
    appendClientLogLine: (line: string) => Promise<void>;
    onClientLogLine: (callback: (entry: ClientLogLine) => void) => () => void;
    readLocalFile: (
      filePath: string,
    ) => Promise<{ name: string; buffer: ArrayBuffer; mimeType: string }>;
  };
  docker: {
    available: () => Promise<boolean>;
    checkGpu: () => Promise<{ gpu: boolean; toolkit: boolean }>;
    listImages: () => Promise<
      Array<{ tag: string; fullName: string; size: string; created: string; id: string }>
    >;
    pullImage: (tag: string) => Promise<string>;
    cancelPull: () => Promise<boolean>;
    isPulling: () => Promise<boolean>;
    removeImage: (tag: string) => Promise<string>;
    getContainerStatus: () => Promise<{
      exists: boolean;
      running: boolean;
      status: string;
      health?: string;
      startedAt?: string;
    }>;
    startContainer: (options: StartContainerOptions) => Promise<string>;
    stopContainer: () => Promise<string>;
    removeContainer: () => Promise<string>;
    getVolumes: () => Promise<
      Array<{ name: string; label: string; driver: string; mountpoint: string; size?: string }>
    >;
    checkModelsCached: (
      modelIds: string[],
    ) => Promise<Record<string, { exists: boolean; size?: string }>>;
    removeModelCache: (modelId: string) => Promise<void>;
    downloadModelToCache: (modelId: string) => Promise<void>;
    removeVolume: (name: string) => Promise<string>;
    readComposeEnvValue: (key: string) => Promise<string | null>;
    volumeExists: (name: string) => Promise<boolean>;
    readOptionalDependencyBootstrapStatus: () => Promise<{
      source: 'runtime-volume-bootstrap-status';
      whisper?: { available: boolean; reason?: string };
      nemo?: { available: boolean; reason?: string };
      vibevoiceAsr?: { available: boolean; reason?: string };
    } | null>;
    getLogs: (tail?: number) => Promise<string[]>;
    startLogStream: (tail?: number) => Promise<void>;
    stopLogStream: () => Promise<void>;
    onLogLine: (callback: (line: string) => void) => () => void;
  };
  tray: {
    setTooltip: (tooltip: string) => Promise<void>;
    setState: (state: TrayState) => Promise<void>;
    setMenuState: (menuState: TrayMenuState) => Promise<void>;
    onAction: (callback: (action: string, ...args: any[]) => void) => () => void;
  };
  audio: {
    getDesktopSources: () => Promise<Array<{ id: string; name: string; thumbnail: string }>>;
  };
  updates: {
    getStatus: () => Promise<UpdateStatus | null>;
    checkNow: () => Promise<UpdateStatus>;
  };
  clipboard: {
    writeText: (text: string) => Promise<void>;
    pasteAtCursor: (text: string) => Promise<void>;
  };
  shortcuts: {
    getPortalBindings: () => Promise<Array<{ id: string; trigger: string }> | null>;
    rebind: () => Promise<void>;
    isWaylandPortal: () => Promise<boolean>;
    onPortalChanged: (
      callback: (bindings: Array<{ id: string; trigger: string }>) => void,
    ) => () => void;
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
    getSessionType: () =>
      process.env.XDG_SESSION_TYPE ?? (process.env.WAYLAND_DISPLAY ? 'wayland' : 'x11'),
    openExternal: (url: string) => ipcRenderer.invoke('app:openExternal', url),
    openPath: (filePath: string) => ipcRenderer.invoke('app:openPath', filePath),
    getConfigDir: () => ipcRenderer.invoke('app:getConfigDir'),
    ensureServerConfig: () => ipcRenderer.invoke('app:ensureServerConfig') as Promise<string>,
    removeConfigAndCache: () => ipcRenderer.invoke('app:removeConfigAndCache'),
    getClientLogPath: () => ipcRenderer.invoke('app:getClientLogPath'),
    appendClientLogLine: (line: string) => ipcRenderer.invoke('app:appendClientLogLine', line),
    onClientLogLine: (callback: (entry: ClientLogLine) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, entry: ClientLogLine) => callback(entry);
      ipcRenderer.on('app:clientLogLine', handler);
      return () => ipcRenderer.removeListener('app:clientLogLine', handler);
    },
    readLocalFile: (filePath: string) =>
      ipcRenderer.invoke('app:readLocalFile', filePath) as Promise<{
        name: string;
        buffer: ArrayBuffer;
        mimeType: string;
      }>,
  },
  docker: {
    available: () => ipcRenderer.invoke('docker:available'),
    checkGpu: () => ipcRenderer.invoke('docker:checkGpu'),
    listImages: () => ipcRenderer.invoke('docker:listImages'),
    pullImage: (tag: string) => ipcRenderer.invoke('docker:pullImage', tag),
    cancelPull: () => ipcRenderer.invoke('docker:cancelPull'),
    isPulling: () => ipcRenderer.invoke('docker:isPulling'),
    removeImage: (tag: string) => ipcRenderer.invoke('docker:removeImage', tag),
    getContainerStatus: () => ipcRenderer.invoke('docker:getContainerStatus'),
    startContainer: (options: StartContainerOptions) =>
      ipcRenderer.invoke('docker:startContainer', options),
    stopContainer: () => ipcRenderer.invoke('docker:stopContainer'),
    removeContainer: () => ipcRenderer.invoke('docker:removeContainer'),
    getVolumes: () => ipcRenderer.invoke('docker:getVolumes'),
    checkModelsCached: (modelIds: string[]) =>
      ipcRenderer.invoke('docker:checkModelsCached', modelIds) as Promise<
        Record<string, { exists: boolean; size?: string }>
      >,
    removeModelCache: (modelId: string) =>
      ipcRenderer.invoke('docker:removeModelCache', modelId) as Promise<void>,
    downloadModelToCache: (modelId: string) =>
      ipcRenderer.invoke('docker:downloadModelToCache', modelId) as Promise<void>,
    removeVolume: (name: string) => ipcRenderer.invoke('docker:removeVolume', name),
    readComposeEnvValue: (key: string) =>
      ipcRenderer.invoke('docker:readComposeEnvValue', key) as Promise<string | null>,
    volumeExists: (name: string) =>
      ipcRenderer.invoke('docker:volumeExists', name) as Promise<boolean>,
    readOptionalDependencyBootstrapStatus: () =>
      ipcRenderer.invoke('docker:readOptionalDependencyBootstrapStatus') as Promise<{
        source: 'runtime-volume-bootstrap-status';
        whisper?: { available: boolean; reason?: string };
        nemo?: { available: boolean; reason?: string };
        vibevoiceAsr?: { available: boolean; reason?: string };
      } | null>,
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
    onAction: (callback: (action: string, ...args: any[]) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, action: string, ...args: any[]) =>
        callback(action, ...args);
      ipcRenderer.on('tray:action', handler);
      return () => ipcRenderer.removeListener('tray:action', handler);
    },
  },
  audio: {
    getDesktopSources: async () => {
      return ipcRenderer.invoke('audio:getDesktopSources');
    },
  },
  updates: {
    getStatus: () => ipcRenderer.invoke('updates:getStatus'),
    checkNow: () => ipcRenderer.invoke('updates:checkNow'),
  },
  clipboard: {
    writeText: (text: string) => ipcRenderer.invoke('clipboard:writeText', text),
    pasteAtCursor: (text: string) => ipcRenderer.invoke('clipboard:pasteAtCursor', text),
  },
  shortcuts: {
    getPortalBindings: () => ipcRenderer.invoke('shortcuts:getPortalBindings'),
    rebind: () => ipcRenderer.invoke('shortcuts:rebind'),
    isWaylandPortal: () => ipcRenderer.invoke('shortcuts:isWaylandPortal'),
    onPortalChanged: (callback: (bindings: Array<{ id: string; trigger: string }>) => void) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        bindings: Array<{ id: string; trigger: string }>,
      ) => callback(bindings);
      ipcRenderer.on('shortcuts:portalChanged', handler);
      return () => ipcRenderer.removeListener('shortcuts:portalChanged', handler);
    },
  },
} satisfies ElectronAPI);
