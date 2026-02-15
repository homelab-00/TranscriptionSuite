import { contextBridge, ipcRenderer } from 'electron';

/**
 * Preload script — exposes a safe IPC bridge to the renderer process.
 * The renderer accesses these via `window.electronAPI`.
 */

export interface ElectronAPI {
  config: {
    get: (key: string) => Promise<unknown>;
    set: (key: string, value: unknown) => Promise<void>;
    getAll: () => Promise<Record<string, unknown>>;
  };
  app: {
    getVersion: () => Promise<string>;
    getPlatform: () => string;
  };
  docker: {
    available: () => Promise<boolean>;
    listImages: () => Promise<Array<{ tag: string; fullName: string; size: string; created: string; id: string }>>;
    pullImage: (tag: string) => Promise<string>;
    removeImage: (tag: string) => Promise<string>;
    getContainerStatus: () => Promise<{ exists: boolean; running: boolean; status: string; health?: string; startedAt?: string }>;
    startContainer: (mode: 'local' | 'remote', env?: Record<string, string>) => Promise<string>;
    stopContainer: () => Promise<string>;
    removeContainer: () => Promise<string>;
    getVolumes: () => Promise<Array<{ name: string; label: string; driver: string; mountpoint: string; size?: string }>>;
    removeVolume: (name: string) => Promise<string>;
    getLogs: (tail?: number) => Promise<string[]>;
  };
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
  },
  docker: {
    available: () => ipcRenderer.invoke('docker:available'),
    listImages: () => ipcRenderer.invoke('docker:listImages'),
    pullImage: (tag: string) => ipcRenderer.invoke('docker:pullImage', tag),
    removeImage: (tag: string) => ipcRenderer.invoke('docker:removeImage', tag),
    getContainerStatus: () => ipcRenderer.invoke('docker:getContainerStatus'),
    startContainer: (mode: 'local' | 'remote', env?: Record<string, string>) => ipcRenderer.invoke('docker:startContainer', mode, env),
    stopContainer: () => ipcRenderer.invoke('docker:stopContainer'),
    removeContainer: () => ipcRenderer.invoke('docker:removeContainer'),
    getVolumes: () => ipcRenderer.invoke('docker:getVolumes'),
    removeVolume: (name: string) => ipcRenderer.invoke('docker:removeVolume', name),
    getLogs: (tail?: number) => ipcRenderer.invoke('docker:getLogs', tail),
  },
} satisfies ElectronAPI);
