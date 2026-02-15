/**
 * Client-side configuration store.
 * Uses electron-store in Electron, falls back to localStorage in browser dev mode.
 *
 * Keys use dot-notation to match electron-store's nested path support.
 * The canonical key list lives in electron/main.ts defaults.
 */

export interface ClientConfig {
  /** Server connection */
  server: {
    host: string;
    port: number;
    https: boolean;
  };
  /** Connection settings (SettingsModal Client tab) */
  connection: {
    localHost: string;
    remoteHost: string;
    useRemote: boolean;
    authToken: string;
    port: number;
    useHttps: boolean;
  };
  /** Audio capture settings */
  audio: {
    gracePeriod: number;
  };
  /** Diarization settings */
  diarization: {
    constrainSpeakers: boolean;
    numSpeakers: number;
  };
  /** Notebook settings */
  notebook: {
    autoAdd: boolean;
  };
  /** App-level settings */
  app: {
    autoCopy: boolean;
    showNotifications: boolean;
    stopServerOnQuit: boolean;
    startMinimized: boolean;
    updateChecksEnabled: boolean;
    updateCheckIntervalMode: '24h' | '7d' | '28d' | 'custom';
    updateCheckCustomHours: number;
  };
  /** UI preferences */
  ui: {
    sidebarCollapsed: boolean;
  };
}

const DEFAULT_CONFIG: ClientConfig = {
  server: {
    host: 'localhost',
    port: 8000,
    https: false,
  },
  connection: {
    localHost: 'localhost',
    remoteHost: '',
    useRemote: false,
    authToken: '',
    port: 8000,
    useHttps: false,
  },
  audio: {
    gracePeriod: 0.5,
  },
  diarization: {
    constrainSpeakers: false,
    numSpeakers: 2,
  },
  notebook: {
    autoAdd: true,
  },
  app: {
    autoCopy: false,
    showNotifications: true,
    stopServerOnQuit: true,
    startMinimized: false,
    updateChecksEnabled: false,
    updateCheckIntervalMode: '24h',
    updateCheckCustomHours: 24,
  },
  ui: {
    sidebarCollapsed: false,
  },
};

/**
 * Check if we're running inside Electron.
 */
function isElectron(): boolean {
  return typeof window !== 'undefined' && 'electronAPI' in window;
}

/**
 * Get a config value by dot-notation key.
 */
export async function getConfig<T = unknown>(key: string): Promise<T | undefined> {
  if (isElectron()) {
    return (window as any).electronAPI.config.get(key) as Promise<T>;
  }
  // Browser fallback: localStorage
  const stored = localStorage.getItem(`ts-config:${key}`);
  if (stored === null) return undefined;
  try {
    return JSON.parse(stored) as T;
  } catch {
    return stored as unknown as T;
  }
}

/**
 * Set a config value by dot-notation key.
 */
export async function setConfig(key: string, value: unknown): Promise<void> {
  if (isElectron()) {
    return (window as any).electronAPI.config.set(key, value);
  }
  localStorage.setItem(`ts-config:${key}`, JSON.stringify(value));
}

/**
 * Get the full server base URL from config.
 * Prefers `connection.*` keys (written by SettingsModal), falls back to `server.*`.
 */
export async function getServerBaseUrl(): Promise<string> {
  const useRemote = (await getConfig<boolean>('connection.useRemote')) ?? false;
  const host = useRemote
    ? ((await getConfig<string>('connection.remoteHost')) || DEFAULT_CONFIG.connection.localHost)
    : ((await getConfig<string>('connection.localHost')) ?? (await getConfig<string>('server.host')) ?? DEFAULT_CONFIG.server.host);
  const port = (await getConfig<number>('connection.port')) ?? (await getConfig<number>('server.port')) ?? DEFAULT_CONFIG.server.port;
  const https = (await getConfig<boolean>('connection.useHttps')) ?? (await getConfig<boolean>('server.https')) ?? DEFAULT_CONFIG.server.https;
  const protocol = https ? 'https' : 'http';
  return `${protocol}://${host}:${port}`;
}

/**
 * Get the stored auth token from config.
 */
export async function getAuthToken(): Promise<string | null> {
  const token = await getConfig<string>('connection.authToken');
  return token || null;
}

export { DEFAULT_CONFIG };
