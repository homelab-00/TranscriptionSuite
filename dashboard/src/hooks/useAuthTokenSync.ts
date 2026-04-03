import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { extractAdminTokenFromDockerLogLine } from '../utils/dockerLogParsing';

/**
 * Always-on hook that detects the admin auth token from Docker logs
 * and keeps `apiClient` + electron-store in sync, regardless of which
 * view is active. Also publishes the token to the React Query cache
 * under `['authToken']` so any consumer can subscribe reactively.
 *
 * **Remote-mode guard:** When `connection.useRemote` is true, the hook
 * skips Docker log scanning entirely — the local container holds a
 * different admin token than the remote server.
 *
 * In non-Electron environments (browser dev mode), this is a no-op.
 */
export function useAuthTokenSync(serverReachable: boolean): void {
  const qc = useQueryClient();
  const knownTokenRef = useRef('');

  useEffect(() => {
    const api = (window as any).electronAPI;
    const docker = api?.docker;
    if (!docker) return;

    let cancelled = false;
    let pollId: number | undefined;
    let unsubscribe: (() => void) | undefined;

    const applyDetectedToken = (token: string) => {
      const normalized = token.trim();
      if (!normalized || normalized === knownTokenRef.current) return;

      knownTokenRef.current = normalized;
      api?.config?.set?.('connection.authToken', normalized).catch(() => {});
      apiClient.setAuthToken(normalized);
      qc.setQueryData(['authToken'], normalized);
    };

    const scanRecentLogs = async () => {
      try {
        const lines = await docker.getLogs?.(300);
        if (cancelled || !Array.isArray(lines)) return;
        for (let i = lines.length - 1; i >= 0; i -= 1) {
          const token = extractAdminTokenFromDockerLogLine(lines[i]);
          if (token) {
            applyDetectedToken(token);
            break;
          }
        }
      } catch {
        // Server/container may not exist yet.
      }
    };

    // Single async init: seed from config first, then decide whether to scan.
    // This eliminates the race between the old config-seed effect and the
    // Docker-scan effect — the config read always completes before scanning.
    const init = async () => {
      // 1. Seed knownTokenRef from persisted config so we don't overwrite
      //    an existing token with the same value from logs.
      try {
        const saved = await api?.config?.get?.('connection.authToken');
        if (typeof saved === 'string' && saved.trim()) {
          knownTokenRef.current = saved.trim();
          qc.setQueryData(['authToken'], saved.trim());
        }
      } catch {
        // Config unavailable — continue with empty ref.
      }

      if (cancelled) return;

      // 2. If the app is configured for a remote server, skip Docker log
      //    scanning entirely. The local container's admin token is different
      //    from the remote server's token and must not overwrite it.
      try {
        const useRemote = await api?.config?.get?.('connection.useRemote');
        if (useRemote) return;
      } catch {
        // Config unavailable — fall through to scan (safe default for local).
      }

      if (cancelled) return;

      // 3. Local mode — scan Docker logs for the admin token.
      void scanRecentLogs();

      unsubscribe =
        typeof docker.onLogLine === 'function'
          ? docker.onLogLine((line: string) => {
              const token = extractAdminTokenFromDockerLogLine(line);
              if (token) applyDetectedToken(token);
            })
          : undefined;

      pollId = window.setInterval(() => {
        if (!knownTokenRef.current) {
          void scanRecentLogs();
        }
      }, 2000);
    };

    void init();

    return () => {
      cancelled = true;
      if (pollId !== undefined) window.clearInterval(pollId);
      unsubscribe?.();
    };
  }, [qc]);
}
