/**
 * useBackups — fetches the list of database backups.
 */

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import type { BackupInfo } from '../api/types';

export interface BackupsState {
  backups: BackupInfo[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
  createBackup: () => Promise<void>;
  restoreBackup: (filename: string) => Promise<void>;
  /** True while a create/restore operation is in flight */
  operating: boolean;
  /** Result message from last create/restore */
  operationResult: string | null;
}

export function useBackups(): BackupsState {
  const queryClient = useQueryClient();
  const [operationResult, setOperationResult] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['backups'],
    queryFn: () => apiClient.listBackups(),
  });

  const createMutation = useMutation({
    mutationFn: () => apiClient.createBackup(),
    onSuccess: (res) => {
      setOperationResult(res.message);
      void queryClient.invalidateQueries({ queryKey: ['backups'] });
    },
    onError: (err) => {
      setOperationResult(err instanceof Error ? err.message : 'Backup failed');
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (filename: string) => apiClient.restoreBackup(filename),
    onSuccess: (res) => {
      setOperationResult(res.message);
    },
    onError: (err) => {
      setOperationResult(err instanceof Error ? err.message : 'Restore failed');
    },
  });

  const operating = createMutation.isPending || restoreMutation.isPending;

  return {
    backups: data?.backups ?? [],
    loading: isLoading,
    error: error instanceof Error ? error.message : error ? 'Failed to load backups' : null,
    refresh: () => void refetch(),
    createBackup: async () => {
      await createMutation.mutateAsync();
    },
    restoreBackup: async (filename) => {
      await restoreMutation.mutateAsync(filename);
    },
    operating,
    operationResult,
  };
}
