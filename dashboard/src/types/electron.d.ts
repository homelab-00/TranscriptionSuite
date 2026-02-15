/**
 * Type declarations for APIs exposed by Electron preload script.
 */

interface ElectronAPI {
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
  tray: {
    setTooltip: (tooltip: string) => Promise<void>;
  };
  audio: {
    getDesktopSources: () => Promise<Array<{ id: string; name: string; thumbnail: string }>>;
  };
}

interface Window {
  electronAPI?: ElectronAPI;
}
