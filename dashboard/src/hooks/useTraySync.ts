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
  /** Transcription (one-shot recording) status */
  transcriptionStatus: TranscriptionStatus;
  /** Live mode status */
  liveStatus: LiveStatus;
  /** Whether audio is muted (live mode or recording) */
  muted: boolean;
  /** Callbacks to forward tray context-menu actions */
  onStartRecording?: () => void;
  onStopRecording?: () => void;
  onToggleMute?: () => void;
}

/**
 * Resolve the highest-priority TrayState from all of the app's sub-states.
 */
function resolveTrayState(deps: Pick<TrySyncDeps, 'serverStatus' | 'containerRunning' | 'transcriptionStatus' | 'liveStatus' | 'muted'>): TrayState {
  const { serverStatus, containerRunning, transcriptionStatus, liveStatus, muted } = deps;

  // Muted takes visual priority while recording/listening
  if (muted && (transcriptionStatus === 'recording' || liveStatus === 'listening' || liveStatus === 'processing')) {
    return 'muted';
  }

  // One-shot transcription states (higher priority than live)
  switch (transcriptionStatus) {
    case 'connecting':
      return 'connecting';
    case 'recording':
      return 'recording';
    case 'processing':
      return 'processing';
    case 'complete':
      return 'complete';
    case 'error':
      return 'error';
  }

  // Live mode states
  switch (liveStatus) {
    case 'connecting':
    case 'starting':
      return 'connecting';
    case 'listening':
      return 'live-listening';
    case 'processing':
      return 'live-processing';
    case 'error':
      return 'error';
  }

  // Server / connection states
  if (serverStatus === 'inactive' && !containerRunning) {
    return 'idle';
  }
  if (serverStatus === 'inactive') {
    return 'disconnected';
  }
  if (serverStatus === 'warning') {
    return 'connecting';
  }
  if (serverStatus === 'active') {
    return 'active';
  }
  if (serverStatus === 'error') {
    return 'error';
  }

  return 'idle';
}

export function useTraySync(deps: TrySyncDeps): void {
  if (!isElectron) return;

  const prevStateRef = useRef<TrayState>('idle');
  const callbacksRef = useRef(deps);
  callbacksRef.current = deps;

  const {
    serverStatus,
    containerRunning,
    transcriptionStatus,
    liveStatus,
    muted,
  } = deps;

  // Push TrayState whenever inputs change
  useEffect(() => {
    const newState = resolveTrayState({ serverStatus, containerRunning, transcriptionStatus, liveStatus, muted });
    if (newState !== prevStateRef.current) {
      prevStateRef.current = newState;
      window.electronAPI!.tray.setState(newState);
    }
  }, [serverStatus, containerRunning, transcriptionStatus, liveStatus, muted]);

  // Push menu state so the context menu shows the right labels
  useEffect(() => {
    const isRecording = transcriptionStatus === 'recording' || transcriptionStatus === 'processing';
    const isLive = liveStatus === 'listening' || liveStatus === 'processing' || liveStatus === 'starting';
    window.electronAPI!.tray.setMenuState({
      serverRunning: containerRunning,
      isRecording,
      isLive,
      isMuted: muted,
    });
  }, [containerRunning, transcriptionStatus, liveStatus, muted]);

  // Listen for tray context-menu actions forwarded from the main process
  useEffect(() => {
    const cleanup = window.electronAPI!.tray.onAction((action: string) => {
      switch (action) {
        case 'start-recording':
          callbacksRef.current.onStartRecording?.();
          break;
        case 'stop-recording':
          callbacksRef.current.onStopRecording?.();
          break;
        case 'toggle-mute':
          callbacksRef.current.onToggleMute?.();
          break;
      }
    });
    return cleanup;
  }, []);
}
