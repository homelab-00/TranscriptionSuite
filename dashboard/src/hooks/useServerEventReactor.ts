import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ServerConnectionInfo } from './useServerStatus';
import { useNotificationsStore } from '../stores/notificationsStore';
import { SERVER_START_ID } from '../utils/startupEventMapping';

/**
 * Watches `serverConnection` for state transitions and cascades
 * React Query cache invalidations to dependent queries so every
 * UI element stays current without manual intervention.
 * Also completes the "Starting server" notification if the JSONL
 * server-ready event never arrived (broken bind mount fallback).
 */
export function useServerEventReactor(serverConnection: ServerConnectionInfo): void {
  const qc = useQueryClient();
  const prev = useRef({ reachable: false, ready: false });

  useEffect(() => {
    const cur = { reachable: serverConnection.reachable, ready: serverConnection.ready };

    // Server became reachable
    if (cur.reachable && !prev.current.reachable) {
      void qc.invalidateQueries({ queryKey: ['adminStatus'] });
      void qc.invalidateQueries({ queryKey: ['languages'] });
    }

    // Models became ready
    if (cur.ready && !prev.current.ready) {
      void qc.invalidateQueries({ queryKey: ['languages'] });
      void qc.invalidateQueries({ queryKey: ['adminStatus'] });

      // Fallback completion for the startup notification: only if a start is
      // still tracked as active (the JSONL server-ready event is primary).
      const entries = useNotificationsStore.getState().notifications;
      const newestStart = [...entries].reverse().find((n) => n.id === SERVER_START_ID);
      if (newestStart?.status === 'active') {
        useNotificationsStore.getState().notify({
          id: SERVER_START_ID,
          category: 'server',
          title: 'Server ready',
          status: 'complete',
          progress: 100,
        });
      }
    }

    prev.current = cur;
  }, [serverConnection.reachable, serverConnection.ready, qc]);
}
