/**
 * useDocker — reactive hook for Docker state.
 *
 * Polls container status, caches image list and volume info,
 * and exposes action methods wired to Electron IPC.
 *
 * Falls back gracefully when not running in Electron.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { RuntimeProfile } from '../types/runtime';

// ─── Types (mirrors electron.d.ts shapes) ───────────────────────────────────

export interface RemoteTag {
  tag: string;
  created: string | null;
}

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

export type HfTokenDecision = 'unset' | 'provided' | 'skipped';

export interface StartContainerOnboardingOptions {
  hfTokenDecision?: HfTokenDecision;
  installWhisper?: boolean;
  installNemo?: boolean;
  installVibeVoiceAsr?: boolean;
  mainTranscriberModel?: string;
  liveTranscriberModel?: string;
  diarizationModel?: string;
  whispercppModel?: string;
}

export interface CleanAllOptions {
  keepDataVolume: boolean;
  keepModelsVolume: boolean;
  keepConfigDirectory: boolean;
}

export interface UseDockerReturn {
  available: boolean;
  loading: boolean;
  /** Detected runtime display name ('Docker' or 'Podman'), null if not detected */
  runtimeKind: string | null;
  /** Actionable guidance when detection fails (e.g. Podman socket not active) */
  detectionGuidance: string | null;
  /** Whether the compose plugin is available for the detected runtime */
  composeAvailable: boolean;

  // Image state
  images: DockerImage[];
  refreshImages: () => Promise<void>;
  pullImage: (tag: string) => Promise<void>;
  cancelPull: () => Promise<void>;
  pulling: boolean;
  removeImage: (tag: string) => Promise<void>;

  // Remote tags (GHCR registry)
  remoteTags: RemoteTag[];
  /**
   * GH-83: tri-state status from the last `listRemoteTags` probe.
   *   - `null`      : never probed (initial mount, or not in Electron)
   *   - `'ok'`      : registry responded with a tag list (may be empty for an
   *                   *existing* but freshly created tagless package)
   *   - `'not-published'`: registry returned 404 on `/v2/<pkg>/tags/list` —
   *                   the package exists in the namespace but has no tags.
   *                   Realistic first-release state for the `-legacy` repo
   *                   until `docker-build-push.sh --variant legacy` has run.
   *   - `'error'`   : network/HTTP failure other than 404.
   *
   * Callers distinguish these to render dedicated UI affordances instead of
   * the pre-GH-83 "empty chip row + silent updater" failure mode.
   */
  remoteTagsStatus: 'ok' | 'not-published' | 'error' | null;
  refreshRemoteTags: () => Promise<void>;

  // Sidecar image state
  hasSidecarImage: () => Promise<boolean>;
  pullSidecarImage: () => Promise<void>;
  cancelSidecarPull: () => Promise<void>;
  sidecarPulling: boolean;

  // Container state
  container: ContainerStatus;
  startContainer: (
    mode: 'local' | 'remote',
    runtimeProfile?: RuntimeProfile,
    tlsEnv?: Record<string, string>,
    imageTag?: string,
    hfToken?: string,
    onboardingOptions?: StartContainerOnboardingOptions,
  ) => Promise<void>;
  stopContainer: () => Promise<void>;
  removeContainer: () => Promise<void>;

  // Volume state
  volumes: VolumeInfo[];
  refreshVolumes: () => Promise<void>;
  removeVolume: (name: string) => Promise<void>;
  cleanAll: (options: CleanAllOptions) => Promise<void>;

  // Log streaming
  logLines: string[];
  logStreaming: boolean;
  startLogStream: (tail?: number) => void;
  stopLogStream: () => void;
  clearLogs: () => void;

  // Operation feedback
  operating: boolean;
  operationError: string | null;

  // Re-run Docker availability and image detection
  retryDetection: () => Promise<void>;
}

const api = () => (window as any).electronAPI?.docker as ElectronAPI['docker'] | undefined;
const appApi = () => (window as any).electronAPI?.app as ElectronAPI['app'] | undefined;

const EMPTY_CONTAINER: ContainerStatus = { exists: false, running: false, status: 'unknown' };

export function useDocker(): UseDockerReturn {
  const [available, setAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [runtimeKind, setRuntimeKind] = useState<string | null>(null);
  const [detectionGuidance, setDetectionGuidance] = useState<string | null>(null);
  const [composeAvailable, setComposeAvailable] = useState(true);
  const [images, setImages] = useState<DockerImage[]>([]);
  const [container, setContainer] = useState<ContainerStatus>(EMPTY_CONTAINER);
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [operating, setOperating] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [pulling, setPulling] = useState(false);
  const [sidecarPulling, setSidecarPulling] = useState(false);
  const [remoteTags, setRemoteTags] = useState<RemoteTag[]>([]);
  const [remoteTagsStatus, setRemoteTagsStatus] = useState<'ok' | 'not-published' | 'error' | null>(
    null,
  );

  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const volumeRefreshedOnHealthyRef = useRef(false);

  // Initial discovery
  useEffect(() => {
    const docker = api();
    if (!docker) {
      setLoading(false);
      return;
    }

    (async () => {
      try {
        const [ok, guidance, compose] = await Promise.all([
          docker.available(),
          docker.getDetectionGuidance().catch(() => null),
          docker.getComposeAvailable().catch(() => true),
        ]);
        setAvailable(ok);
        setDetectionGuidance(guidance);
        // When Docker is completely absent, compose is also unavailable.
        // getComposeAvailable() returns true for the ambiguous null state, so
        // we must explicitly set false here to keep the Start buttons disabled.
        setComposeAvailable(ok ? compose : false);
        if (ok) {
          docker
            .getRuntimeKind()
            .then(setRuntimeKind)
            .catch(() => {});
          const [imgs, status, vols] = await Promise.all([
            docker.listImages(),
            docker.getContainerStatus(),
            docker.getVolumes(),
          ]);
          setImages(imgs);
          setContainer(status);
          setVolumes(vols);

          // Only start polling if Docker is actually available
          pollRef.current = setInterval(async () => {
            const d = api();
            if (!d) return;
            try {
              const [st, im] = await Promise.all([d.getContainerStatus(), d.listImages()]);
              setContainer(st);
              setImages(im);

              // Auto-refresh volume sizes once when the server first reports healthy
              if (st.health === 'healthy' && !volumeRefreshedOnHealthyRef.current) {
                volumeRefreshedOnHealthyRef.current = true;
                d.getVolumes()
                  .then((vols2) => setVolumes(vols2))
                  .catch(() => {});
              }
              // Reset flag when container stops so it triggers again on next startup
              if (!st.running) {
                volumeRefreshedOnHealthyRef.current = false;
              }
            } catch {
              /* ignore */
            }
          }, 10_000);
        }
      } catch {
        setAvailable(false);
      } finally {
        setLoading(false);
      }
    })();

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

  const refreshRemoteTags = useCallback(async () => {
    const docker = api();
    if (!docker?.listRemoteTags) return;
    try {
      // Step 1: fetch tag list (fast, ~1-2s) — UI shows chips immediately
      const result = await docker.listRemoteTags();
      setRemoteTags(result.tags);
      setRemoteTagsStatus(result.status);

      // Step 2: fetch dates in background (slow, ~5-8s) — chips update with dates.
      // Only meaningful when we actually have tags (status === 'ok' and non-empty).
      if (result.status === 'ok' && result.tags.length > 0 && docker.fetchRemoteTagDates) {
        const tagNames = result.tags.map((t) => t.tag);
        docker
          .fetchRemoteTagDates(tagNames)
          .then((dates) => {
            setRemoteTags((prev) =>
              prev.map((rt) => ({
                ...rt,
                created: dates[rt.tag] ?? rt.created,
              })),
            );
          })
          .catch(() => {
            /* best-effort */
          });
      }
    } catch {
      setRemoteTags([]);
      setRemoteTagsStatus('error');
    }
  }, []);

  // Fetch remote tags once on mount (tags change rarely — no need to poll)
  useEffect(() => {
    refreshRemoteTags();
  }, [refreshRemoteTags]);

  const refreshVolumes = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    const vols = await docker.getVolumes();
    setVolumes(vols);
  }, []);

  /**
   * Re-run container runtime detection from scratch (resets Docker/Podman cache).
   * Useful when the runtime was started after the app launched, or detection failed
   * due to a transient issue (e.g. daemon not ready yet).
   */
  const retryDetection = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    setLoading(true);
    setOperationError(null);
    try {
      const ok = await docker.retryDetection();
      const [guidance, compose] = await Promise.all([
        docker.getDetectionGuidance().catch(() => null),
        docker.getComposeAvailable().catch(() => true),
      ]);
      setAvailable(ok);
      setDetectionGuidance(guidance);
      setComposeAvailable(compose);
      if (ok) {
        docker
          .getRuntimeKind()
          .then(setRuntimeKind)
          .catch(() => {});
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

  const pullImage = useCallback(
    async (tag: string) => {
      const docker = api();
      if (!docker) return;
      setPulling(true);
      await withOperation(async () => {
        try {
          await docker.pullImage(tag);
          await refreshImages();
        } finally {
          setPulling(false);
        }
      });
    },
    [withOperation, refreshImages],
  );

  const cancelPull = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await docker.cancelPull();
    setPulling(false);
    setOperating(false);
  }, []);

  const hasSidecarImage = useCallback(async (): Promise<boolean> => {
    const docker = api();
    if (!docker) return false;
    return docker.hasSidecarImage();
  }, []);

  const pullSidecarImage = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    setSidecarPulling(true);
    await withOperation(async () => {
      try {
        await docker.pullSidecarImage();
      } finally {
        setSidecarPulling(false);
      }
    });
  }, [withOperation]);

  const cancelSidecarPull = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await docker.cancelSidecarPull();
    setSidecarPulling(false);
    setOperating(false);
    setOperationError(null);
  }, []);

  const removeImage = useCallback(
    async (tag: string) => {
      const docker = api();
      if (!docker) return;
      await withOperation(async () => {
        await docker.removeImage(tag);
        await refreshImages();
      });
    },
    [withOperation, refreshImages],
  );

  const startContainer = useCallback(
    async (
      mode: 'local' | 'remote',
      runtimeProfile: RuntimeProfile = 'cpu',
      tlsEnv?: Record<string, string>,
      imageTag?: string,
      hfToken?: string,
      onboardingOptions?: StartContainerOnboardingOptions,
    ) => {
      const docker = api();
      if (!docker) return;
      await withOperation(async () => {
        await docker.startContainer({
          mode,
          runtimeProfile,
          tlsEnv,
          imageTag,
          hfToken,
          ...onboardingOptions,
        });
        // Wait a moment then refresh status
        await new Promise((r) => setTimeout(r, 2000));
        setContainer(await docker.getContainerStatus());
      });
    },
    [withOperation],
  );

  const stopContainer = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.stopContainer();
      await new Promise((r) => setTimeout(r, 1000));
      setContainer(await docker.getContainerStatus());
    });
  }, [withOperation]);

  const removeContainer = useCallback(async () => {
    const docker = api();
    if (!docker) return;
    await withOperation(async () => {
      await docker.removeContainer();
      await new Promise((r) => setTimeout(r, 1000));
      setContainer(await docker.getContainerStatus());
    });
  }, [withOperation]);

  const removeVolume = useCallback(
    async (name: string) => {
      const docker = api();
      if (!docker) return;
      await withOperation(async () => {
        await docker.removeVolume(name);
        await refreshVolumes();
      });
    },
    [withOperation, refreshVolumes],
  );

  const cleanAll = useCallback(
    async (options: CleanAllOptions) => {
      const docker = api();
      const app = appApi();
      if (!docker) return;

      await withOperation(async () => {
        const [localImages, localVolumes] = await Promise.all([
          docker.listImages(),
          docker.getVolumes(),
        ]);

        await docker.stopContainer();
        await docker.removeContainer();

        for (const image of localImages) {
          await docker.removeImage(image.tag);
        }

        const targetVolumes = new Set<string>(['transcriptionsuite-runtime']);
        if (!options.keepDataVolume) targetVolumes.add('transcriptionsuite-data');
        if (!options.keepModelsVolume) targetVolumes.add('transcriptionsuite-models');

        for (const volume of localVolumes) {
          if (!targetVolumes.has(volume.name)) continue;
          if (!volume.mountpoint) continue;
          await docker.removeVolume(volume.name);
        }

        if (!options.keepConfigDirectory && app?.removeConfigAndCache) {
          await app.removeConfigAndCache();
        }

        const [status, imagesAfterCleanup, volumesAfterCleanup] = await Promise.all([
          docker.getContainerStatus(),
          docker.listImages(),
          docker.getVolumes(),
        ]);
        setContainer(status);
        setImages(imagesAfterCleanup);
        setVolumes(volumesAfterCleanup);
      });
    },
    [withOperation],
  );

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
      setLogLines((prev) => {
        return [...prev, line];
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
    runtimeKind,
    detectionGuidance,
    composeAvailable,
    images,
    refreshImages,
    pullImage,
    cancelPull,
    pulling,
    remoteTags,
    remoteTagsStatus,
    refreshRemoteTags,
    hasSidecarImage,
    pullSidecarImage,
    cancelSidecarPull,
    sidecarPulling,
    removeImage,
    container,
    startContainer,
    stopContainer,
    removeContainer,
    volumes,
    refreshVolumes,
    removeVolume,
    cleanAll,
    logLines,
    logStreaming,
    startLogStream,
    stopLogStream,
    clearLogs,
    operating,
    operationError,
    retryDetection,
  };
}
