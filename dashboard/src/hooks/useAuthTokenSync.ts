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
 * **Stale-token guard:** When the server becomes reachable and a token
 * is cached, the hook validates it once via `POST /api/auth/login`.
 * If the server rejects it (stale token from a previous volume), the
 * token is cleared so the user sees "Auth token not configured" instead
 * of a confusing rejection loop.
 *
 * In non-Electron environments (browser dev mode), this is a no-op.
 */
export function useAuthTokenSync(serverReachable: boolean, useRemote: boolean): void {
  const qc = useQueryClient();
  const knownTokenRef = useRef('');
  const validatedRef = useRef(false);

  // ── Docker log scanning & config seeding (runs once on mount) ──────────
  useEffect(() => {
    const api = (window as any).electronAPI;
    const docker = api?.docker;
    if (!docker) return;

    let cancelled = false;
    let pollId: number | undefined;
    let unsubscribe: (() => void) | undefined;

    const clearStaleToken = () => {
      knownTokenRef.current = '';
      api?.config?.set?.('connection.authToken', '').catch(() => {});
      apiClient.setAuthToken(null);
      qc.setQueryData(['authToken'], '');
      qc.invalidateQueries({ queryKey: ['adminStatus'] });
    };

    const applyDetectedToken = (token: string) => {
      const normalized = token.trim();
      if (!normalized || normalized === knownTokenRef.current) return;

      knownTokenRef.current = normalized;
      validatedRef.current = false; // New token needs re-validation
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
      // Re-entering init (e.g. useRemote changed) — force re-validation
      // so a token that went stale during a remote period is caught.
      validatedRef.current = false;

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

      // 1b. If the server is already reachable and we have a token, validate
      //     it now. The second useEffect also handles this, but it may have
      //     already fired (and skipped) before init() finished seeding the ref.
      if (knownTokenRef.current && serverReachable && !validatedRef.current) {
        try {
          const result = await apiClient.login(knownTokenRef.current);
          if (cancelled) return;
          validatedRef.current = true;
          if (!result.success) {
            clearStaleToken();
            return;
          }
        } catch {
          // Network/server error — don't clear. The second effect will
          // retry if serverReachable later toggles false → true.
        }
      }

      if (cancelled) return;

      // 2. If the app is configured for a remote server, skip Docker log
      //    scanning entirely. The local container's admin token is different
      //    from the remote server's token and must not overwrite it.
      if (useRemote) return;

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
  }, [qc, useRemote]);

  // ── Stale-token validation (fires when server becomes reachable) ───────
  // Validates the cached token once per session against POST /api/auth/login
  // (a public endpoint). If the server rejects it, the token is cleared so
  // the user gets a clean "Auth token not configured" prompt.
  //
  // This effect handles the case where the server becomes reachable AFTER
  // init() has already seeded the token. The inline validation in init()
  // handles the case where the server is already reachable on mount.
  useEffect(() => {
    if (!serverReachable || validatedRef.current || !knownTokenRef.current) return;

    let cancelled = false;

    apiClient
      .login(knownTokenRef.current)
      .then((result) => {
        if (cancelled) return;
        validatedRef.current = true;

        if (!result.success) {
          // Token is stale — clear it everywhere.
          const api = (window as any).electronAPI;
          knownTokenRef.current = '';
          api?.config?.set?.('connection.authToken', '').catch(() => {});
          apiClient.setAuthToken(null);
          qc.setQueryData(['authToken'], '');
          qc.invalidateQueries({ queryKey: ['adminStatus'] });
        }
      })
      .catch(() => {
        // Server/network error — don't clear the token. If serverReachable
        // later toggles false → true, this effect re-fires and retries.
      });

    return () => {
      cancelled = true;
    };
  }, [serverReachable, qc]);
}
