import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import type { AdminStatus } from '../api/types';

export interface AdminStatusState {
  status: AdminStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useAdminStatus(pollInterval = 10_000, enabled = true): AdminStatusState {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['adminStatus'],
    queryFn: () => apiClient.getAdminStatus(),
    refetchInterval: pollInterval,
    enabled,
  });

  return {
    status: data ?? null,
    loading: isLoading,
    error: error instanceof Error ? error.message : error ? 'Failed to load admin status' : null,
    refresh: () => void refetch(),
  };
}
