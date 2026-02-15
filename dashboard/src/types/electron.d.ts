/**
 * Type declarations for APIs exposed by Electron preload script.
 */

type TrayState =
  | 'idle' | 'active' | 'connecting' | 'recording' | 'processing'
  | 'live-listening' | 'live-processing' | 'muted' | 'complete'
  | 'error' | 'disconnected';

type RuntimeProfile = 'gpu' | 'cpu';

interface StartContainerOptions {
  mode: 'local' | 'remote';
  runtimeProfile: RuntimeProfile;
  tlsEnv?: Record<string, string>;
}

interface TrayMenuState {
  serverRunning?: boolean;
  isRecording?: boolean;
  isLive?: boolean;
  isMuted?: boolean;
}

interface ElectronAPI {
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

interface ComponentUpdateStatus {
  current: string | null;
  latest: string | null;
  updateAvailable: boolean;
  error: string | null;
}

interface UpdateStatus {
  lastChecked: string;
  app: ComponentUpdateStatus;
  server: ComponentUpdateStatus;
}

interface Window {
  electronAPI?: ElectronAPI;
}
