import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Box,
  Cpu,
  HardDrive,
  Download,
  Loader2,
  RefreshCw,
  Gpu,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Copy,
  Check,
  Eye,
  EyeOff,
  Users,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { CustomSelect } from '../ui/CustomSelect';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { apiClient } from '../../src/api/client';

type RuntimeProfile = 'gpu' | 'cpu';

interface ServerViewProps {
  onStartServer: (
    mode: 'local' | 'remote',
    runtimeProfile: RuntimeProfile,
    imageTag?: string,
  ) => Promise<void>;
  startupFlowPending: boolean;
}

const MODEL_DEFAULT_LOADING_PLACEHOLDER = 'Loading server default...';
const LIVE_ALTERNATE_MODEL = 'Systran/faster-whisper-medium';
const MAIN_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
const LIVE_MODEL_SAME_AS_MAIN_OPTION = 'Same as Main Transcriber';
const LIVE_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';
const DIARIZATION_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
const ACTIVE_CARD_ACCENT_CLASS = 'border-accent-cyan/40! shadow-[0_0_15px_rgba(34,211,238,0.2)]!';

function getString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

// Session-level GPU detection cache — survives view unmount/remount
let cachedGpuInfo: { gpu: boolean; toolkit: boolean } | null | undefined = undefined; // undefined = not yet checked

function normalizeModelName(value: string): string {
  return value.trim().toLowerCase();
}

export const ServerView: React.FC<ServerViewProps> = ({ onStartServer, startupFlowPending }) => {
  const { status: adminStatus } = useAdminStatus();
  const docker = useDockerContext();

  // Model selection state
  const [mainModelSelection, setMainModelSelection] = useState(MODEL_DEFAULT_LOADING_PLACEHOLDER);
  const [mainCustomModel, setMainCustomModel] = useState('');
  const [liveModelSelection, setLiveModelSelection] = useState(LIVE_MODEL_SAME_AS_MAIN_OPTION);
  const [liveCustomModel, setLiveCustomModel] = useState('');
  const [modelsHydrated, setModelsHydrated] = useState(false);
  const [diarizationModelSelection, setDiarizationModelSelection] =
    useState(DIARIZATION_DEFAULT_MODEL);
  const [diarizationCustomModel, setDiarizationCustomModel] = useState('');
  const [diarizationHydrated, setDiarizationHydrated] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Model download cache state (checks Docker volume for HF model dirs)
  const [modelCacheStatus, setModelCacheStatus] = useState<Record<string, { exists: boolean }>>({});
  const modelCacheCheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Runtime profile (persisted in electron-store)
  const [runtimeProfile, setRuntimeProfile] = useState<RuntimeProfile>('gpu');

  // Auth token display in Instance Settings
  const [showAuthToken, setShowAuthToken] = useState(false);
  const [authTokenCopied, setAuthTokenCopied] = useState(false);
  const [authToken, setAuthToken] = useState('');

  // Load persisted runtime profile and auth token on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('server.runtimeProfile')
        .then((val: unknown) => {
          if (val === 'gpu' || val === 'cpu') setRuntimeProfile(val);
        })
        .catch(() => {});
      api.config
        .get('client.authToken')
        .then((val: unknown) => {
          if (typeof val === 'string') setAuthToken(val);
        })
        .catch(() => {});
    }
  }, []);

  // Persist runtime profile changes
  const handleRuntimeProfileChange = useCallback((profile: RuntimeProfile) => {
    setRuntimeProfile(profile);
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config.set('server.runtimeProfile', profile);
    }
  }, []);

  // Derive status from Docker hook
  const containerStatus = docker.container;
  const isRunning = containerStatus.running;
  const isRunningAndHealthy = isRunning && containerStatus.health === 'healthy';
  const hasImages = docker.images.length > 0;
  const statusLabel = containerStatus.exists
    ? containerStatus.status.charAt(0).toUpperCase() + containerStatus.status.slice(1)
    : 'Not Found';

  // Resolve configured model names from admin status payload (new + legacy shapes)
  const adminConfig = (adminStatus?.config ?? {}) as Record<string, unknown>;
  const adminMainCfg = (adminConfig.main_transcriber ?? {}) as Record<string, unknown>;
  const adminLiveCfg = (adminConfig.live_transcriber ??
    adminConfig.live_transcription ??
    {}) as Record<string, unknown>;
  const adminDiarizationCfg = (adminConfig.diarization ?? {}) as Record<string, unknown>;
  const adminLegacyTranscriptionCfg = (adminConfig.transcription ?? {}) as Record<string, unknown>;
  const adminModels = (adminStatus?.models ?? {}) as Record<string, unknown>;
  const adminModelTranscription = (adminModels.transcription ?? {}) as Record<string, unknown>;
  const adminModelTranscriptionCfg = (adminModelTranscription.config ?? {}) as Record<
    string,
    unknown
  >;
  const adminModelDiarization = (adminModels.diarization ?? {}) as Record<string, unknown>;
  const adminModelDiarizationCfg = (adminModelDiarization.config ?? {}) as Record<string, unknown>;

  const configuredMainModel =
    getString(adminMainCfg.model) ??
    getString(adminLegacyTranscriptionCfg.model) ??
    getString(adminModelTranscriptionCfg.model) ??
    '';
  const configuredLiveModel = getString(adminLiveCfg.model) ?? configuredMainModel;
  const configuredDiarizationModel =
    getString(adminDiarizationCfg.model) ??
    getString(adminModelDiarizationCfg.model) ??
    getString(adminModelDiarization.model) ??
    '';

  useEffect(() => {
    if (modelsHydrated || !adminStatus || !configuredMainModel) return;

    const normalizedMain = normalizeModelName(configuredMainModel);
    setMainModelSelection(configuredMainModel);
    setMainCustomModel('');

    const normalizedLive = normalizeModelName(configuredLiveModel);
    if (normalizedLive === normalizedMain) {
      setLiveModelSelection(LIVE_MODEL_SAME_AS_MAIN_OPTION);
      setLiveCustomModel('');
    } else if (normalizedLive === normalizeModelName(LIVE_ALTERNATE_MODEL)) {
      setLiveModelSelection(LIVE_ALTERNATE_MODEL);
      setLiveCustomModel('');
    } else {
      setLiveModelSelection(LIVE_MODEL_CUSTOM_OPTION);
      setLiveCustomModel(configuredLiveModel);
    }

    setModelsHydrated(true);
  }, [adminStatus, configuredMainModel, configuredLiveModel, modelsHydrated]);

  useEffect(() => {
    if (diarizationHydrated || !adminStatus) return;

    if (
      configuredDiarizationModel &&
      normalizeModelName(configuredDiarizationModel) !==
        normalizeModelName(DIARIZATION_DEFAULT_MODEL)
    ) {
      setDiarizationModelSelection(DIARIZATION_MODEL_CUSTOM_OPTION);
      setDiarizationCustomModel(configuredDiarizationModel);
    } else {
      setDiarizationModelSelection(DIARIZATION_DEFAULT_MODEL);
      setDiarizationCustomModel('');
    }

    setDiarizationHydrated(true);
  }, [adminStatus, configuredDiarizationModel, diarizationHydrated]);

  const activeTranscriber =
    mainModelSelection === MAIN_MODEL_CUSTOM_OPTION
      ? mainCustomModel.trim() || configuredMainModel
      : configuredMainModel || mainModelSelection;
  const activeLiveModel =
    liveModelSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION
      ? activeTranscriber
      : liveModelSelection === LIVE_MODEL_CUSTOM_OPTION
        ? liveCustomModel.trim() || configuredLiveModel || activeTranscriber
        : LIVE_ALTERNATE_MODEL;

  // Active diarization model name
  const activeDiarizationModel =
    diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION
      ? diarizationCustomModel.trim() || configuredDiarizationModel || DIARIZATION_DEFAULT_MODEL
      : DIARIZATION_DEFAULT_MODEL;

  // Check model download cache whenever the active model names or container state change
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.docker?.checkModelsCached || !isRunning) return;

    // Collect unique model IDs to check
    const modelIds = [
      ...new Set([activeTranscriber, activeLiveModel, activeDiarizationModel]),
    ].filter((id) => id && id !== MODEL_DEFAULT_LOADING_PLACEHOLDER);
    if (modelIds.length === 0) return;

    // Debounce the check
    if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    modelCacheCheckRef.current = setTimeout(() => {
      api.docker
        .checkModelsCached(modelIds)
        .then((result: Record<string, { exists: boolean }>) => {
          setModelCacheStatus(result);
        })
        .catch(() => {});
    }, 500);

    return () => {
      if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    };
  }, [activeTranscriber, activeLiveModel, activeDiarizationModel, isRunning]);

  // Image selection state — "Most Recent (auto)" always picks the newest available tag
  const MOST_RECENT = 'Most Recent (auto)';
  const imageOptions =
    docker.images.length > 0
      ? [MOST_RECENT, ...docker.images.map((i) => i.fullName)]
      : ['ghcr.io/homelab-00/transcriptionsuite-server:latest'];
  const [selectedImage, setSelectedImage] = useState(imageOptions[0]);
  const resolvedImage =
    selectedImage === MOST_RECENT && docker.images.length > 0
      ? docker.images[0].fullName
      : selectedImage;
  const selectedTagForActions = resolvedImage.split(':').pop() || 'latest';
  const selectedTagForStart = docker.images.length > 0 ? selectedTagForActions : undefined;

  // ─── Setup Checklist ────────────────────────────────────────────────────────

  const [setupDismissed, setSetupDismissed] = useState(true); // hide until loaded
  const [setupExpanded, setSetupExpanded] = useState(true);
  const [gpuInfo, setGpuInfo] = useState<{ gpu: boolean; toolkit: boolean } | null>(
    cachedGpuInfo ?? null,
  );

  // Load dismissed state and GPU info on mount (GPU check cached per session)
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('app.setupDismissed')
        .then((val: unknown) => {
          setSetupDismissed(val === true);
        })
        .catch(() => setSetupDismissed(false));
    } else {
      setSetupDismissed(false);
    }
    // Only run GPU check once per session
    if (cachedGpuInfo === undefined && api?.docker?.checkGpu) {
      api.docker
        .checkGpu()
        .then((info: { gpu: boolean; toolkit: boolean }) => {
          cachedGpuInfo = info;
          setGpuInfo(info);
          // Auto-set runtime profile based on GPU detection (only if not already configured)
          api.config
            ?.get('server.runtimeProfile')
            .then((val: unknown) => {
              if (!val && info.gpu && info.toolkit) {
                handleRuntimeProfileChange('gpu');
              } else if (!val && !info.gpu) {
                handleRuntimeProfileChange('cpu');
              }
            })
            .catch(() => {});
        })
        .catch(() => {
          cachedGpuInfo = null;
          setGpuInfo(null);
        });
    }
  }, []);

  // Setup checks
  const setupChecks = [
    {
      label: 'Docker installed',
      ok: docker.available,
      hint: 'Install Docker Engine or Docker Desktop',
    },
    {
      label: 'Docker image pulled',
      ok: docker.images.length > 0,
      hint: 'Pull an image below to get started',
    },
    {
      label: 'NVIDIA GPU detected',
      ok: gpuInfo?.gpu ?? false,
      warn: gpuInfo !== null && !gpuInfo.gpu,
      hint: gpuInfo?.gpu
        ? gpuInfo.toolkit
          ? 'nvidia-container-toolkit ready'
          : 'Run: sudo nvidia-ctk runtime configure --runtime=docker'
        : 'CPU mode will be used (slower)',
    },
  ];
  const allPassed = setupChecks.every((c) => c.ok);
  const showChecklist = !setupDismissed || !allPassed;

  const handleDismissSetup = useCallback(() => {
    setSetupDismissed(true);
    const api = (window as any).electronAPI;
    api?.config?.set('app.setupDismissed', true);
  }, []);

  // Model load/unload handlers
  const handleLoadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      await apiClient.loadModels();
    } catch {
      /* errors shown via admin status */
    }
    setModelsLoading(false);
  }, []);

  const handleUnloadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      await apiClient.unloadModels();
    } catch {
      /* ignore */
    }
    setModelsLoading(false);
  }, []);

  return (
    <div className="custom-scrollbar h-full w-full overflow-y-auto">
      <div className="mx-auto flex max-w-4xl flex-col space-y-6 p-6 pt-8 pb-10">
        <div className="flex-none pt-2">
          <h1 className="mb-2 text-3xl font-bold tracking-tight text-white">
            Server Configuration
          </h1>
          <p className="-mt-1 text-slate-400">Manage runtime resources and persistent storage.</p>
        </div>

        {/* Setup checklist — shown on first run or when prerequisites are missing */}
        {showChecklist && (
          <div
            className={`overflow-hidden rounded-xl border transition-all duration-300 ${allPassed ? 'border-green-500/20 bg-green-500/5' : 'border-accent-orange/20 bg-accent-orange/5'}`}
          >
            <button
              onClick={() => setSetupExpanded(!setupExpanded)}
              className="flex w-full items-center justify-between px-5 py-3.5 transition-colors hover:bg-white/5"
            >
              <div className="flex items-center gap-3">
                {allPassed ? (
                  <CheckCircle2 size={18} className="text-green-400" />
                ) : (
                  <AlertTriangle size={18} className="text-accent-orange" />
                )}
                <span className="text-sm font-semibold text-white">
                  {allPassed ? 'Setup Complete' : 'Setup Checklist'}
                </span>
                <span className="font-mono text-xs text-slate-500">
                  {setupChecks.filter((c) => c.ok).length}/{setupChecks.length} checks passed
                </span>
              </div>
              <div className="flex items-center gap-2">
                {!allPassed && (
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      docker.retryDetection();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.stopPropagation();
                        docker.retryDetection();
                      }
                    }}
                    className="hover:text-accent-cyan flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-white/10"
                    title="Re-check Docker, images, and GPU"
                  >
                    <RotateCcw size={12} />
                    Retry
                  </div>
                )}
                {allPassed && (
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDismissSetup();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.stopPropagation();
                        handleDismissSetup();
                      }
                    }}
                    className="cursor-pointer rounded px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                  >
                    Dismiss
                  </div>
                )}
                {setupExpanded ? (
                  <ChevronUp size={14} className="text-slate-400" />
                ) : (
                  <ChevronDown size={14} className="text-slate-400" />
                )}
              </div>
            </button>
            {setupExpanded && (
              <div className="space-y-2.5 px-5 pb-4">
                {setupChecks.map((check, i) => (
                  <div key={i} className="flex items-center gap-3">
                    {check.ok ? (
                      <CheckCircle2 size={15} className="shrink-0 text-green-400" />
                    ) : check.warn ? (
                      <AlertTriangle size={15} className="text-accent-orange shrink-0" />
                    ) : (
                      <XCircle size={15} className="shrink-0 text-red-400" />
                    )}
                    <span className={`text-sm ${check.ok ? 'text-slate-300' : 'text-white'}`}>
                      {check.label}
                    </span>
                    <span className="ml-auto text-xs text-slate-500">{check.hint}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 1. Image Card */}
        <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
          <div
            className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${hasImages ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}
          >
            <Download size={14} />
          </div>
          <GlassCard
            title="1. Docker Image"
            className={`transition-all duration-500 ease-in-out ${hasImages ? ACTIVE_CARD_ACCENT_CLASS : ''}`}
          >
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-4">
                <div className="flex items-center space-x-3">
                  <StatusLight status={hasImages ? 'active' : 'inactive'} />
                  <span
                    className={`font-mono text-sm transition-colors ${hasImages ? 'text-slate-300' : 'text-slate-500'}`}
                  >
                    {hasImages
                      ? `${docker.images.length} image${docker.images.length > 1 ? 's' : ''} available`
                      : 'No images'}
                  </span>

                  {hasImages && docker.images[0] && (
                    <div className="flex gap-2 transition-opacity duration-300">
                      <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-slate-400">
                        {docker.images[0].created.split(' ')[0]}
                      </span>
                      <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-slate-400">
                        {docker.images[0].size}
                      </span>
                    </div>
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">
                    Select Image Tag
                  </label>
                  <CustomSelect
                    value={selectedImage}
                    onChange={setSelectedImage}
                    options={imageOptions}
                    className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  />
                </div>
              </div>
              <div className="flex flex-col justify-end space-y-2">
                <Button
                  variant="secondary"
                  className="h-10 w-full"
                  onClick={() => docker.refreshImages()}
                  disabled={docker.operating}
                >
                  <RefreshCw size={14} className="mr-2" />
                  Scan Local Images
                </Button>
                <Button
                  variant="secondary"
                  className="h-10 w-full"
                  onClick={() => docker.pullImage(selectedTagForActions)}
                  disabled={docker.operating}
                >
                  {docker.pulling ? (
                    <>
                      <Loader2 size={14} className="mr-2 animate-spin" /> Pulling...
                    </>
                  ) : (
                    'Fetch Fresh Image'
                  )}
                </Button>
                {docker.pulling && (
                  <Button
                    variant="danger"
                    className="h-10 w-full"
                    onClick={() => docker.cancelPull()}
                  >
                    Cancel Pull
                  </Button>
                )}
                <Button
                  variant="danger"
                  className="h-10 w-full"
                  onClick={() => docker.removeImage(selectedTagForActions)}
                  disabled={docker.operating || docker.images.length === 0}
                >
                  Remove Image
                </Button>
              </div>
            </div>
            {docker.operationError && (
              <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                {docker.operationError}
              </div>
            )}
          </GlassCard>
        </div>

        {/* 2. Container Card (Config & Controls) */}
        <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
          <div
            className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${isRunning ? `bg-accent-cyan text-slate-900 ${isRunningAndHealthy ? 'shadow-[0_0_15px_rgba(34,211,238,0.5)]' : ''}` : containerStatus.exists ? 'bg-accent-orange text-slate-900 shadow-[0_0_15px_rgba(251,146,60,0.5)]' : 'bg-slate-800 text-slate-300'}`}
          >
            <Box size={16} />
          </div>
          <GlassCard
            title="2. Instance Settings"
            className={`transition-all duration-500 ease-in-out ${isRunningAndHealthy ? ACTIVE_CARD_ACCENT_CLASS : ''}`}
          >
            <div className="space-y-6">
              {/* Runtime Profile Selector */}
              <div className="flex items-center gap-4 border-b border-white/5 pb-4">
                <label className="text-xs font-medium tracking-wider whitespace-nowrap text-slate-500 uppercase">
                  Runtime
                </label>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleRuntimeProfileChange('gpu')}
                    disabled={isRunning}
                    className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all ${
                      runtimeProfile === 'gpu'
                        ? 'bg-accent-cyan/15 border-accent-cyan/40 text-accent-cyan shadow-[0_0_10px_rgba(34,211,238,0.15)]'
                        : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                    } ${isRunning ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                  >
                    <Gpu size={14} />
                    GPU (CUDA)
                  </button>
                  <button
                    onClick={() => handleRuntimeProfileChange('cpu')}
                    disabled={isRunning}
                    className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all ${
                      runtimeProfile === 'cpu'
                        ? 'bg-accent-orange/15 border-accent-orange/40 text-accent-orange shadow-[0_0_10px_rgba(255,145,0,0.15)]'
                        : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                    } ${isRunning ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                  >
                    <Cpu size={14} />
                    CPU Only
                  </button>
                </div>
                {runtimeProfile === 'cpu' && !isRunning && (
                  <span className="text-xs text-slate-500 italic">
                    Slower transcription, no NVIDIA GPU required
                  </span>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-5">
                <div className="flex h-6 shrink-0 items-center space-x-3 border-r border-white/10 pr-5">
                  <StatusLight
                    status={
                      isRunningAndHealthy
                        ? 'active'
                        : containerStatus.exists
                          ? 'warning'
                          : 'inactive'
                    }
                    animate={isRunningAndHealthy}
                  />
                  <span
                    className={`font-mono text-sm transition-colors ${
                      isRunning
                        ? 'text-slate-300'
                        : containerStatus.exists
                          ? 'text-accent-orange'
                          : 'text-slate-500'
                    }`}
                  >
                    {statusLabel}
                  </span>
                </div>

                <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-4">
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      className="h-9 px-4"
                      onClick={() => onStartServer('local', runtimeProfile, selectedTagForStart)}
                      disabled={docker.operating || isRunning || startupFlowPending}
                    >
                      {docker.operating || startupFlowPending ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        'Start Local'
                      )}
                    </Button>
                    <Button
                      variant="secondary"
                      className="h-9 px-4"
                      onClick={() => onStartServer('remote', runtimeProfile, selectedTagForStart)}
                      disabled={docker.operating || isRunning || startupFlowPending}
                    >
                      Start Remote
                    </Button>
                    <Button
                      variant="danger"
                      className="h-9 px-4"
                      onClick={() => docker.stopContainer()}
                      disabled={docker.operating || !isRunning}
                    >
                      Stop
                    </Button>
                  </div>
                  <Button
                    variant="danger"
                    className="h-9 px-4"
                    onClick={() => docker.removeContainer()}
                    disabled={docker.operating || isRunning || !containerStatus.exists}
                  >
                    Remove Container
                  </Button>
                </div>
              </div>

              {/* Auth Token (read-only) */}
              {authToken && (
                <div className="border-t border-white/5 pt-4">
                  <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                    Auth Token
                  </label>
                  <div className="relative">
                    <input
                      type={showAuthToken ? 'text' : 'password'}
                      value={authToken}
                      readOnly
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-20 font-mono text-sm text-white focus:outline-none"
                    />
                    <div className="absolute top-2 right-2 flex items-center gap-1">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(authToken);
                          setAuthTokenCopied(true);
                          setTimeout(() => setAuthTokenCopied(false), 2000);
                        }}
                        className="p-1 text-slate-500 transition-colors hover:text-white"
                        title="Copy token"
                      >
                        {authTokenCopied ? (
                          <Check size={14} className="text-green-400" />
                        ) : (
                          <Copy size={14} />
                        )}
                      </button>
                      <button
                        onClick={() => setShowAuthToken(!showAuthToken)}
                        className="p-1 text-slate-500 transition-colors hover:text-white"
                      >
                        {showAuthToken ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {containerStatus.startedAt && isRunning && (
                <div className="font-mono text-xs text-slate-500">
                  Started: {new Date(containerStatus.startedAt).toLocaleString()}
                  {containerStatus.health && (
                    <span className="ml-3">
                      Health:{' '}
                      <span
                        className={
                          containerStatus.health === 'healthy'
                            ? 'text-green-400'
                            : 'text-accent-orange'
                        }
                      >
                        {containerStatus.health}
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </GlassCard>
        </div>

        {/* 3. ASR Models Card */}
        <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
          <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
            <Cpu size={14} />
          </div>
          <GlassCard title="3. ASR Models Configuration">
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">Main Transcriber</label>
                    {isRunning &&
                      activeTranscriber &&
                      activeTranscriber !== MODEL_DEFAULT_LOADING_PLACEHOLDER && (
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`inline-block h-2 w-2 rounded-full ${modelCacheStatus[activeTranscriber]?.exists ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'}`}
                          />
                          <span
                            className={`font-mono text-[10px] ${modelCacheStatus[activeTranscriber]?.exists ? 'text-green-400' : 'text-slate-500'}`}
                          >
                            {modelCacheStatus[activeTranscriber]?.exists ? 'Downloaded' : 'Missing'}
                          </span>
                        </div>
                      )}
                  </div>
                  <CustomSelect
                    value={mainModelSelection}
                    onChange={setMainModelSelection}
                    options={[
                      configuredMainModel || MODEL_DEFAULT_LOADING_PLACEHOLDER,
                      MAIN_MODEL_CUSTOM_OPTION,
                    ]}
                    accentColor="magenta"
                    className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  />
                  {mainModelSelection === MAIN_MODEL_CUSTOM_OPTION && (
                    <input
                      type="text"
                      value={mainCustomModel}
                      onChange={(e) => setMainCustomModel(e.target.value)}
                      placeholder="owner/model-name"
                      className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1"
                    />
                  )}
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">Live Mode Model</label>
                    {isRunning &&
                      activeLiveModel &&
                      activeLiveModel !== MODEL_DEFAULT_LOADING_PLACEHOLDER &&
                      (() => {
                        const liveKey =
                          liveModelSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION
                            ? activeTranscriber
                            : activeLiveModel;
                        const liveExists = modelCacheStatus[liveKey ?? '']?.exists;
                        return (
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`inline-block h-2 w-2 rounded-full ${liveExists ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'}`}
                            />
                            <span
                              className={`font-mono text-[10px] ${liveExists ? 'text-green-400' : 'text-slate-500'}`}
                            >
                              {liveExists ? 'Downloaded' : 'Missing'}
                            </span>
                          </div>
                        );
                      })()}
                  </div>
                  <CustomSelect
                    value={liveModelSelection}
                    onChange={setLiveModelSelection}
                    options={[
                      LIVE_MODEL_SAME_AS_MAIN_OPTION,
                      LIVE_ALTERNATE_MODEL,
                      LIVE_MODEL_CUSTOM_OPTION,
                    ]}
                    className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  />
                  {liveModelSelection === LIVE_MODEL_CUSTOM_OPTION && (
                    <input
                      type="text"
                      value={liveCustomModel}
                      onChange={(e) => setLiveCustomModel(e.target.value)}
                      placeholder="owner/model-name"
                      className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1"
                    />
                  )}
                </div>
              </div>
              <div className="flex gap-2 border-t border-white/5 pt-2">
                <Button
                  variant={adminStatus?.models_loaded === false ? 'secondary' : 'danger'}
                  className="h-9 px-4"
                  onClick={
                    adminStatus?.models_loaded === false ? handleLoadModels : handleUnloadModels
                  }
                  disabled={modelsLoading || !isRunning}
                >
                  {modelsLoading ? (
                    <>
                      <Loader2 size={14} className="mr-2 animate-spin" /> Loading...
                    </>
                  ) : adminStatus?.models_loaded === false ? (
                    'Load Models'
                  ) : (
                    'Unload Models'
                  )}
                </Button>
                {adminStatus?.models_loaded !== undefined && (
                  <span
                    className={`ml-auto self-center font-mono text-xs ${adminStatus.models_loaded ? 'text-green-400' : 'text-slate-500'}`}
                  >
                    {adminStatus.models_loaded ? 'Models Loaded' : 'Models Not Loaded'}
                  </span>
                )}
              </div>
            </div>
          </GlassCard>
        </div>

        {/* 4. Diarization Models Card */}
        <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
          <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
            <Users size={14} />
          </div>
          <GlassCard title="4. Diarization Models Configuration">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-slate-300">Diarization Model</label>
                {isRunning && activeDiarizationModel && (
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${modelCacheStatus[activeDiarizationModel]?.exists ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'}`}
                    />
                    <span
                      className={`font-mono text-[10px] ${modelCacheStatus[activeDiarizationModel]?.exists ? 'text-green-400' : 'text-slate-500'}`}
                    >
                      {modelCacheStatus[activeDiarizationModel]?.exists ? 'Downloaded' : 'Missing'}
                    </span>
                  </div>
                )}
              </div>
              <CustomSelect
                value={diarizationModelSelection}
                onChange={setDiarizationModelSelection}
                options={[DIARIZATION_DEFAULT_MODEL, DIARIZATION_MODEL_CUSTOM_OPTION]}
                className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
              />
              {diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION && (
                <input
                  type="text"
                  value={diarizationCustomModel}
                  onChange={(e) => setDiarizationCustomModel(e.target.value)}
                  placeholder="owner/model-name"
                  className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1"
                />
              )}
            </div>
          </GlassCard>
        </div>

        {/* 5. Volumes Card */}
        <div className="relative shrink-0 border-l-2 border-white/10 pb-2 pl-8 last:border-0 last:pb-0">
          <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
            <HardDrive size={14} />
          </div>
          <GlassCard
            title="5. Persistent Volumes"
            action={
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={() => docker.refreshVolumes()}
              >
                Refresh
              </Button>
            }
          >
            <div className="space-y-4">
              {docker.volumes.length > 0 ? (
                docker.volumes.map((vol) => {
                  const colorMap: Record<string, string> = {
                    'transcriptionsuite-data': 'bg-blue-500',
                    'transcriptionsuite-models': 'bg-purple-500',
                    'transcriptionsuite-runtime': 'bg-orange-500',
                    'transcriptionsuite-uv-cache': 'bg-teal-500',
                  };
                  return (
                    <div key={vol.name} className="flex items-center justify-between py-1 text-sm">
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-2 w-2 rounded-full ${colorMap[vol.name] || 'bg-slate-500'}`}
                        ></div>
                        <span className="text-slate-300">{vol.label}</span>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="font-mono text-slate-500">{vol.size || '—'}</span>
                        <span
                          className={`text-xs ${vol.mountpoint ? 'text-green-400' : 'text-slate-500'}`}
                        >
                          {vol.mountpoint ? 'Mounted' : 'Not Found'}
                        </span>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="py-2 text-center text-sm text-slate-500">
                  {docker.available ? 'No volumes found' : 'Docker not available'}
                </div>
              )}

              {docker.volumes.length > 0 && (
                <div className="mt-4 flex gap-2 overflow-x-auto border-t border-white/5 pt-4 pb-2">
                  {docker.volumes.map((vol) => (
                    <Button
                      key={vol.name}
                      size="sm"
                      variant="danger"
                      className="text-xs whitespace-nowrap"
                      onClick={() => docker.removeVolume(vol.name)}
                      disabled={docker.operating || isRunning}
                    >
                      Clear {vol.label.replace(' Volume', '')}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
};
