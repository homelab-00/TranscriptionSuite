import React, { useState, useCallback, useEffect } from 'react';
import { ModelManagerTab } from './ModelManagerTab';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { isMLXModel } from '../../src/services/modelCapabilities';
import {
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  resolveMainModelSelectionValue,
} from '../../src/services/modelSelection';

const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';
const MLX_DEFAULT_MODEL = 'mlx-community/parakeet-tdt-0.6b-v3';

export const ModelManagerView: React.FC = () => {
  const docker = useDockerContext();

  // Model selection state — reads/writes the same electron-store keys as ServerView
  const [mainModelSelection, setMainModelSelection] = useState(MODEL_DEFAULT_LOADING_PLACEHOLDER);
  const [mainCustomModel, setMainCustomModel] = useState('');
  const [liveModelSelection, setLiveModelSelection] = useState(LIVE_MODEL_SAME_AS_MAIN_OPTION);
  const [liveCustomModel, setLiveCustomModel] = useState('');
  const [diarizationModelSelection, setDiarizationModelSelection] =
    useState(DIARIZATION_DEFAULT_MODEL);
  const [diarizationCustomModel, setDiarizationCustomModel] = useState('');
  const [runtimeProfile, setRuntimeProfile] = useState<string>('docker');
  const [hydrated, setHydrated] = useState(false);

  const [modelCacheStatus, setModelCacheStatus] = useState<
    Record<string, { exists: boolean; size?: string }>
  >({});

  const [mlxStatus, setMlxStatus] = useState<string>('stopped');

  // On the Metal (bare-metal) profile there is no Docker container, so the
  // Model Manager's "running" signal comes from the MLX server status instead
  // of docker.container.running (which is permanently false on Metal — GH-136).
  const isMetal = runtimeProfile === 'metal';
  const isRunning = isMetal ? mlxStatus === 'running' : docker.container.running;

  // Track MLX server status for the running signal above (Metal profile).
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.mlx?.getStatus) return;
    let active = true;
    api.mlx
      .getStatus()
      .then((s: string) => {
        if (active) setMlxStatus(s);
      })
      .catch(() => {});
    const unsub = api.mlx.onStatusChanged?.((s: string) => setMlxStatus(s));
    return () => {
      active = false;
      if (typeof unsub === 'function') unsub();
    };
  }, []);

  // Load persisted selections from electron store on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.config) {
      setHydrated(true);
      return;
    }

    let active = true;
    Promise.all([
      api.config.get('server.mainModelSelection'),
      api.config.get('server.mainCustomModel'),
      api.config.get('server.liveModelSelection'),
      api.config.get('server.liveCustomModel'),
      api.config.get('server.diarizationModelSelection'),
      api.config.get('server.diarizationCustomModel'),
      api.config.get('server.runtimeProfile'),
    ])
      .then(
        ([main, mainCustom, live, liveCustom, diarization, diarizationCustom, rt]: unknown[]) => {
          if (!active) return;
          if (typeof main === 'string' && main.trim()) setMainModelSelection(main.trim());
          if (typeof mainCustom === 'string') setMainCustomModel(mainCustom.trim());
          if (typeof live === 'string' && live.trim()) setLiveModelSelection(live.trim());
          if (typeof liveCustom === 'string') setLiveCustomModel(liveCustom.trim());
          if (typeof diarization === 'string' && diarization.trim())
            setDiarizationModelSelection(diarization.trim());
          if (typeof diarizationCustom === 'string')
            setDiarizationCustomModel(diarizationCustom.trim());
          if (typeof rt === 'string' && rt.trim()) setRuntimeProfile(rt.trim());
        },
      )
      .catch(() => {})
      .finally(() => {
        if (active) setHydrated(true);
      });

    return () => {
      active = false;
    };
  }, []);

  // Metal mode: auto-switch a non-MLX main model to the MLX default.
  useEffect(() => {
    if (!hydrated || runtimeProfile !== 'metal') return;
    const resolved = resolveMainModelSelectionValue(mainModelSelection, mainCustomModel, '');
    if (resolved && !isMLXModel(resolved) && resolved !== MODEL_DEFAULT_LOADING_PLACEHOLDER) {
      setMainModelSelection(MLX_DEFAULT_MODEL);
      setMainCustomModel('');
    }
  }, [runtimeProfile, hydrated, mainModelSelection, mainCustomModel]);

  // Persist changes back to the shared electron-store keys
  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config?.set('server.mainModelSelection', mainModelSelection)?.catch?.(() => {});
  }, [hydrated, mainModelSelection]);

  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config?.set('server.mainCustomModel', mainCustomModel)?.catch?.(() => {});
  }, [hydrated, mainCustomModel]);

  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config?.set('server.liveModelSelection', liveModelSelection)?.catch?.(() => {});
  }, [hydrated, liveModelSelection]);

  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config?.set('server.liveCustomModel', liveCustomModel)?.catch?.(() => {});
  }, [hydrated, liveCustomModel]);

  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config
      ?.set('server.diarizationModelSelection', diarizationModelSelection)
      ?.catch?.(() => {});
  }, [hydrated, diarizationModelSelection]);

  useEffect(() => {
    if (!hydrated) return;
    const api = (window as any).electronAPI;
    void api?.config
      ?.set('server.diarizationCustomModel', diarizationCustomModel)
      ?.catch?.(() => {});
  }, [hydrated, diarizationCustomModel]);

  const refreshCacheStatus = useCallback(
    (extraIds?: string[]) => {
      const api = (window as any).electronAPI;
      const modelIds = [...new Set(extraIds ?? [])].filter(Boolean);
      if (modelIds.length === 0) return;

      const apply = (result: Record<string, { exists: boolean; size?: string }>) => {
        setModelCacheStatus((prev) => ({ ...prev, ...result }));
      };

      if (isMetal) {
        // Metal: pure host-filesystem check — works whether or not the server runs.
        if (!api?.mlx?.checkModelsCached) return;
        api.mlx
          .checkModelsCached(modelIds)
          .then(apply)
          .catch(() => {});
        return;
      }
      // Docker: cache lives inside the container, so it must be running.
      if (!api?.docker?.checkModelsCached || !isRunning) return;
      api.docker
        .checkModelsCached(modelIds)
        .then(apply)
        .catch(() => {});
    },
    [isRunning, isMetal],
  );

  return (
    <div className="custom-scrollbar h-full w-full overflow-y-auto">
      <div className="mx-auto flex max-w-4xl flex-col space-y-6 p-6 pt-8 pb-10">
        <div className="flex flex-none items-center pt-2">
          <div>
            <h1 className="mb-2 text-3xl font-bold tracking-tight text-white">Model Manager</h1>
            <p className="-mt-1 text-slate-400">Browse, download, and manage model weights.</p>
          </div>
        </div>

        <ModelManagerTab
          mainModelSelection={mainModelSelection}
          setMainModelSelection={setMainModelSelection}
          mainCustomModel={mainCustomModel}
          setMainCustomModel={setMainCustomModel}
          liveModelSelection={liveModelSelection}
          setLiveModelSelection={setLiveModelSelection}
          liveCustomModel={liveCustomModel}
          setLiveCustomModel={setLiveCustomModel}
          diarizationModelSelection={diarizationModelSelection}
          setDiarizationModelSelection={setDiarizationModelSelection}
          diarizationCustomModel={diarizationCustomModel}
          setDiarizationCustomModel={setDiarizationCustomModel}
          modelCacheStatus={modelCacheStatus}
          isRunning={isRunning}
          refreshCacheStatus={refreshCacheStatus}
          isMetal={isMetal}
        />
      </div>
    </div>
  );
};
