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

export function useAdminStatus(pollInterval = 10_000, enabled = true): AdminStatusState {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const prevJsonRef = useRef<string>('');

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiClient.getAdminStatus();
      if (mountedRef.current) {
        // Skip state update when the response is identical to the previous one
        const json = JSON.stringify(data);
        if (json !== prevJsonRef.current) {
          prevJsonRef.current = json;
          setStatus(data);
        }
        setError(null);
        setLoading(false);
      }
    } catch (err) {
      if (mountedRef.current) {
        const msg = err instanceof Error ? err.message : 'Failed to load admin status';
        if (msg !== prevJsonRef.current) {
          prevJsonRef.current = msg;
          setError(msg);
        }
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
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, [fetchStatus, pollInterval, enabled]);

  return { status, loading, error, refresh: fetchStatus };
}
