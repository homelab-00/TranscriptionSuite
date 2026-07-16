import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { getModelsByFamily } from '../services/modelRegistry';
import { useNotificationsStore } from '../stores/notificationsStore';

interface UseModelDownloadsOptions {
  isMetal: boolean;
  runtimeProfile: string;
  refreshCacheStatus: (ids: readonly string[]) => void;
  refreshHostCacheStatus: (ids: readonly string[]) => void;
}

export interface UseModelDownloadsResult {
  downloadingIds: ReadonlySet<string>;
  downloadModel: (id: string) => Promise<void>;
  removeModel: (id: string) => Promise<void>;
}

function isGgmlModel(modelId: string): boolean {
  return !!getModelsByFamily('whispercpp').find((m) => m.id === modelId);
}

/**
 * Downloads and removes model weights across the three storage paths.
 *
 * Metal has no container: downloads go through the MLX bridge straight to the
 * host filesystem. Docker keeps the cache inside the container. vulkan-wsl2
 * additionally sends GGML (whisper.cpp) weights to a separate Windows-host
 * cache with its own IPC calls and its own probe, because those weights cannot
 * live inside the container on WSL2. Removing a host-side GGML model is not
 * wired through IPC, so that path tells the user to delete it by hand instead
 * of failing quietly.
 */
export function useModelDownloads({
  isMetal,
  runtimeProfile,
  refreshCacheStatus,
  refreshHostCacheStatus,
}: UseModelDownloadsOptions): UseModelDownloadsResult {
  const isVulkanWsl2 = runtimeProfile === 'vulkan-wsl2';
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set());

  const downloadModel = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      const isWhisperCpp = isGgmlModel(modelId);
      // Metal has no container — use the native (host-local) cache path.
      const download = isMetal ? api?.mlx?.downloadModelToCache : api?.docker?.downloadModelToCache;
      if (!download) return;

      const notifId = `model-download-${modelId}`;
      const ggmlHostPath = isVulkanWsl2 && isWhisperCpp;
      // The GGML host download emits its own ggml-download-* events with real
      // byte progress (docker:downloadEvent channel), so it gets no hook-level
      // card — one download, one card.
      if (!ggmlHostPath) {
        useNotificationsStore.getState().notify({
          id: notifId,
          category: 'download',
          title: `Downloading ${modelId}...`,
          detail: 'Fetching model weights',
          status: 'active',
        });
      }

      setDownloadingIds((prev) => new Set(prev).add(modelId));
      try {
        if (ggmlHostPath) {
          if (!api?.docker?.downloadGgmlModelToHost) return;
          await api.docker.downloadGgmlModelToHost(modelId);
          await refreshHostCacheStatus([modelId]);
        } else {
          await download(modelId);
          useNotificationsStore.getState().notify({
            id: notifId,
            category: 'download',
            title: `Downloaded ${modelId}`,
            status: 'complete',
          });
          refreshCacheStatus([modelId]);
        }
      } catch (err: any) {
        const msg = err?.message || 'Unknown error';
        useNotificationsStore.getState().notify({
          id: notifId,
          category: 'download',
          title: `Download failed: ${modelId}`,
          status: 'error',
          error: msg,
        });
      } finally {
        setDownloadingIds((prev) => {
          const next = new Set(prev);
          next.delete(modelId);
          return next;
        });
      }
    },
    [isVulkanWsl2, isMetal, refreshCacheStatus, refreshHostCacheStatus],
  );

  const removeModel = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      const isWhisperCpp = isGgmlModel(modelId);

      try {
        if (isVulkanWsl2 && isWhisperCpp) {
          // Host-side removal is not yet supported via IPC; show guidance instead.
          toast.warning(`Delete manually from %APPDATA%\\TranscriptionSuite\\whisper-models\\`);
          return;
        }
        const remove = isMetal ? api?.mlx?.removeModelCache : api?.docker?.removeModelCache;
        if (!remove) return;
        await remove(modelId);
        toast.success(`Removed cache for ${modelId}`);
        refreshCacheStatus([modelId]);
      } catch (err: any) {
        toast.error(`Remove failed: ${err?.message || 'Unknown error'}`);
      }
    },
    [isVulkanWsl2, isMetal, refreshCacheStatus],
  );

  return { downloadingIds, downloadModel, removeModel };
}
