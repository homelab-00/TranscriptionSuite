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

export type InstallerStatus =
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
  | { state: 'error'; message: string }
  | {
      state: 'manual-download-required';
      version: string | null;
      downloadUrl: string;
      reason: string;
    };

/** Per-release manifest shape (M4). Kept in sync with compatGuard.ts. */
export interface Manifest {
  version: string;
  compatibleServerRange: string;
  sha256: Record<string, string>;
  releaseType: string;
}

export type CompatUnknownReason =
  | 'no-manifest'
  | 'manifest-fetch-failed'
  | 'manifest-parse-error'
  | 'server-version-unavailable'
  | 'invalid-range';

export type CompatResult =
  | { result: 'compatible'; manifest: Manifest; serverVersion: string }
  | {
      result: 'incompatible';
      manifest: Manifest;
      serverVersion: string;
      compatibleRange: string;
      deployment: 'local' | 'remote';
    }
  | { result: 'unknown'; reason: CompatUnknownReason; detail?: string };

// Keep in sync with src/types/runtime.ts (canonical) and src/types/electron.d.ts
export type RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'metal';
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
    getArch: () => string;
    reportRendererReady: () => void;
    getSessionType: () => string;
    openExternal: (url: string) => Promise<void>;
    openPath: (filePath: string) => Promise<string>;
    getConfigDir: () => Promise<string>;
    ensureServerConfig: () => Promise<string>;
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
    listRemoteTags: () => Promise<
      | { status: 'ok'; tags: Array<{ tag: string; created: string | null }> }
      | { status: 'not-published'; tags: [] }
      | { status: 'error'; tags: [] }
    >;
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
    checkTailscaleCertsExist: () => Promise<boolean>;
    getLogs: (tail?: number) => Promise<string[]>;
    startLogStream: (tail?: number) => Promise<void>;
    stopLogStream: () => Promise<void>;
    onLogLine: (callback: (line: string) => void) => () => void;
    onDownloadEvent: (
      callback: (event: {
        action: 'start' | 'complete' | 'fail';
        id: string;
        type: string;
        label: string;
        error?: string;
      }) => void,
    ) => () => void;
    onActivityEvent: (
      callback: (event: {
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
      }) => void,
    ) => () => void;
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
    /** Linux: list PulseAudio/PipeWire output sinks for system audio capture. */
    listSinks: () => Promise<Array<{ name: string; description: string }>>;
    /** Linux: create a virtual mic from a sink's monitor source. */
    createMonitorLoopback: (
      sinkName: string,
    ) => Promise<{ moduleId: number; volumePct: number | null }>;
    /** Linux: remove the virtual mic. */
    removeMonitorLoopback: () => Promise<void>;
  };
  updates: {
    getStatus: () => Promise<UpdateStatus | null>;
    checkNow: () => Promise<UpdateStatus>;
    /**
     * Begin download. Guards against concurrent calls. On incompatible
     * server (M4 pre-flight compat check) returns `{ok:false,
     * reason:'incompatible-server', detail:{...}}` and does NOT invoke the
     * underlying UpdateInstaller.
     */
    download: () => Promise<
      | { ok: true; reason?: 'already-downloading' }
      | { ok: false; reason: 'no-update-available' | 'error'; message?: string }
      | { ok: false; reason: 'manual-download-required'; downloadUrl: string }
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
    /**
     * Run the M4 compat guard without starting a download. Used by M5's
     * pre-install modal to render compat status before the user commits.
     */
    checkCompatibility: () => Promise<CompatResult>;
    /**
     * Request install. When the server is busy the install is deferred and
     * the caller receives `{ok:false, reason:'deferred-until-idle', detail}`.
     * A later `updates:installReady` event signals the pending install is
     * now actionable. Pass-through `doInstall()` result otherwise.
     */
    install: () => Promise<{ ok: boolean; reason?: string; detail?: string }>;
    /** Cancel any active download. No-op when idle. */
    cancelDownload: () => Promise<{ ok: boolean }>;
    /** Cancel a pending (deferred-until-idle) install. Idempotent. */
    cancelPendingInstall: () => Promise<{ ok: true }>;
    /** Read the current installer state. */
    getInstallerStatus: () => Promise<InstallerStatus>;
    /** Subscribe to installer state transitions. Returns an unsubscribe fn. */
    onInstallerStatus: (callback: (status: InstallerStatus) => void) => () => void;
    /** Fires when a deferred install transitions to actionable (server idle). */
    onInstallReady: (callback: () => void) => () => void;
    /**
     * M7: open the GitHub release page in the user's default browser. Used
     * by the manual-download banner state (read-only AppImage on Linux,
     * macOS without code signing, etc.). The URL is allow-listed
     * server-side to `https://github.com/homelab-00/TranscriptionSuite/
     * releases/...` only.
     */
    openReleasePage: (
      url: string,
    ) => Promise<
      | { ok: true }
      | { ok: false; reason: 'untrusted-url' }
      | { ok: false; reason: 'open-failed'; message: string }
    >;
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
  serverConfig: {
    readTemplate: () => Promise<string | null>;
    readLocal: () => Promise<string | null>;
    writeLocal: (yamlText: string) => Promise<void>;
  };
  server: {
    probeConnection: (
      url: string,
      skipCertVerify?: boolean,
    ) => Promise<{
      ok: boolean;
      httpStatus?: number;
      error?: string;
      errorCode?: string;
      body?: string;
    }>;
    checkFirewallPort: (
      port: number,
    ) => Promise<{ listening: boolean; firewallSuspect: boolean; hint: string | null }>;
    /**
     * Read the persisted legacy-GPU toggle (Issue #83).
     * Returns false when unset (default user path unchanged).
     */
    getUseLegacyGpu: () => Promise<boolean>;
    /**
     * Write the legacy-GPU toggle. When `wipeRuntimeVolume` is true the main
     * process attempts to remove the `transcriptionsuite-runtime` volume so
     * the next bootstrap re-syncs wheels from the new PyTorch index.
     *
     * `runtimeVolumeWiped` reflects the actual outcome — false when the wipe
     * was requested but failed (e.g., volume held by a stopped-but-not-removed
     * container). `runtimeVolumeWipeError` carries the failure reason in that
     * case so the renderer can surface it. When no volume exists yet (first
     * toggle before any container has bootstrapped), `runtimeVolumeWiped` is
     * true with `runtimeVolumeWipeError = null` — there is nothing to wipe.
     */
    setUseLegacyGpu: (
      value: boolean,
      wipeRuntimeVolume?: boolean,
    ) => Promise<{
      useLegacyGpu: boolean;
      runtimeVolumeWiped: boolean;
      runtimeVolumeWipeError: string | null;
    }>;
  };
  tailscale: {
    getHostname: () => Promise<string | null>;
  };
  fileIO: {
    getDownloadsPath: () => Promise<string>;
    writeText: (filePath: string, content: string) => Promise<void>;
    selectFolder: () => Promise<string | null>;
  };
  watcher: {
    startSession: (folderPath: string) => Promise<void>;
    stopSession: () => Promise<void>;
    startNotebook: (folderPath: string) => Promise<void>;
    stopNotebook: () => Promise<void>;
    clearLedger: (type: 'session' | 'notebook') => Promise<void>;
    checkPath: (folderPath: string) => Promise<boolean>;
    /** Push listener — returns cleanup function. Follows docker.onLogLine pattern. */
    onFilesDetected: (
      callback: (payload: {
        type: 'session' | 'notebook';
        files: string[];
        count: number;
        fileMeta: Array<{ path: string; createdAt: string }>;
      }) => void,
    ) => () => void;
  };
  notifications: {
    show: (options: {
      title: string;
      body: string;
      silent?: boolean;
      timeoutMs?: number;
    }) => Promise<boolean>;
  };
  mlx: {
    start: (opts: {
      port: number;
      hfToken?: string;
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
    }) => Promise<void>;
    stop: () => Promise<void>;
    getStatus: () => Promise<'stopped' | 'starting' | 'running' | 'stopping' | 'error'>;
    getLogs: (tail?: number) => Promise<string[]>;
    onStatusChanged: (
      callback: (status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error') => void,
    ) => () => void;
    onLogLine: (callback: (line: string) => void) => () => void;
  };
}

export interface ComponentUpdateStatus {
  current: string | null;
  latest: string | null;
  updateAvailable: boolean;
  error: string | null;
  releaseNotes: string | null;
}

export interface UpdateStatus {
  lastChecked: string;
  app: ComponentUpdateStatus;
  server: ComponentUpdateStatus;
  installer?: InstallerStatus;
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
    getArch: () => process.arch,
    // M6: one-way signal fired by <App> after initial React mount. Main
    // calls LaunchWatchdog.confirmLaunchStable in response, resetting the
    // per-version launch-attempt counter. A broken renderer that never
    // mounts will never emit, so the counter accumulates and triggers
    // rollback on the 3rd failed launch. Idempotent on main side.
    reportRendererReady: () => ipcRenderer.send('updates:rendererReady'),
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
    readLogFiles: (tailLines = 200) =>
      ipcRenderer.invoke('app:readLogFiles', tailLines) as Promise<{
        clientLog: string;
        serverLog: string;
        clientLogPath: string;
        serverLogPath: string;
      }>,
    readLocalFile: (filePath: string) =>
      ipcRenderer.invoke('app:readLocalFile', filePath) as Promise<{
        name: string;
        buffer: ArrayBuffer;
        mimeType: string;
      }>,
  },
  docker: {
    available: () => ipcRenderer.invoke('docker:available'),
    retryDetection: () => ipcRenderer.invoke('docker:retryDetection'),
    getRuntimeKind: () => ipcRenderer.invoke('docker:getRuntimeKind') as Promise<string | null>,
    getDetectionGuidance: () =>
      ipcRenderer.invoke('docker:getDetectionGuidance') as Promise<string | null>,
    getComposeAvailable: () => ipcRenderer.invoke('docker:getComposeAvailable') as Promise<boolean>,
    checkGpu: () => ipcRenderer.invoke('docker:checkGpu'),
    listImages: () => ipcRenderer.invoke('docker:listImages'),
    listRemoteTags: () =>
      ipcRenderer.invoke('docker:listRemoteTags') as Promise<
        | { status: 'ok'; tags: Array<{ tag: string; created: string | null }> }
        | { status: 'not-published'; tags: [] }
        | { status: 'error'; tags: [] }
      >,
    fetchRemoteTagDates: (tags: string[]) =>
      ipcRenderer.invoke('docker:fetchRemoteTagDates', tags) as Promise<
        Record<string, string | null>
      >,
    pullImage: (tag: string) => ipcRenderer.invoke('docker:pullImage', tag),
    cancelPull: () => ipcRenderer.invoke('docker:cancelPull'),
    isPulling: () => ipcRenderer.invoke('docker:isPulling'),
    hasSidecarImage: () => ipcRenderer.invoke('docker:hasSidecarImage'),
    pullSidecarImage: () => ipcRenderer.invoke('docker:pullSidecarImage'),
    cancelSidecarPull: () => ipcRenderer.invoke('docker:cancelSidecarPull'),
    isSidecarPulling: () => ipcRenderer.invoke('docker:isSidecarPulling'),
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
    checkTailscaleCertsExist: () =>
      ipcRenderer.invoke('docker:checkTailscaleCertsExist') as Promise<boolean>,
    getLogs: (tail?: number) => ipcRenderer.invoke('docker:getLogs', tail),
    startLogStream: (tail?: number) => ipcRenderer.invoke('docker:startLogStream', tail),
    stopLogStream: () => ipcRenderer.invoke('docker:stopLogStream'),
    onLogLine: (callback: (line: string) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
      ipcRenderer.on('docker:logLine', handler);
      return () => ipcRenderer.removeListener('docker:logLine', handler);
    },
    onDownloadEvent: (
      callback: (event: {
        action: 'start' | 'complete' | 'fail';
        id: string;
        type: string;
        label: string;
        error?: string;
      }) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        evt: {
          action: 'start' | 'complete' | 'fail';
          id: string;
          type: string;
          label: string;
          error?: string;
        },
      ) => callback(evt);
      ipcRenderer.on('docker:downloadEvent', handler);
      return () => ipcRenderer.removeListener('docker:downloadEvent', handler);
    },
    onActivityEvent: (
      callback: (event: {
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
      }) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        evt: {
          id: string;
          category: string;
          label: string;
          status?: string;
          [key: string]: unknown;
        },
      ) => callback(evt as Parameters<typeof callback>[0]);
      ipcRenderer.on('activity:event', handler);
      return () => ipcRenderer.removeListener('activity:event', handler);
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
    enableSystemAudioLoopback: () => ipcRenderer.invoke('audio:enableSystemAudioLoopback'),
    disableSystemAudioLoopback: () => ipcRenderer.invoke('audio:disableSystemAudioLoopback'),
    listSinks: () => ipcRenderer.invoke('audio:listSinks'),
    createMonitorLoopback: (sinkName: string) =>
      ipcRenderer.invoke('audio:createMonitorLoopback', sinkName),
    removeMonitorLoopback: () => ipcRenderer.invoke('audio:removeMonitorLoopback'),
  },
  updates: {
    getStatus: () => ipcRenderer.invoke('updates:getStatus'),
    checkNow: () => ipcRenderer.invoke('updates:checkNow'),
    download: () => ipcRenderer.invoke('updates:download'),
    checkCompatibility: () => ipcRenderer.invoke('updates:checkCompatibility'),
    install: () => ipcRenderer.invoke('updates:install'),
    cancelDownload: () => ipcRenderer.invoke('updates:cancelDownload'),
    cancelPendingInstall: () => ipcRenderer.invoke('updates:cancelPendingInstall'),
    getInstallerStatus: () => ipcRenderer.invoke('updates:getInstallerStatus'),
    onInstallerStatus: (callback: (status: InstallerStatus) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, status: InstallerStatus) =>
        callback(status);
      ipcRenderer.on('updates:installerStatus', handler);
      return () => ipcRenderer.removeListener('updates:installerStatus', handler);
    },
    onInstallReady: (callback: () => void) => {
      const handler = () => callback();
      ipcRenderer.on('updates:installReady', handler);
      return () => ipcRenderer.removeListener('updates:installReady', handler);
    },
    openReleasePage: (url: string) => ipcRenderer.invoke('updates:openReleasePage', url),
  },
  clipboard: {
    writeText: (text: string) => ipcRenderer.invoke('clipboard:writeText', text),
    pasteAtCursor: (text: string, options?: { preserveClipboard?: boolean }) =>
      ipcRenderer.invoke('clipboard:pasteAtCursor', text, options),
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
  serverConfig: {
    readTemplate: () => ipcRenderer.invoke('serverConfig:readTemplate') as Promise<string | null>,
    readLocal: () => ipcRenderer.invoke('serverConfig:readLocal') as Promise<string | null>,
    writeLocal: (yamlText: string) =>
      ipcRenderer.invoke('serverConfig:writeLocal', yamlText) as Promise<void>,
  },
  server: {
    probeConnection: (url: string, skipCertVerify?: boolean) =>
      ipcRenderer.invoke('server:probeConnection', url, skipCertVerify ?? false) as Promise<{
        ok: boolean;
        httpStatus?: number;
        error?: string;
        errorCode?: string;
        body?: string;
      }>,
    checkFirewallPort: (port: number) =>
      ipcRenderer.invoke('server:checkFirewallPort', port) as Promise<{
        listening: boolean;
        firewallSuspect: boolean;
        hint: string | null;
      }>,
    getUseLegacyGpu: () => ipcRenderer.invoke('server:getUseLegacyGpu') as Promise<boolean>,
    setUseLegacyGpu: (value: boolean, wipeRuntimeVolume?: boolean) =>
      ipcRenderer.invoke('server:setUseLegacyGpu', value, wipeRuntimeVolume ?? false) as Promise<{
        useLegacyGpu: boolean;
        runtimeVolumeWiped: boolean;
        runtimeVolumeWipeError: string | null;
      }>,
  },
  tailscale: {
    getHostname: () => ipcRenderer.invoke('tailscale:getHostname') as Promise<string | null>,
  },
  fileIO: {
    getDownloadsPath: () => ipcRenderer.invoke('app:getDownloadsPath') as Promise<string>,
    writeText: (filePath: string, content: string) =>
      ipcRenderer.invoke('file:writeText', filePath, content) as Promise<void>,
    selectFolder: () => ipcRenderer.invoke('dialog:selectFolder') as Promise<string | null>,
  },
  watcher: {
    startSession: (folderPath: string) =>
      ipcRenderer.invoke('watcher:startSession', folderPath) as Promise<void>,
    stopSession: () => ipcRenderer.invoke('watcher:stopSession') as Promise<void>,
    startNotebook: (folderPath: string) =>
      ipcRenderer.invoke('watcher:startNotebook', folderPath) as Promise<void>,
    stopNotebook: () => ipcRenderer.invoke('watcher:stopNotebook') as Promise<void>,
    clearLedger: (type: 'session' | 'notebook') =>
      ipcRenderer.invoke('watcher:clearLedger', type) as Promise<void>,
    checkPath: (folderPath: string) =>
      ipcRenderer.invoke('watcher:checkPath', folderPath) as Promise<boolean>,
    onFilesDetected: (
      callback: (payload: {
        type: 'session' | 'notebook';
        files: string[];
        count: number;
        fileMeta: Array<{ path: string; createdAt: string }>;
      }) => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        payload: {
          type: 'session' | 'notebook';
          files: string[];
          count: number;
          fileMeta: Array<{ path: string; createdAt: string }>;
        },
      ) => callback(payload);
      ipcRenderer.on('watcher:filesDetected', handler);
      return () => ipcRenderer.removeListener('watcher:filesDetected', handler);
    },
  },
  notifications: {
    show: (options: { title: string; body: string; silent?: boolean; timeoutMs?: number }) =>
      ipcRenderer.invoke('notifications:show', options) as Promise<boolean>,
  },
  mlx: {
    start: (opts: {
      port: number;
      hfToken?: string;
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
    }) => ipcRenderer.invoke('mlx:start', opts) as Promise<void>,
    stop: () => ipcRenderer.invoke('mlx:stop') as Promise<void>,
    getStatus: () =>
      ipcRenderer.invoke('mlx:getStatus') as Promise<
        'stopped' | 'starting' | 'running' | 'stopping' | 'error'
      >,
    getLogs: (tail?: number) => ipcRenderer.invoke('mlx:getLogs', tail) as Promise<string[]>,
    onStatusChanged: (
      callback: (status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error') => void,
    ) => {
      const handler = (
        _event: Electron.IpcRendererEvent,
        status: 'stopped' | 'starting' | 'running' | 'stopping' | 'error',
      ) => callback(status);
      ipcRenderer.on('mlx:statusChanged', handler);
      return () => ipcRenderer.removeListener('mlx:statusChanged', handler);
    },
    onLogLine: (callback: (line: string) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
      ipcRenderer.on('mlx:logLine', handler);
      return () => ipcRenderer.removeListener('mlx:logLine', handler);
    },
  },
} satisfies ElectronAPI);
