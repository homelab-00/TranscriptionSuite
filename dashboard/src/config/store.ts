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
    lanHost: string;
    remoteProfile: 'tailscale' | 'lan';
    useRemote: boolean;
    authToken: string;
    port: number;
    useHttps: boolean;
  };
  /** Audio capture settings */
  audio: {
    gracePeriod: number;
  };
  /** Session view UI selections */
  session: {
    audioSource: 'mic' | 'system';
    micDevice: string;
    systemDevice: string;
    mainLanguage: string;
    liveLanguage: string;
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
    modelSelectionOnboardingCompleted: boolean;
    pasteAtCursor: boolean;
    cumulativeUsageMs: number;
    starPopupShown: boolean;
  };
  /** Global keyboard shortcuts (Electron accelerator strings) */
  shortcuts: {
    startRecording: string;
    stopTranscribe: string;
  };
  /** Output formatting */
  output: {
    hideTimestamps: boolean;
  };
  /** UI preferences */
  ui: {
    sidebarCollapsed: boolean;
    /**
     * Issue #87 — when false, a global CSS override on `<html
     * data-blur-effects="off">` neutralizes every `backdrop-filter` rule
     * (Tailwind utilities, inline styles, custom CSS). Default true.
     */
    blurEffectsEnabled: boolean;
  };
}

/** Default server port — single source of truth for all client-side defaults. */
export const DEFAULT_SERVER_PORT = 9786;

const DEFAULT_CONFIG: ClientConfig = {
  server: {
    host: 'localhost',
    port: DEFAULT_SERVER_PORT,
    https: false,
  },
  connection: {
    localHost: 'localhost',
    remoteHost: '',
    lanHost: '',
    remoteProfile: 'tailscale',
    useRemote: false,
    authToken: '',
    port: DEFAULT_SERVER_PORT,
    useHttps: false,
  },
  audio: {
    gracePeriod: 1.0,
  },
  session: {
    audioSource: 'mic',
    micDevice: 'Default Microphone',
    systemDevice: 'Default Output',
    mainLanguage: 'Auto Detect',
    liveLanguage: 'Auto Detect',
  },
  diarization: {
    constrainSpeakers: true,
    numSpeakers: 2,
  },
  notebook: {
    autoAdd: false,
  },
  app: {
    autoCopy: true,
    showNotifications: true,
    stopServerOnQuit: true,
    startMinimized: false,
    updateChecksEnabled: false,
    updateCheckIntervalMode: '24h',
    updateCheckCustomHours: 24,
    modelSelectionOnboardingCompleted: false,
    pasteAtCursor: false,
    cumulativeUsageMs: 0,
    starPopupShown: false,
  },
  shortcuts: {
    startRecording: 'Alt+Ctrl+Z',
    stopTranscribe: 'Alt+Ctrl+X',
  },
  output: {
    hideTimestamps: false,
  },
  ui: {
    sidebarCollapsed: false,
    blurEffectsEnabled: true,
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
  const remoteProfile =
    (await getConfig<'tailscale' | 'lan'>('connection.remoteProfile')) ??
    DEFAULT_CONFIG.connection.remoteProfile;
  const remoteHost = ((await getConfig<string>('connection.remoteHost')) ?? '').trim();
  const lanHost = ((await getConfig<string>('connection.lanHost')) ?? '').trim();
  const localHost =
    (await getConfig<string>('connection.localHost')) ??
    (await getConfig<string>('server.host')) ??
    DEFAULT_CONFIG.server.host;

  // Parity invariant with electron/appState.ts::getServerUrl — NO silent
  // fallback to 'localhost' when useRemote=true with a blank active-profile
  // host. Callers of network-probe paths (apiClient.checkConnection) must
  // gate on isServerUrlConfigured() first; a malformed `http://:<port>`
  // here is the deliberate loud-fail shape that prevents stealth-localhost
  // probes on pure-remote users.
  // Spec: _bmad-output/implementation-artifacts/spec-in-app-update-remote-host-validation-renderer.md
  const host = useRemote ? (remoteProfile === 'lan' ? lanHost : remoteHost) : localHost;
  const port =
    (await getConfig<number>('connection.port')) ??
    (await getConfig<number>('server.port')) ??
    DEFAULT_CONFIG.server.port;
  const https =
    (await getConfig<boolean>('connection.useHttps')) ??
    (await getConfig<boolean>('server.https')) ??
    DEFAULT_CONFIG.server.https;
  const protocol = https ? 'https' : 'http';
  return `${protocol}://${host}:${port}`;
}

/**
 * Returns false when useRemote=true AND the host for the active remoteProfile
 * is blank after trim(); true for local mode and any configured remote.
 *
 * Renderer-side mirror of `electron/appState.ts::isServerUrlConfigured`. The
 * install path short-circuits via the main-process predicate; API probe paths
 * (apiClient.checkConnection) short-circuit via this one, returning a stable
 * `'remote-host-not-configured'` error instead of probing the malformed
 * `http://:<port>` URL that `getServerBaseUrl` now emits for blank-remote.
 */
export async function isServerUrlConfigured(): Promise<boolean> {
  const useRemote = (await getConfig<boolean>('connection.useRemote')) ?? false;
  if (!useRemote) return true;
  const profile =
    (await getConfig<'tailscale' | 'lan'>('connection.remoteProfile')) ??
    DEFAULT_CONFIG.connection.remoteProfile;
  const host = (
    profile === 'lan'
      ? ((await getConfig<string>('connection.lanHost')) ?? '')
      : ((await getConfig<string>('connection.remoteHost')) ?? '')
  ).trim();
  return host.length > 0;
}

/**
 * Get the stored auth token from config.
 */
export async function getAuthToken(): Promise<string | null> {
  const token = await getConfig<string>('connection.authToken');
  return token || null;
}

export { DEFAULT_CONFIG };
