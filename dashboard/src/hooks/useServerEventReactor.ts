import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ServerConnectionInfo } from './useServerStatus';

/**
 * Watches `serverConnection` for state transitions and cascades
 * React Query cache invalidations to dependent queries so every
 * UI element stays current without manual intervention.
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
    }

    prev.current = cur;
  }, [serverConnection.reachable, serverConnection.ready, qc]);
}
