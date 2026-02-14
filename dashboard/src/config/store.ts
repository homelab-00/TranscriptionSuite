/**
 * Client-side configuration store.
 * Uses electron-store in Electron, falls back to localStorage in browser dev mode.
 */

export interface ClientConfig {
  /** Server connection */
  server: {
    host: string;
    port: number;
    https: boolean;
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
 */
export async function getServerBaseUrl(): Promise<string> {
  const host = (await getConfig<string>('server.host')) ?? DEFAULT_CONFIG.server.host;
  const port = (await getConfig<number>('server.port')) ?? DEFAULT_CONFIG.server.port;
  const https = (await getConfig<boolean>('server.https')) ?? DEFAULT_CONFIG.server.https;
  const protocol = https ? 'https' : 'http';
  return `${protocol}://${host}:${port}`;
}

export { DEFAULT_CONFIG };
