/**
 * useDocker — reactive hook for Docker state.
 *
 * Polls container status, caches image list and volume info,
 * and exposes action methods wired to Electron IPC.
 *
 * Falls back gracefully when not running in Electron.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ─── Types (mirrors electron.d.ts shapes) ───────────────────────────────────

export interface DockerImage {
  tag: string;
  fullName: string;
  size: string;
  created: string;
  id: string;
}

export interface ContainerStatus {
  exists: boolean;
  running: boolean;
  status: string;
  health?: string;
  startedAt?: string;
}

export interface VolumeInfo {
  name: string;
  label: string;
  driver: string;
  mountpoint: string;
  size?: string;
}

export interface UseDockerReturn {
  available: boolean;
  loading: boolean;

  // Image state
  images: DockerImage[];
  refreshImages: () => Promise<void>;
  pullImage: (tag: string) => Promise<void>;
  removeImage: (tag: string) => Promise<void>;

  // Container state
  container: ContainerStatus;
  startContainer: (mode: 'local' | 'remote', env?: Record<string, string>) => Promise<void>;
  stopContainer: () => Promise<void>;
  removeContainer: () => Promise<void>;

  // Volume state
  volumes: VolumeInfo[];
  refreshVolumes: () => Promise<void>;
  removeVolume: (name: string) => Promise<void>;

  // Log streaming
  logLines: string[];
  logStreaming: boolean;
  startLogStream: (tail?: number) => void;
  stopLogStream: () => void;
  clearLogs: () => void;

  // Operation feedback
  operating: boolean;
  operationError: string | null;
}

const api = () => (window as any).electronAPI?.docker as ElectronAPI['docker'] | undefined;

const EMPTY_CONTAINER: ContainerStatus = { exists: false, running: false, status: 'unknown' };

export function useDocker(): UseDockerReturn {
  const [available, setAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [images, setImages] = useState<DockerImage[]>([]);
  const [container, setContainer] = useState<ContainerStatus>(EMPTY_CONTAINER);
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [operating, setOperating] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  // Initial discovery
  useEffect(() => {
    const docker = api();
    if (!docker) {
      setLoading(false);
      return;
    }

    (async () => {
      try {
        const ok = await docker.available();
        setAvailable(ok);
        if (ok) {
          const [imgs, status, vols] = await Promise.all([
            docker.listImages(),
            docker.getContainerStatus(),
            docker.getVolumes(),
          ]);
          setImages(imgs);
          setContainer(status);
          setVolumes(vols);
        }
      } catch {
        setAvailable(false);
      } finally {
        setLoading(false);
      }
    })();

    // Poll container status every 10s
    pollRef.current = setInterval(async () => {
      const d = api();
      if (!d) return;
      try {
        const status = await d.getContainerStatus();
        setContainer(status);
      } catch { /* ignore */ }
    }, 10_000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const refreshImages = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    const imgs = await docker.listImages();
    setImages(imgs);
  }, []);

  const refreshVolumes = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    const vols = await docker.getVolumes();
    setVolumes(vols);
  }, []);

  const withOperation = useCallback(async (fn: () => Promise<unknown>) => {
    setOperating(true);
    setOperationError(null);
    try {
      await fn();
    } catch (err: any) {
      setOperationError(err.message || 'Operation failed');
    } finally {
      setOperating(false);
    }
  }, []);

  const pullImage = useCallback(async (tag: string) => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.pullImage(tag);
      await refreshImages();
    });
  }, [withOperation, refreshImages]);

  const removeImage = useCallback(async (tag: string) => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.removeImage(tag);
      await refreshImages();
    });
  }, [withOperation, refreshImages]);

  const startContainer = useCallback(async (mode: 'local' | 'remote', env?: Record<string, string>) => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.startContainer(mode, env);
      // Wait a moment then refresh status
      await new Promise(r => setTimeout(r, 2000));
      setContainer(await docker.getContainerStatus());
    });
  }, [withOperation]);

  const stopContainer = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.stopContainer();
      await new Promise(r => setTimeout(r, 1000));
      setContainer(await docker.getContainerStatus());
    });
  }, [withOperation]);

  const removeContainer = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.removeContainer();
      await new Promise(r => setTimeout(r, 1000));
      setContainer(await docker.getContainerStatus());
    });
  }, [withOperation]);

  const removeVolume = useCallback(async (name: string) => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.removeVolume(name);
      await refreshVolumes();
    });
  }, [withOperation, refreshVolumes]);

  // ─── Log Streaming ─────────────────────────────────────────────────────────

  const [logLines, setLogLines] = useState<string[]>([]);
  const [logStreaming, setLogStreaming] = useState(false);
  const logCleanupRef = useRef<(() => void) | null>(null);

  const startLogStream = useCallback((tail?: number) => {
    const docker = api();
    if (!docker) return;

    // Stop any existing stream first
    if (logCleanupRef.current) logCleanupRef.current();

    setLogLines([]);
    setLogStreaming(true);

    docker.startLogStream(tail);
    const cleanup = docker.onLogLine((line: string) => {
      setLogLines(prev => {
        const next = [...prev, line];
        // Keep a rolling buffer of 1000 lines
        return next.length > 1000 ? next.slice(-1000) : next;
      });
    });

    logCleanupRef.current = () => {
      cleanup();
      docker.stopLogStream();
      setLogStreaming(false);
    };
  }, []);

  const stopLogStream = useCallback(() => {
    if (logCleanupRef.current) {
      logCleanupRef.current();
      logCleanupRef.current = null;
    }
  }, []);

  const clearLogs = useCallback(() => {
    setLogLines([]);
  }, []);

  // Cleanup log stream on unmount
  useEffect(() => {
    return () => {
      if (logCleanupRef.current) logCleanupRef.current();
    };
  }, []);

  return {
    available,
    loading,
    images,
    refreshImages,
    pullImage,
    removeImage,
    container,
    startContainer,
    stopContainer,
    removeContainer,
    volumes,
    refreshVolumes,
    removeVolume,
    logLines,
    logStreaming,
    startLogStream,
    stopLogStream,
    clearLogs,
    operating,
    operationError,
  };
}
