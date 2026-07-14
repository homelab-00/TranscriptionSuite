import { useCallback, useState } from 'react';

export interface ModelCacheEntry {
  exists: boolean;
  size?: string;
}

export type ModelCacheStatus = Record<string, ModelCacheEntry>;

interface UseModelCacheOptions {
  isRunning: boolean;
  isMetal: boolean;
}

export interface UseModelCacheResult {
  modelCacheStatus: ModelCacheStatus;
  refreshCacheStatus: (modelIds: readonly string[]) => void;
}

/**
 * Tracks which model weights are present on disk.
 *
 * The probe differs by runtime. On Metal there is no container: the cache is a
 * plain host-filesystem check that works whether or not the server runs, and
 * docker.container.running is permanently false there (GH-136). On Docker the
 * cache lives inside the container, so it can only be read while it runs.
 */
export function useModelCache({ isRunning, isMetal }: UseModelCacheOptions): UseModelCacheResult {
  const [modelCacheStatus, setModelCacheStatus] = useState<ModelCacheStatus>({});

  const refreshCacheStatus = useCallback(
    (modelIds: readonly string[]) => {
      const api = (window as any).electronAPI;
      const ids = [...new Set(modelIds)].filter(Boolean);
      if (ids.length === 0) return;

      const apply = (result: ModelCacheStatus) => {
        setModelCacheStatus((prev) => ({ ...prev, ...result }));
      };

      if (isMetal) {
        if (!api?.mlx?.checkModelsCached) return;
        api.mlx
          .checkModelsCached(ids)
          .then(apply)
          .catch(() => {});
        return;
      }

      if (!api?.docker?.checkModelsCached || !isRunning) return;
      api.docker
        .checkModelsCached(ids)
        .then(apply)
        .catch(() => {});
    },
    [isRunning, isMetal],
  );

  return { modelCacheStatus, refreshCacheStatus };
}
