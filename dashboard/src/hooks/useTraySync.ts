/**
 * useTraySync — watches application state (server, recording, live mode,
 * Docker) and pushes the resolved TrayState to the Electron main process.
 *
 * Also listens for tray context-menu actions and dispatches them to the
 * correct hook callback.
 *
 * Drop this hook into your top-level App component.
 */

import { useEffect, useRef } from 'react';
import type { LiveStatus } from './useLiveMode';
import type { TranscriptionStatus } from './useTranscription';
import type { ConnectionState } from './useServerStatus';

const isElectron = typeof window !== 'undefined' && window.electronAPI != null;

interface TrySyncDeps {
  /** Server connection state from useServerStatus */
  serverStatus: ConnectionState;
  /** Whether the Docker container is running */
  containerRunning: boolean;
  /** Docker container health status ('healthy' | 'starting' | 'unhealthy' | undefined) */
  containerHealth?: string;
  /** Transcription (one-shot recording) status */
  transcriptionStatus: TranscriptionStatus;
  /** Live mode status */
  liveStatus: LiveStatus;
  /** Whether audio is muted (live mode or recording) */
  muted: boolean;
  /** Whether a file upload or batch import is in progress */
  isUploading?: boolean;
  /** Active transcription model name (for tooltip) */
  activeModel?: string;
  /** Whether ASR models are currently loaded on the server */
  modelsLoaded?: boolean;
  /** Whether the server connection is local (enables model management) */
  isLocalConnection?: boolean;
  /** Callbacks to forward tray context-menu actions */
  onStartRecording?: () => void;
  onStopRecording?: () => void;
  onCancelRecording?: () => void;
  onToggleMute?: () => void;
  onTranscribeFile?: (filePath: string) => void;
  onStartLiveMode?: () => void;
  onStopLiveMode?: () => void;
  onToggleLiveMute?: () => void;
  onToggleModels?: () => void;
}

/**
 * Resolve the highest-priority TrayState from all of the app's sub-states.
 */
function resolveTrayState(
  deps: Pick<
    TrySyncDeps,
    | 'serverStatus'
    | 'containerRunning'
    | 'containerHealth'
    | 'transcriptionStatus'
    | 'liveStatus'
    | 'muted'
    | 'isUploading'
    | 'modelsLoaded'
  >,
): TrayState {
  const {
    serverStatus,
    containerRunning,
    containerHealth,
    transcriptionStatus,
    liveStatus,
    muted,
    isUploading,
    modelsLoaded,
  } = deps;

  // Not running, inactive, or Docker healthcheck not yet passed → gray
  if (!containerRunning || serverStatus === 'inactive') {
    return 'disconnected';
  }
  if (containerHealth === 'starting' || containerHealth === 'unhealthy') {
    return 'disconnected';
  }
  if (serverStatus === 'error') {
    return 'error';
  }

  // One-shot transcription ACTIVE states (higher priority than live)
  if (transcriptionStatus === 'connecting' || transcriptionStatus === 'recording') {
    return muted ? 'recording-muted' : 'recording';
  }
  if (transcriptionStatus === 'processing') {
    return 'processing';
  }

  // Live mode states
  if (liveStatus === 'listening' || liveStatus === 'starting' || liveStatus === 'connecting') {
    return muted ? 'live-muted' : 'live-active';
  }
  if (liveStatus === 'processing') {
    return 'processing';
  }

  // Terminal one-shot states (must not block live mode above)
  if (transcriptionStatus === 'complete') {
    return 'complete';
  }
  if (transcriptionStatus === 'error' || liveStatus === 'error') {
    return 'error';
  }

  // Upload / import in progress
  if (isUploading) {
    return 'uploading';
  }

  // Server running but models unloaded
  if (modelsLoaded === false) {
    return 'models-unloaded';
  }

  // Server running, healthy, nothing active
  if (serverStatus === 'active') {
    return 'idle';
  }

  // Fallback for 'warning' / 'loading' — server not fully healthy
  return 'disconnected';
}

export function useTraySync(deps: TrySyncDeps): void {
  if (!isElectron) return;

  const prevStateRef = useRef<TrayState>('idle');
  const callbacksRef = useRef(deps);
  callbacksRef.current = deps;

  const {
    serverStatus,
    containerRunning,
    containerHealth,
    transcriptionStatus,
    liveStatus,
    muted,
    isUploading,
    activeModel,
    modelsLoaded,
    isLocalConnection,
  } = deps;

  // Push menu state FIRST so it is applied before setState triggers a rebuildMenu in the
  // main process. React fires effects in definition order within the same render cycle,
  // and IPC messages are processed sequentially, so this guarantees menuState is
  // up-to-date before applyState() → rebuildMenu() runs.
  useEffect(() => {
    const isRecording =
      transcriptionStatus === 'connecting' ||
      transcriptionStatus === 'recording' ||
      transcriptionStatus === 'processing';
    const isLive =
      liveStatus === 'listening' || liveStatus === 'processing' || liveStatus === 'starting';

    // canCancel: during one-shot recording, processing (v0.5.6: recording + uploading + transcribing)
    const canCancel = transcriptionStatus === 'recording' || transcriptionStatus === 'processing';

    // isStandby: server connected and ready, nothing active.
    // 'complete' is intentionally NOT excluded — the tray should allow starting a new
    // recording immediately after a previous one finishes (mirrors canStartRecording in SessionView).
    const isStandby =
      containerRunning &&
      containerHealth === 'healthy' &&
      serverStatus === 'active' &&
      !isRecording &&
      !isLive;

    window.electronAPI!.tray.setMenuState({
      serverRunning: containerRunning,
      isRecording,
      isLive,
      isMuted: muted,
      modelsLoaded: modelsLoaded ?? true,
      isLocalConnection: isLocalConnection ?? true,
      canCancel,
      isStandby,
    });
  }, [
    containerRunning,
    containerHealth,
    transcriptionStatus,
    liveStatus,
    muted,
    serverStatus,
    modelsLoaded,
    isLocalConnection,
  ]);

  // Push TrayState after menu state so applyState() → rebuildMenu() sees the latest menuState.
  useEffect(() => {
    const newState = resolveTrayState({
      serverStatus,
      containerRunning,
      containerHealth,
      transcriptionStatus,
      liveStatus,
      muted,
      isUploading,
      modelsLoaded,
    });
    if (newState !== prevStateRef.current) {
      prevStateRef.current = newState;
      window.electronAPI!.tray.setState(newState);
    }
    // Also set custom tooltip with model info when server is active
    if (activeModel && containerRunning) {
      window.electronAPI!.tray.setTooltip(`TranscriptionSuite — Model: ${activeModel}`);
    }
  }, [
    serverStatus,
    containerRunning,
    containerHealth,
    transcriptionStatus,
    liveStatus,
    muted,
    isUploading,
    modelsLoaded,
    activeModel,
  ]);

  // Listen for tray context-menu actions forwarded from the main process
  useEffect(() => {
    const cleanup = window.electronAPI!.tray.onAction((action: string, ...args: any[]) => {
      switch (action) {
        case 'start-recording':
          callbacksRef.current.onStartRecording?.();
          break;
        case 'stop-recording':
          callbacksRef.current.onStopRecording?.();
          break;
        case 'cancel-recording':
          callbacksRef.current.onCancelRecording?.();
          break;
        case 'toggle-mute':
          callbacksRef.current.onToggleMute?.();
          break;
        case 'transcribe-file':
          if (args[0]) callbacksRef.current.onTranscribeFile?.(args[0] as string);
          break;
        case 'start-live-mode':
          callbacksRef.current.onStartLiveMode?.();
          break;
        case 'stop-live-mode':
          callbacksRef.current.onStopLiveMode?.();
          break;
        case 'toggle-live-mute':
          callbacksRef.current.onToggleLiveMute?.();
          break;
        case 'toggle-models':
          callbacksRef.current.onToggleModels?.();
          break;
      }
    });
    return cleanup;
  }, []);
}
