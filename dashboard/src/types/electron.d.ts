/**
 * Type declarations for APIs exposed by Electron preload script.
 */

type TrayState =
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

// Keep in sync with src/types/runtime.ts (canonical) and electron/preload.ts
type RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'metal';
type HfTokenDecision = 'unset' | 'provided' | 'skipped';
type ClientLogType = 'info' | 'success' | 'error' | 'warning';

interface ClientLogLine {
  timestamp: string;
  source: string;
  message: string;
  type: ClientLogType;
}

interface StartContainerOptions {
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
  whispercppModel?: string;
}

interface TrayMenuState {
  serverRunning?: boolean;
  isRecording?: boolean;
  isLive?: boolean;
  isMuted?: boolean;
  modelsLoaded?: boolean;
  isLocalConnection?: boolean;
  canCancel?: boolean;
  isStandby?: boolean;
  canTranscribeFile?: boolean;
}

type DownloadEventType = 'runtime-dep' | 'ml-model' | 'model-preload';

interface BootstrapDownloadEvent {
  action: 'start' | 'complete' | 'fail';
  id: string;
  type: DownloadEventType;
  label: string;
  error?: string;
}

interface StartupActivityEvent {
  id: string;
  category: string;
  label: string;
  status?: string;
  progress?: number;
  totalSize?: string;
  downloadedSize?: string;
  detail?: string;
  severity?: string;
  persistent?: boolean;
  phase?: string;
  syncMode?: string;
  expandableDetail?: string;
  durationMs?: number;
  ts?: number;
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
    getSessionType: () => string;
    openExternal: (url: string) => Promise<void>;
    openPath: (filePath: string) => Promise<string>;
    getConfigDir: () => Promise<string>;
    removeConfigAndCache: () => Promise<void>;
    getClientLogPath: () => Promise<string>;
    appendClientLogLine: (line: string) => Promise<void>;
    onClientLogLine: (callback: (entry: ClientLogLine) => void) => () => void;
    readLogFiles: (tailLines?: number) => Promise<{
      clientLog: string;
      serverLog: string;
      clientLogPath: string;
      serverLogPath: string;
    }>;
    readLocalFile: (
      filePath: string,
    ) => Promise<{ name: string; buffer: ArrayBuffer; mimeType: string }>;
  };
  docker: {
    available: () => Promise<boolean>;
    retryDetection: () => Promise<boolean>;
    getRuntimeKind: () => Promise<string | null>;
    getDetectionGuidance: () => Promise<string | null>;
    getComposeAvailable: () => Promise<boolean>;
    checkGpu: () => Promise<{ gpu: boolean; toolkit: boolean; vulkan: boolean }>;
    listImages: () => Promise<
      Array<{ tag: string; fullName: string; size: string; created: string; id: string }>
    >;
    listRemoteTags: () => Promise<Array<{ tag: string; created: string | null }>>;
    fetchRemoteTagDates: (tags: string[]) => Promise<Record<string, string | null>>;
    pullImage: (tag: string) => Promise<string>;
    cancelPull: () => Promise<boolean>;
    isPulling: () => Promise<boolean>;
    hasSidecarImage: () => Promise<boolean>;
    pullSidecarImage: () => Promise<string>;
    cancelSidecarPull: () => Promise<boolean>;
    isSidecarPulling: () => Promise<boolean>;
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
    onDownloadEvent: (callback: (event: BootstrapDownloadEvent) => void) => () => void;
    onActivityEvent: (callback: (event: StartupActivityEvent) => void) => () => void;
  };
  tray: {
    setTooltip: (tooltip: string) => Promise<void>;
    setState: (state: TrayState) => Promise<void>;
    setMenuState: (menuState: TrayMenuState) => Promise<void>;
    onAction: (callback: (action: string, ...args: any[]) => void) => () => void;
  };
  audio: {
    getDesktopSources: () => Promise<Array<{ id: string; name: string; thumbnail: string }>>;
    enableSystemAudioLoopback: () => Promise<void>;
    disableSystemAudioLoopback: () => Promise<void>;
    listSinks: () => Promise<Array<{ name: string; description: string }>>;
    createMonitorLoopback: (
      sinkName: string,
    ) => Promise<{ moduleId: number; volumePct: number | null }>;
    removeMonitorLoopback: () => Promise<void>;
  };
  updates: {
    getStatus: () => Promise<UpdateStatus | null>;
    checkNow: () => Promise<UpdateStatus>;
    download: () => Promise<
      | { ok: true; reason?: 'already-downloading' }
      | { ok: false; reason: 'no-update-available' | 'error'; message?: string }
      | {
          ok: false;
          reason: 'incompatible-server';
          detail: {
            serverVersion: string;
            compatibleRange: string;
            deployment: 'local' | 'remote';
          };
        }
    >;
    checkCompatibility: () => Promise<CompatResult>;
    install: () => Promise<{ ok: boolean; reason?: string; detail?: string }>;
    cancelDownload: () => Promise<{ ok: boolean }>;
    cancelPendingInstall: () => Promise<{ ok: true }>;
    getInstallerStatus: () => Promise<InstallerStatus>;
    onInstallerStatus: (callback: (status: InstallerStatus) => void) => () => void;
    onInstallReady: (callback: () => void) => () => void;
  };
  clipboard: {
    writeText: (text: string) => Promise<void>;
    pasteAtCursor: (text: string, options?: { preserveClipboard?: boolean }) => Promise<void>;
  };
  shortcuts: {
    getPortalBindings: () => Promise<Array<{ id: string; trigger: string }> | null>;
    rebind: () => Promise<void>;
    isWaylandPortal: () => Promise<boolean>;
    onPortalChanged: (
      callback: (bindings: Array<{ id: string; trigger: string }>) => void,
    ) => () => void;
  };
  fileIO: {
    getDownloadsPath: () => Promise<string>;
    writeText: (filePath: string, content: string) => Promise<void>;
    selectFolder: () => Promise<string | null>;
  };
  notifications: {
    show: (options: {
      title: string;
      body: string;
      silent?: boolean;
      timeoutMs?: number;
    }) => Promise<boolean>;
  };
}

interface ComponentUpdateStatus {
  current: string | null;
  latest: string | null;
  updateAvailable: boolean;
  error: string | null;
  /**
   * Markdown body from the GitHub release (app channel only). Trimmed to
   * 50 000 chars at capture time. `null` when absent, empty, or when the
   * source is not a GitHub release (e.g., the `server` channel on GHCR).
   */
  releaseNotes: string | null;
}

type InstallerStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | {
      state: 'downloading';
      version: string;
      percent: number;
      bytesPerSecond: number;
      transferred: number;
      total: number;
    }
  | { state: 'verifying'; version: string }
  | { state: 'downloaded'; version: string }
  | { state: 'cancelled' }
  | { state: 'error'; message: string };

interface Manifest {
  version: string;
  compatibleServerRange: string;
  sha256: Record<string, string>;
  releaseType: string;
}

type CompatUnknownReason =
  | 'no-manifest'
  | 'manifest-fetch-failed'
  | 'manifest-parse-error'
  | 'server-version-unavailable'
  | 'invalid-range';

type CompatResult =
  | { result: 'compatible'; manifest: Manifest; serverVersion: string }
  | {
      result: 'incompatible';
      manifest: Manifest;
      serverVersion: string;
      compatibleRange: string;
      deployment: 'local' | 'remote';
    }
  | { result: 'unknown'; reason: CompatUnknownReason; detail?: string };

interface UpdateStatus {
  lastChecked: string;
  app: ComponentUpdateStatus;
  server: ComponentUpdateStatus;
  installer?: InstallerStatus;
}

interface Window {
  electronAPI?: ElectronAPI;
}
