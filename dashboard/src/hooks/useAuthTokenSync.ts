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

    void scanRecentLogs();

    const unsubscribe =
      typeof docker.onLogLine === 'function'
        ? docker.onLogLine((line: string) => {
            const token = extractAdminTokenFromDockerLogLine(line);
            if (token) applyDetectedToken(token);
          })
        : undefined;

    const pollId = window.setInterval(() => {
      if (!knownTokenRef.current) {
        void scanRecentLogs();
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(pollId);
      unsubscribe?.();
    };
  }, [qc]);

  // Seed the ref from electron-store on mount so we don't overwrite
  // an existing persisted token with one from logs.
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('connection.authToken')
        .then((val: unknown) => {
          if (typeof val === 'string' && val.trim()) {
            knownTokenRef.current = val.trim();
            qc.setQueryData(['authToken'], val.trim());
          }
        })
        .catch(() => {});
    }
  }, [qc]);
}
