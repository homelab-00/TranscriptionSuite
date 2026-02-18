/**
 * useBackups — fetches the list of database backups.
 */

import { useState, useEffect, useCallback } from 'react';
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
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [operating, setOperating] = useState(false);
  const [operationResult, setOperationResult] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.listBackups();
      setBackups(data.backups);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load backups');
      setBackups([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const createBackup = useCallback(async () => {
    setOperating(true);
    setOperationResult(null);
    try {
      const res = await apiClient.createBackup();
      setOperationResult(res.message);
      await fetch(); // Refresh list
    } catch (err) {
      setOperationResult(err instanceof Error ? err.message : 'Backup failed');
    } finally {
      setOperating(false);
    }
  }, [fetch]);

  const restoreBackup = useCallback(async (filename: string) => {
    setOperating(true);
    setOperationResult(null);
    try {
      const res = await apiClient.restoreBackup(filename);
      setOperationResult(res.message);
    } catch (err) {
      setOperationResult(err instanceof Error ? err.message : 'Restore failed');
    } finally {
      setOperating(false);
    }
  }, []);

  return {
    backups,
    loading,
    error,
    refresh: fetch,
    createBackup,
    restoreBackup,
    operating,
    operationResult,
  };
}
