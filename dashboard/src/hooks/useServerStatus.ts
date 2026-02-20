import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient, type ServerStatus } from '../api/client';

export type ConnectionState = 'active' | 'inactive' | 'warning' | 'error' | 'loading';

export interface ServerConnectionInfo {
  /** StatusLight-compatible state for the server */
  serverStatus: ConnectionState;
  /** StatusLight-compatible state for the client (connected to server?) */
  clientStatus: ConnectionState;
  /** Detailed server info when connected, null otherwise */
  details: ServerStatus | null;
  /** Human-readable status label */
  serverLabel: string;
  /** Whether the server is reachable at all */
  reachable: boolean;
  /** Whether models are loaded and ready */
  ready: boolean;
  /** Last error message, if any */
  error: string | null;
  /** Force an immediate re-check */
  refresh: () => void;
}

/**
 * Hook that polls the TranscriptionSuite server for health/status.
 * Returns StatusLight-compatible states for server and client indicators.
 *
 * Uses a single GET /api/status request per cycle (not the old
 * /health + /ready + /api/status triple) and skips state updates
 * when the response hasn't changed.
 *
 * @param pollInterval  Polling interval in ms (default: 10 000)
 */
export function useServerStatus(pollInterval = 10_000): ServerConnectionInfo {
  const [serverStatus, setServerStatus] = useState<ConnectionState>('loading');
  const [clientStatus, setClientStatus] = useState<ConnectionState>('loading');
  const [details, setDetails] = useState<ServerStatus | null>(null);
  const [serverLabel, setServerLabel] = useState('Connecting…');
  const [reachable, setReachable] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const prevJsonRef = useRef<string>('');

  const check = useCallback(async () => {
    const result = await apiClient.checkConnection();

    if (!mountedRef.current) return;

    // Skip state updates when the response is identical to the previous one
    const json = JSON.stringify(result);
    if (json === prevJsonRef.current) return;
    prevJsonRef.current = json;

    setReachable(result.reachable);
    setReady(result.ready);
    setDetails(result.status);
    setError(result.error);

    if (!result.reachable) {
      setServerStatus('inactive');
      setClientStatus('inactive');
      setServerLabel('Server offline');
    } else if (result.ready) {
      setServerStatus('active');
      setClientStatus('active');
      setServerLabel('Server ready');
    } else {
      // Reachable but not ready (models loading, etc.)
      setServerStatus('warning');
      setClientStatus('warning');
      setServerLabel('Models loading…');
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    check(); // Initial check immediately

    const interval = setInterval(check, pollInterval);

    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, [check, pollInterval]);

  return {
    serverStatus,
    clientStatus,
    details,
    serverLabel,
    reachable,
    ready,
    error,
    refresh: check,
  };
}
