import { useQuery } from '@tanstack/react-query';
import { apiClient, type ServerStatus } from '../api/client';

export type ServerHealthState = 'active' | 'inactive' | 'warning' | 'error' | 'loading';

export interface ServerConnectionInfo {
  /** StatusLight-compatible state for the server */
  serverStatus: ServerHealthState;
  /** StatusLight-compatible state for the client (connected to server?) */
  clientStatus: ServerHealthState;
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
  /** GPU error string when CUDA is in a failed state, null otherwise */
  gpuError: string | null;
  /** Force an immediate re-check */
  refresh: () => void;
}

export function deriveStatus(
  result: Awaited<ReturnType<typeof apiClient.checkConnection>> | undefined,
): Omit<ServerConnectionInfo, 'refresh'> {
  if (!result) {
    return {
      serverStatus: 'loading',
      clientStatus: 'loading',
      details: null,
      serverLabel: 'Connecting…',
      reachable: false,
      ready: false,
      error: null,
      gpuError: null,
    };
  }

  if (!result.reachable) {
    return {
      serverStatus: 'inactive',
      clientStatus: 'inactive',
      details: result.status,
      serverLabel: 'Server offline',
      reachable: false,
      ready: false,
      error: result.error,
      gpuError: null,
    };
  }

  // GPU error takes priority — even if server is reachable, it cannot transcribe.
  if (result.status?.gpu_error) {
    return {
      serverStatus: 'error',
      clientStatus: 'error',
      details: result.status,
      serverLabel:
        result.status.gpu_error_action ??
        'GPU unavailable — restart computer or switch to CPU mode in Settings > Server',
      reachable: true,
      ready: false,
      error: result.error,
      gpuError: result.status.gpu_error,
    };
  }

  if (result.ready) {
    return {
      serverStatus: 'active',
      clientStatus: 'active',
      details: result.status,
      serverLabel: 'Server ready',
      reachable: true,
      ready: true,
      error: result.error,
      gpuError: null,
    };
  }

  return {
    serverStatus: 'warning',
    clientStatus: 'warning',
    details: result.status,
    serverLabel: 'Models loading…',
    reachable: true,
    ready: false,
    error: result.error,
    gpuError: null,
  };
}

/**
 * Hook that polls the TranscriptionSuite server for health/status.
 * Returns StatusLight-compatible states for server and client indicators.
 *
 * @param pollInterval  Polling interval in ms (default: 10 000)
 */
export function useServerStatus(pollInterval = 10_000): ServerConnectionInfo {
  const { data, refetch } = useQuery({
    queryKey: ['serverStatus'],
    queryFn: () => apiClient.checkConnection(),
    refetchInterval: pollInterval,
  });

  return {
    ...deriveStatus(data),
    refresh: () => void refetch(),
  };
}
