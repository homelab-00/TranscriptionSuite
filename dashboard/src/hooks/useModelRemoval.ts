import { useCallback } from 'react';
import { toast } from 'sonner';
import { getModelsByFamily } from '../services/modelRegistry';

interface UseModelRemovalOptions {
  isMetal: boolean;
  runtimeProfile: string;
  refreshCacheStatus: (ids: readonly string[]) => void;
}

export interface UseModelRemovalResult {
  removeModel: (id: string) => Promise<void>;
}

function isGgmlModel(modelId: string): boolean {
  return !!getModelsByFamily('whispercpp').find((m) => m.id === modelId);
}

/**
 * Removes cached model weights across the three storage paths.
 *
 * Metal has no container: removal goes through the MLX bridge straight to the
 * host filesystem. Docker keeps the cache inside the container. vulkan-wsl2
 * keeps GGML (whisper.cpp) weights in a separate Windows-host cache; removing
 * a host-side GGML model is not wired through IPC, so that path tells the user
 * to delete it by hand instead of failing quietly.
 *
 * There is no download counterpart: missing weights are downloaded
 * automatically at server start (the backend fetches HuggingFace models on
 * load, and dockerManager pre-pulls host-side GGML weights on vulkan-wsl2).
 */
export function useModelRemoval({
  isMetal,
  runtimeProfile,
  refreshCacheStatus,
}: UseModelRemovalOptions): UseModelRemovalResult {
  const isVulkanWsl2 = runtimeProfile === 'vulkan-wsl2';

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

  return { removeModel };
}
