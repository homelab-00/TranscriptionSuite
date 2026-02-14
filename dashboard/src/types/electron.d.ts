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
}

interface Window {
  electronAPI?: ElectronAPI;
}
