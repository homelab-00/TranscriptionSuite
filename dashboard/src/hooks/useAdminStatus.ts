/**
 * useAdminStatus — fetches admin status with model information.
 * Polls periodically like useServerStatus.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { AdminStatus } from '../api/types';

export interface AdminStatusState {
  status: AdminStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useAdminStatus(pollInterval = 10000, enabled = true): AdminStatusState {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetch = useCallback(async () => {
    try {
      const data = await apiClient.getAdminStatus();
      if (mountedRef.current) {
        setStatus(data);
        setError(null);
        setLoading(false);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load admin status');
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        mountedRef.current = false;
      };
    }
    fetch();
    const interval = setInterval(fetch, pollInterval);
    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, [fetch, pollInterval, enabled]);

  return { status, loading, error, refresh: fetch };
}
