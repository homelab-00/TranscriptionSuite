import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
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
  Laptop,
  Radio,
  Zap,
  MinusCircle,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { CustomSelect } from '../ui/CustomSelect';

import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { apiClient } from '../../src/api/client';
import { writeToClipboard } from '../../src/hooks/useClipboard';
import { isWhisperModel } from '../../src/services/modelCapabilities';
import {
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MAIN_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  MODEL_DISABLED_OPTION,
  DISABLED_MODEL_SENTINEL,
  WHISPER_MEDIUM,
  MAIN_MODEL_PRESETS,
  LIVE_MODEL_PRESETS,
  resolveMainModelSelectionValue,
  resolveLiveModelSelectionValue,
  toBackendModelEnvValue,
} from '../../src/services/modelSelection';
import { DEFAULT_SERVER_PORT } from '../../src/config/store';

type RuntimeProfile = 'gpu' | 'cpu' | 'metal';

const MLX_DEFAULT_MODEL = 'mlx-community/whisper-small-mlx';

interface ServerViewProps {
  onStartServer: (
    mode: 'local' | 'remote',
    runtimeProfile: RuntimeProfile,
    imageTag?: string,
    models?: {
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
    },
  ) => Promise<void>;
  startupFlowPending: boolean;
}

const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';
const DIARIZATION_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
const ACTIVE_CARD_ACCENT_CLASS = 'border-accent-cyan/40! shadow-[0_0_15px_rgba(34,211,238,0.2)]!';
const FALLBACK_LIVE_WHISPER_MODEL = WHISPER_MEDIUM;

const MAIN_MODEL_SELECTION_OPTIONS = new Set([
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  ...MAIN_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
  MAIN_MODEL_CUSTOM_OPTION,
]);
const LIVE_MODEL_SELECTION_OPTIONS = new Set([
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  ...LIVE_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
]);
const DIARIZATION_MODEL_SELECTION_OPTIONS = new Set([
  DIARIZATION_DEFAULT_MODEL,
  DIARIZATION_MODEL_CUSTOM_OPTION,
]);

const UI_SENTINEL_VALUES = new Set([
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MAIN_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  DIARIZATION_MODEL_CUSTOM_OPTION,
]);

function sanitizeModelName(value: string): string {
  if (value === MODEL_DISABLED_OPTION || value === DISABLED_MODEL_SENTINEL) {
    return DISABLED_MODEL_SENTINEL;
  }
  const normalized = toBackendModelEnvValue(value);
  if (!normalized || UI_SENTINEL_VALUES.has(normalized)) return '';
  return normalized;
}

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

function findCaseInsensitivePreset(value: string, options: string[]): string | null {
  const normalizedValue = normalizeModelName(value);
  if (!normalizedValue) return null;
  const match = options.find((option) => normalizeModelName(option) === normalizedValue);
  return match ?? null;
}

function normalizeLiveModelToWhisper(modelName: string): string {
  if (modelName === DISABLED_MODEL_SENTINEL) return modelName;
  return isWhisperModel(modelName) ? modelName : FALLBACK_LIVE_WHISPER_MODEL;
}

function mapMainModelToSelection(modelName: string): { selection: string; custom: string } {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel || normalizedModel === normalizeModelName(DISABLED_MODEL_SENTINEL)) {
    return { selection: MODEL_DISABLED_OPTION, custom: '' };
  }
  const preset = findCaseInsensitivePreset(modelName, MAIN_MODEL_PRESETS);
  if (preset) {
    return { selection: preset, custom: '' };
  }
  return { selection: MAIN_MODEL_CUSTOM_OPTION, custom: modelName };
}

function mapLiveModelToSelection(
  modelName: string,
  mainModelName: string,
): { selection: string; custom: string } {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel || normalizedModel === normalizeModelName(DISABLED_MODEL_SENTINEL)) {
    return { selection: MODEL_DISABLED_OPTION, custom: '' };
  }

  const normalizedLiveModel = normalizeLiveModelToWhisper(modelName);
  if (
    isWhisperModel(mainModelName) &&
    normalizeModelName(normalizedLiveModel) === normalizeModelName(mainModelName)
  ) {
    return { selection: LIVE_MODEL_SAME_AS_MAIN_OPTION, custom: '' };
  }

  const preset = findCaseInsensitivePreset(normalizedLiveModel, LIVE_MODEL_PRESETS);
  if (preset) {
    return { selection: preset, custom: '' };
  }
  return { selection: LIVE_MODEL_CUSTOM_OPTION, custom: normalizedLiveModel };
}

function mapDiarizationModelToSelection(modelName: string): { selection: string; custom: string } {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel || normalizedModel === normalizeModelName(DIARIZATION_DEFAULT_MODEL)) {
    return { selection: DIARIZATION_DEFAULT_MODEL, custom: '' };
  }
  return { selection: DIARIZATION_MODEL_CUSTOM_OPTION, custom: modelName };
}

export const ServerView: React.FC<ServerViewProps> = ({ onStartServer, startupFlowPending }) => {
  const { status: adminStatus, refresh: refreshAdminStatus } = useAdminStatus();
  const docker = useDockerContext();

  // Model selection state
  const [mainModelSelection, setMainModelSelection] = useState(MODEL_DEFAULT_LOADING_PLACEHOLDER);
  const [mainCustomModel, setMainCustomModel] = useState('');
  const [liveModelSelection, setLiveModelSelection] = useState(LIVE_MODEL_SAME_AS_MAIN_OPTION);
  const [liveCustomModel, setLiveCustomModel] = useState('');
  const [localSelectionsHydrated, setLocalSelectionsHydrated] = useState(false);
  const [modelsHydrated, setModelsHydrated] = useState(false);
  const [diarizationModelSelection, setDiarizationModelSelection] =
    useState(DIARIZATION_DEFAULT_MODEL);
  const [diarizationCustomModel, setDiarizationCustomModel] = useState('');
  const [diarizationHydrated, setDiarizationHydrated] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Model download cache state (checks Docker volume for HF model dirs)
  const [modelCacheStatus, setModelCacheStatus] = useState<
    Record<string, { exists: boolean; size?: string }>
  >({});
  const modelCacheCheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Runtime profile (persisted in electron-store)
  const [runtimeProfile, setRuntimeProfile] = useState<RuntimeProfile>('gpu');

  // Metal (Apple Silicon) detection – derived from server-side feature check
  const mlxFeature = (adminStatus?.models as any)?.features?.mlx as { available: boolean; reason: string } | undefined;
  const metalSupported = mlxFeature?.available ?? false;
  const [isDarwin] = useState<boolean>(() => {
    return (window as any).electronAPI?.app?.getPlatform?.() === 'darwin';
  });

  // Auth token display in Instance Settings
  const [showAuthToken, setShowAuthToken] = useState(false);
  const [authTokenCopied, setAuthTokenCopied] = useState(false);
  const [authToken, setAuthToken] = useState('');

  // Tailscale hostname auto-detection
  const [tailscaleHostname, setTailscaleHostname] = useState<string | null>(null);
  const [tailscaleHostnameCopied, setTailscaleHostnameCopied] = useState(false);

  // Clean-all modal state
  const [isCleanAllDialogOpen, setIsCleanAllDialogOpen] = useState(false);
  const [keepDataVolume, setKeepDataVolume] = useState(false);
  const [keepModelsVolume, setKeepModelsVolume] = useState(false);
  const [keepConfigDirectory, setKeepConfigDirectory] = useState(false);

  // Firewall warning state (remote mode)
  const [firewallWarning, setFirewallWarning] = useState<string | null>(null);

  // Server mode badge (local vs remote)
  const [serverMode, setServerMode] = useState<'local' | 'remote' | null>(null);

  // Load persisted runtime profile, auth token, and Tailscale hostname on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('server.runtimeProfile')
        .then((val: unknown) => {
          if (val === 'gpu' || val === 'cpu' || val === 'metal') setRuntimeProfile(val);
        })
        .catch(() => {});
      api.config
        .get('connection.authToken')
        .then((val: unknown) => {
          if (typeof val === 'string') setAuthToken(val);
        })
        .catch(() => {});
    }
    // Detect local Tailscale hostname
    if (api?.tailscale?.getHostname) {
      api.tailscale
        .getHostname()
        .then((hostname: string | null) => {
          if (hostname) setTailscaleHostname(hostname);
        })
        .catch(() => {});
    }
  }, [adminStatus]);

  // Load persisted model selection UI state once per mount.
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.config) {
      setLocalSelectionsHydrated(true);
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
    ])
      .then(
        ([
          storedMainSelection,
          storedMainCustom,
          storedLiveSelection,
          storedLiveCustom,
          storedDiarizationSelection,
          storedDiarizationCustom,
        ]: unknown[]) => {
          if (!active) return;

          let nextMainSelection =
            getString(storedMainSelection) ?? MODEL_DEFAULT_LOADING_PLACEHOLDER;
          let nextMainCustom = getString(storedMainCustom) ?? '';

          if (!MAIN_MODEL_SELECTION_OPTIONS.has(nextMainSelection)) {
            if (
              normalizeModelName(nextMainSelection) === normalizeModelName(DISABLED_MODEL_SENTINEL)
            ) {
              nextMainSelection = MODEL_DISABLED_OPTION;
            } else {
              const preset = findCaseInsensitivePreset(nextMainSelection, MAIN_MODEL_PRESETS);
              if (preset) {
                nextMainSelection = preset;
              } else if (nextMainSelection) {
                nextMainCustom = nextMainSelection;
                nextMainSelection = MAIN_MODEL_CUSTOM_OPTION;
              } else {
                nextMainSelection = MODEL_DEFAULT_LOADING_PLACEHOLDER;
              }
            }
          }
          if (nextMainSelection !== MAIN_MODEL_CUSTOM_OPTION) {
            nextMainCustom = '';
          }

          let nextLiveSelection = getString(storedLiveSelection) ?? LIVE_MODEL_SAME_AS_MAIN_OPTION;
          let nextLiveCustom = getString(storedLiveCustom) ?? '';

          if (!LIVE_MODEL_SELECTION_OPTIONS.has(nextLiveSelection)) {
            if (
              normalizeModelName(nextLiveSelection) === normalizeModelName(DISABLED_MODEL_SENTINEL)
            ) {
              nextLiveSelection = MODEL_DISABLED_OPTION;
            } else {
              const preset = findCaseInsensitivePreset(nextLiveSelection, LIVE_MODEL_PRESETS);
              if (preset) {
                nextLiveSelection = preset;
              } else if (nextLiveSelection) {
                nextLiveCustom = nextLiveSelection;
                nextLiveSelection = LIVE_MODEL_CUSTOM_OPTION;
              } else {
                nextLiveSelection = LIVE_MODEL_SAME_AS_MAIN_OPTION;
              }
            }
          }
          if (nextLiveSelection !== LIVE_MODEL_CUSTOM_OPTION) {
            nextLiveCustom = '';
          }

          const resolvedMainModel = resolveMainModelSelectionValue(
            nextMainSelection,
            nextMainCustom,
            '',
          );
          const resolvedLiveModel = resolveLiveModelSelectionValue(
            nextLiveSelection,
            nextLiveCustom,
            resolvedMainModel,
            '',
          );
          if (resolvedLiveModel !== DISABLED_MODEL_SENTINEL && !isWhisperModel(resolvedLiveModel)) {
            nextLiveSelection = FALLBACK_LIVE_WHISPER_MODEL;
            nextLiveCustom = '';
          }

          let nextDiarizationSelection =
            getString(storedDiarizationSelection) ?? DIARIZATION_DEFAULT_MODEL;
          let nextDiarizationCustom = getString(storedDiarizationCustom) ?? '';

          if (!DIARIZATION_MODEL_SELECTION_OPTIONS.has(nextDiarizationSelection)) {
            if (
              normalizeModelName(nextDiarizationSelection) ===
              normalizeModelName(DIARIZATION_DEFAULT_MODEL)
            ) {
              nextDiarizationSelection = DIARIZATION_DEFAULT_MODEL;
            } else if (nextDiarizationSelection) {
              nextDiarizationCustom = nextDiarizationSelection;
              nextDiarizationSelection = DIARIZATION_MODEL_CUSTOM_OPTION;
            } else {
              nextDiarizationSelection = DIARIZATION_DEFAULT_MODEL;
            }
          }
          if (nextDiarizationSelection !== DIARIZATION_MODEL_CUSTOM_OPTION) {
            nextDiarizationCustom = '';
          }

          setMainModelSelection(nextMainSelection);
          setMainCustomModel(nextMainCustom);
          setLiveModelSelection(nextLiveSelection);
          setLiveCustomModel(nextLiveCustom);
          setDiarizationModelSelection(nextDiarizationSelection);
          setDiarizationCustomModel(nextDiarizationCustom);
        },
      )
      .catch(() => {})
      .finally(() => {
        if (active) {
          setLocalSelectionsHydrated(true);
        }
      });

    return () => {
      active = false;
    };
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

  // MLX (native process) server state
  type MLXStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';
  const [mlxStatus, setMlxStatus] = useState<MLXStatus>('stopped');

  // Sync mlxStatus from the main process on mount and subscribe to push updates.
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    api.mlx.getStatus().then(setMlxStatus).catch(() => {});
    const unsub = api.mlx.onStatusChanged((status: MLXStatus) => setMlxStatus(status));
    return unsub;
  }, []);


  const hasImages = docker.images.length > 0;
  const statusLabel = containerStatus.exists
    ? containerStatus.status.charAt(0).toUpperCase() + containerStatus.status.slice(1)
    : 'Not Found';

  // Check firewall when container becomes healthy in remote mode
  useEffect(() => {
    if (!isRunningAndHealthy) {
      setFirewallWarning(null);
      return;
    }
    const api = (window as any).electronAPI;
    if (!api?.server?.checkFirewallPort || !api?.config?.get) return;

    // Only check if server was started in remote/TLS mode
    api.config
      .get('connection.useRemote')
      .then(async (useRemote: unknown) => {
        // Also check the compose env to see if TLS was enabled (server-side indicator)
        const tlsFromCompose = await api.docker
          ?.readComposeEnvValue?.('TLS_ENABLED')
          .catch(() => null);
        const isRemote = useRemote === true || tlsFromCompose === 'true';
        if (!isRemote) return;

        try {
          const port = ((await api.config.get('connection.port')) as number) ?? DEFAULT_SERVER_PORT;
          const result = await api.server.checkFirewallPort(port);
          if (result.firewallSuspect && result.hint) {
            setFirewallWarning(result.hint);
          } else {
            setFirewallWarning(null);
          }
        } catch {
          // Best effort
        }
      })
      .catch(() => {});
  }, [isRunningAndHealthy]);

  // Track server mode (local vs remote) from compose env
  useEffect(() => {
    if (!isRunning) {
      setServerMode(null);
      return;
    }
    const dockerApi = (window as any).electronAPI?.docker;
    if (!dockerApi?.readComposeEnvValue) return;
    dockerApi
      .readComposeEnvValue('TLS_ENABLED')
      .then((val: unknown) => {
        setServerMode(val === 'true' ? 'remote' : 'local');
      })
      .catch(() => {});
  }, [isRunning]);

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
    DISABLED_MODEL_SENTINEL;
  const configuredLiveModel = getString(adminLiveCfg.model) ?? configuredMainModel;
  const configuredDiarizationModel =
    getString(adminDiarizationCfg.model) ??
    getString(adminModelDiarizationCfg.model) ??
    getString(adminModelDiarization.model) ??
    '';

  useEffect(() => {
    if (!localSelectionsHydrated || modelsHydrated || !adminStatus) return;

    const mappedMain = mapMainModelToSelection(configuredMainModel);
    const mappedLive = mapLiveModelToSelection(configuredLiveModel, configuredMainModel);

    setMainModelSelection(mappedMain.selection);
    setMainCustomModel(mappedMain.custom);
    setLiveModelSelection(mappedLive.selection);
    setLiveCustomModel(mappedLive.custom);

    setModelsHydrated(true);
  }, [
    adminStatus,
    configuredMainModel,
    configuredLiveModel,
    localSelectionsHydrated,
    modelsHydrated,
  ]);

  useEffect(() => {
    if (!localSelectionsHydrated || diarizationHydrated || !adminStatus) return;

    const mappedDiarization = mapDiarizationModelToSelection(configuredDiarizationModel);
    setDiarizationModelSelection(mappedDiarization.selection);
    setDiarizationCustomModel(mappedDiarization.custom);

    setDiarizationHydrated(true);
  }, [adminStatus, configuredDiarizationModel, diarizationHydrated, localSelectionsHydrated]);

  const activeTranscriber = resolveMainModelSelectionValue(
    mainModelSelection,
    mainCustomModel,
    configuredMainModel,
  );
  const activeLiveModel = resolveLiveModelSelectionValue(
    liveModelSelection,
    liveCustomModel,
    activeTranscriber,
    configuredLiveModel,
  );
  const normalizedLiveModel = normalizeLiveModelToWhisper(activeLiveModel);
  const liveModelWhisperOnlyCompatible =
    activeLiveModel === DISABLED_MODEL_SENTINEL || isWhisperModel(activeLiveModel);
  const liveModeModelConstraintMessage = 'Live Mode only supports faster-whisper models.';

  // Active diarization model name
  const activeDiarizationModel =
    diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION
      ? diarizationCustomModel.trim() || configuredDiarizationModel || DIARIZATION_DEFAULT_MODEL
      : DIARIZATION_DEFAULT_MODEL;

  // MLX native-process start/stop handlers (depend on activeTranscriber declared above)
  const handleMLXStart = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    const port = (await api.config?.get('server.port').catch(() => 9786)) ?? 9786;
    const hfToken = (await api.config?.get('server.hfToken').catch(() => '')) ?? '';
    await api.mlx.start({
      port: Number(port),
      hfToken: hfToken || undefined,
      mainTranscriberModel: sanitizeModelName(activeTranscriber) || MLX_DEFAULT_MODEL,
    });
  }, [activeTranscriber]);

  const handleMLXStop = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    await api.mlx.stop();
  }, []);

  // Hard-reset any non-whisper live model selection to the default whisper model.
  useEffect(() => {
    if (
      !localSelectionsHydrated ||
      activeLiveModel === DISABLED_MODEL_SENTINEL ||
      isWhisperModel(activeLiveModel)
    )
      return;
    setLiveModelSelection(FALLBACK_LIVE_WHISPER_MODEL);
    setLiveCustomModel('');
  }, [activeLiveModel, localSelectionsHydrated]);

  // Persist model selection UI state.
  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.mainModelSelection', mainModelSelection).catch(() => {});
  }, [localSelectionsHydrated, mainModelSelection]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.mainCustomModel', mainCustomModel).catch(() => {});
  }, [localSelectionsHydrated, mainCustomModel]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.liveModelSelection', liveModelSelection).catch(() => {});
  }, [localSelectionsHydrated, liveModelSelection]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.liveCustomModel', liveCustomModel).catch(() => {});
  }, [localSelectionsHydrated, liveCustomModel]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config
      .set('server.diarizationModelSelection', diarizationModelSelection)
      .catch(() => {});
  }, [localSelectionsHydrated, diarizationModelSelection]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.diarizationCustomModel', diarizationCustomModel).catch(() => {});
  }, [localSelectionsHydrated, diarizationCustomModel]);

  // Check model download cache whenever the active model names or container state change
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.docker?.checkModelsCached || !isRunning) return;

    // Collect unique model IDs to check
    const modelIds = [
      ...new Set([activeTranscriber, normalizedLiveModel, activeDiarizationModel]),
    ].filter(
      (id) => id && id !== MODEL_DEFAULT_LOADING_PLACEHOLDER && id !== DISABLED_MODEL_SENTINEL,
    );
    if (modelIds.length === 0) return;

    // Debounce the check
    if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    modelCacheCheckRef.current = setTimeout(() => {
      api.docker
        .checkModelsCached(modelIds)
        .then((result: Record<string, { exists: boolean; size?: string }>) => {
          setModelCacheStatus((prev) => ({ ...prev, ...result }));
        })
        .catch(() => {});
    }, 500);

    return () => {
      if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    };
  }, [activeTranscriber, normalizedLiveModel, activeDiarizationModel, isRunning]);

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
          // Auto-set runtime profile based on hardware detection (only if not already configured).
          // Priority: Metal (Apple Silicon) > NVIDIA GPU > CPU
          api.config
            ?.get('server.runtimeProfile')
            .then((val: unknown) => {
              if (!val) {
                if (metalSupported) {
                  handleRuntimeProfileChange('metal');
                  api.config
                    ?.get('server.mainModelSelection')
                    .then((modelVal: unknown) => {
                      const cur = typeof modelVal === 'string' ? modelVal.trim() : '';
                      if (!cur || cur === MODEL_DEFAULT_LOADING_PLACEHOLDER) {
                        setMainModelSelection(MLX_DEFAULT_MODEL);
                        api.config?.set('server.mainModelSelection', MLX_DEFAULT_MODEL);
                        api.config?.set('server.mainCustomModel', '');
                      }
                    })
                    .catch(() => {});
                } else if (info.gpu && info.toolkit) {
                  handleRuntimeProfileChange('gpu');
                } else {
                  handleRuntimeProfileChange('cpu');
                }
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
  const rtName = docker.runtimeKind ?? 'Docker';
  const gpuSatisfied = gpuInfo?.gpu ?? false;
  const metalSatisfied = metalSupported;
  const setupChecks = [
    {
      label: `${rtName} installed`,
      ok: docker.available,
      hint: 'Install Docker Engine, Docker Desktop, or Podman',
    },
    {
      label: `${rtName} image pulled`,
      ok: docker.images.length > 0,
      hint: 'Pull an image below to get started',
    },
    {
      label: 'NVIDIA GPU detected',
      ok: gpuSatisfied,
      // Grey out when Metal is active and NVIDIA isn't present — hardware is covered
      na: !gpuSatisfied && metalSatisfied,
      warn: gpuInfo !== null && !gpuSatisfied && !metalSatisfied,
      hint: gpuSatisfied
        ? gpuInfo?.toolkit
          ? 'nvidia-container-toolkit ready'
          : 'Run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml'
        : metalSatisfied
          ? 'Not needed — Metal acceleration active'
          : 'CPU mode will be used (slower)',
    },
    {
      label: 'Apple Silicon Metal',
      ok: metalSatisfied,
      // Grey out when NVIDIA is active and Metal isn't present — hardware is covered
      na: !metalSatisfied && gpuSatisfied,
      warn: !metalSatisfied && !gpuSatisfied && isDarwin,
      hint: metalSatisfied
        ? 'MLX acceleration available'
        : gpuSatisfied
          ? 'Not needed — NVIDIA GPU active'
          : !isDarwin
            ? 'Not applicable on this platform'
            : mlxFeature?.reason === 'not_apple_silicon'
              ? 'Intel Mac — CPU mode will be used'
              : mlxFeature?.reason === 'mlx_whisper_not_installed'
                ? 'mlx-whisper not installed — run: uv sync --extra mlx'
                : 'MLX unavailable — CPU mode will be used',
    },
  ];
  // allPassed: na items (greyed-out / covered by the other GPU option) count as passing
  const allPassed = setupChecks.every((c) => c.ok || c.na);
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
    refreshAdminStatus();
  }, [refreshAdminStatus]);

  const handleUnloadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      await apiClient.unloadModels();
    } catch {
      /* ignore */
    }
    setModelsLoading(false);
    refreshAdminStatus();
  }, [refreshAdminStatus]);

  const openCleanAllDialog = useCallback(() => {
    setKeepDataVolume(false);
    setKeepModelsVolume(false);
    setKeepConfigDirectory(false);
    setIsCleanAllDialogOpen(true);
  }, []);

  const handleConfirmCleanAll = useCallback(async () => {
    setIsCleanAllDialogOpen(false);
    await docker.cleanAll({
      keepDataVolume,
      keepModelsVolume,
      keepConfigDirectory,
    });
  }, [docker, keepConfigDirectory, keepDataVolume, keepModelsVolume]);

  return (
    <>
      <div className="custom-scrollbar h-full w-full overflow-y-auto">
        <div className="mx-auto flex max-w-4xl flex-col space-y-6 p-6 pt-8 pb-10">
          <div className="flex flex-none items-center pt-2">
            <div>
              <h1 className="mb-2 text-3xl font-bold tracking-tight text-white">
                Server Configuration
              </h1>
              <p className="-mt-1 text-slate-400">
                Manage runtime resources and persistent storage.
              </p>
            </div>
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
                    {setupChecks.filter((c) => c.ok || (c as any).na).length}/{setupChecks.length} checks passed
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
                      title="Re-check container runtime, images, and GPU"
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
                      ) : (check as any).na ? (
                        <MinusCircle size={15} className="shrink-0 text-slate-600" />
                      ) : check.warn ? (
                        <AlertTriangle size={15} className="text-accent-orange shrink-0" />
                      ) : (
                        <XCircle size={15} className="shrink-0 text-red-400" />
                      )}
                      <span
                        className={`text-sm ${
                          check.ok
                            ? 'text-slate-300'
                            : (check as any).na
                              ? 'text-slate-600'
                              : 'text-white'
                        }`}
                      >
                        {check.label}
                      </span>
                      <span className={`ml-auto text-xs ${(check as any).na ? 'text-slate-700' : 'text-slate-500'}`}>{check.hint}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 1. Instance Settings Card */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
            <div
              className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${isRunning || mlxStatus === 'running' ? `bg-accent-cyan text-slate-900 ${isRunningAndHealthy || mlxStatus === 'running' ? 'shadow-[0_0_15px_rgba(34,211,238,0.5)]' : ''}` : containerStatus.exists ? 'bg-accent-orange text-slate-900 shadow-[0_0_15px_rgba(251,146,60,0.5)]' : 'bg-slate-800 text-slate-300'}`}
            >
              <Box size={16} />
            </div>
            <GlassCard
              title="1. Instance Settings"
              className={`transition-all duration-500 ease-in-out ${isRunningAndHealthy || mlxStatus === 'running' ? ACTIVE_CARD_ACCENT_CLASS : ''}`}
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
                    {isDarwin && (
                      <button
                        onClick={() => handleRuntimeProfileChange('metal')}
                        disabled={isRunning}
                        className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all ${
                          runtimeProfile === 'metal'
                            ? 'bg-violet-500/15 border-violet-500/40 text-violet-400 shadow-[0_0_10px_rgba(167,139,250,0.15)]'
                            : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                        } ${isRunning ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                      >
                        <Zap size={14} />
                        GPU (Metal)
                      </button>
                    )}
                  </div>
                  {runtimeProfile === 'cpu' && !isRunning && (
                    <span className="text-xs text-slate-500 italic">
                      Slower transcription, no NVIDIA GPU required
                    </span>
                  )}
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
                            writeToClipboard(authToken).catch(() => {});
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

                {/* Tailscale Hostname (for remote mode configuration) */}
                {tailscaleHostname && (
                  <div className="border-t border-white/5 pt-4">
                    <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                      Tailscale Hostname
                    </label>
                    <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2">
                      <span className="flex-1 truncate font-mono text-sm text-slate-300">
                        {tailscaleHostname}
                      </span>
                      <button
                        onClick={() => {
                          writeToClipboard(tailscaleHostname).catch(() => {});
                          setTailscaleHostnameCopied(true);
                          setTimeout(() => setTailscaleHostnameCopied(false), 2000);
                        }}
                        className="shrink-0 p-1 text-slate-500 transition-colors hover:text-white"
                        title="Copy Tailscale hostname"
                      >
                        {tailscaleHostnameCopied ? (
                          <Check size={14} className="text-green-400" />
                        ) : (
                          <Copy size={14} />
                        )}
                      </button>
                    </div>
                    <p className="mt-1.5 text-xs text-slate-500">
                      Use this hostname when configuring remote clients to connect via Tailscale.
                    </p>
                  </div>
                )}

                {/* Firewall warning (remote mode) */}
                {firewallWarning && isRunningAndHealthy && (
                  <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
                    <div className="text-xs text-amber-200">
                      <p className="font-medium">Firewall may block remote connections</p>
                      <p className="mt-0.5 text-amber-300/80">{firewallWarning}</p>
                    </div>
                  </div>
                )}

              </div>
            </GlassCard>
          </div>

          {/* 2. Inference Server (metal) or Docker Image (docker/cpu/gpu) Card */}
          {runtimeProfile === 'metal' ? (
            <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
              <div
                className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${mlxStatus === 'running' ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : mlxStatus === 'starting' || mlxStatus === 'stopping' ? 'bg-accent-orange text-slate-900 shadow-[0_0_15px_rgba(251,146,60,0.5)]' : 'bg-slate-800 text-slate-300'}`}
              >
                <Zap size={14} />
              </div>
              <GlassCard
                title="2. Inference Server"
                className={`transition-all duration-500 ease-in-out ${mlxStatus === 'running' ? ACTIVE_CARD_ACCENT_CLASS : ''}`}
              >
                <div className="flex flex-wrap items-center gap-5">
                  <div className="flex h-6 shrink-0 items-center space-x-3 border-r border-white/10 pr-5">
                    <StatusLight
                      status={
                        mlxStatus === 'running'
                          ? 'active'
                          : mlxStatus === 'starting' || mlxStatus === 'stopping'
                            ? 'warning'
                            : 'inactive'
                      }
                      animate={mlxStatus === 'running'}
                    />
                    <span
                      className={`font-mono text-sm transition-colors ${
                        mlxStatus === 'running'
                          ? 'text-slate-300'
                          : mlxStatus === 'starting' || mlxStatus === 'stopping'
                            ? 'text-accent-orange'
                            : 'text-slate-500'
                      }`}
                    >
                      {mlxStatus === 'running'
                        ? 'Running'
                        : mlxStatus === 'starting'
                          ? 'Starting…'
                          : mlxStatus === 'stopping'
                            ? 'Stopping…'
                            : mlxStatus === 'error'
                              ? 'Error'
                              : 'Stopped'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <Button
                      variant="secondary"
                      className="h-9 px-4"
                      onClick={handleMLXStart}
                      disabled={mlxStatus === 'running' || mlxStatus === 'starting' || mlxStatus === 'stopping'}
                    >
                      {mlxStatus === 'starting' ? (
                        <><Loader2 size={14} className="animate-spin" /> Starting…</>
                      ) : (
                        <><Zap size={14} /> Start Metal Server</>
                      )}
                    </Button>
                    <Button
                      variant="danger"
                      className="h-9 px-4"
                      onClick={handleMLXStop}
                      disabled={mlxStatus !== 'running' && mlxStatus !== 'starting'}
                    >
                      {mlxStatus === 'stopping' ? (
                        <><Loader2 size={14} className="animate-spin" /> Stopping…</>
                      ) : (
                        'Stop'
                      )}
                    </Button>
                    {mlxStatus === 'error' && (
                      <span className="text-xs text-red-400">Error — check logs</span>
                    )}
                  </div>
                </div>
              </GlassCard>
            </div>
          ) : (
            <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
              <div
                className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${hasImages ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}
              >
                <Download size={14} />
              </div>
              <GlassCard
                title="2. Docker Image"
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
                <div className="mt-4 flex flex-wrap items-center gap-5 border-t border-white/5 pt-4">
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
                    {isRunning && serverMode && (
                      <span
                        className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase ${serverMode === 'local' ? 'bg-accent-cyan/15 text-accent-cyan' : 'bg-accent-magenta/15 text-accent-magenta'}`}
                      >
                        {serverMode === 'local' ? <Laptop size={10} /> : <Radio size={10} />}
                        {serverMode}
                      </span>
                    )}
                  </div>
                  <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-4">
                    <div className="flex gap-2">
                      <Button
                        variant="secondary"
                        className="h-9 px-4"
                        onClick={() =>
                          onStartServer('local', runtimeProfile, selectedTagForStart, {
                            mainTranscriberModel: sanitizeModelName(activeTranscriber),
                            liveTranscriberModel: sanitizeModelName(normalizedLiveModel),
                            diarizationModel: sanitizeModelName(activeDiarizationModel),
                          })
                        }
                        disabled={
                          docker.operating ||
                          isRunning ||
                          startupFlowPending ||
                          !liveModelWhisperOnlyCompatible
                        }
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
                        onClick={() =>
                          onStartServer('remote', runtimeProfile, selectedTagForStart, {
                            mainTranscriberModel: sanitizeModelName(activeTranscriber),
                            liveTranscriberModel: sanitizeModelName(normalizedLiveModel),
                            diarizationModel: sanitizeModelName(activeDiarizationModel),
                          })
                        }
                        disabled={
                          docker.operating ||
                          isRunning ||
                          startupFlowPending ||
                          !liveModelWhisperOnlyCompatible
                        }
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
                {docker.operationError && (
                  <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                    {docker.operationError}
                  </div>
                )}
                {containerStatus.startedAt && isRunning && (
                  <div className="mt-2 font-mono text-xs text-slate-500">
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
              </GlassCard>
            </div>
          )}

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
                        activeTranscriber !== MODEL_DEFAULT_LOADING_PLACEHOLDER &&
                        activeTranscriber !== DISABLED_MODEL_SENTINEL && (
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`inline-block h-2 w-2 rounded-full ${modelCacheStatus[activeTranscriber]?.exists ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'}`}
                            />
                            <span
                              className={`font-mono text-[10px] ${modelCacheStatus[activeTranscriber]?.exists ? 'text-green-400' : 'text-slate-500'}`}
                            >
                              {modelCacheStatus[activeTranscriber]?.exists
                                ? 'Downloaded'
                                : 'Missing'}
                            </span>
                          </div>
                        )}
                    </div>
                    <CustomSelect
                      value={mainModelSelection}
                      onChange={setMainModelSelection}
                      options={[
                        ...MAIN_MODEL_PRESETS,
                        MODEL_DISABLED_OPTION,
                        MAIN_MODEL_CUSTOM_OPTION,
                      ]}
                      accentColor="magenta"
                      className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                      disabled={isRunning}
                    />
                    {mainModelSelection === MAIN_MODEL_CUSTOM_OPTION && (
                      <input
                        type="text"
                        value={mainCustomModel}
                        onChange={(e) => setMainCustomModel(e.target.value)}
                        placeholder="owner/model-name"
                        disabled={isRunning}
                        className={`focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
                      />
                    )}
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium text-slate-300">Live Mode Model</label>
                      {isRunning &&
                        activeLiveModel &&
                        activeLiveModel !== MODEL_DEFAULT_LOADING_PLACEHOLDER &&
                        activeLiveModel !== DISABLED_MODEL_SENTINEL &&
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
                        ...LIVE_MODEL_PRESETS,
                        MODEL_DISABLED_OPTION,
                        LIVE_MODEL_CUSTOM_OPTION,
                      ]}
                      className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                      disabled={isRunning}
                    />
                    {liveModelSelection === LIVE_MODEL_CUSTOM_OPTION && (
                      <input
                        type="text"
                        value={liveCustomModel}
                        onChange={(e) => setLiveCustomModel(e.target.value)}
                        placeholder="owner/model-name"
                        disabled={isRunning}
                        className={`focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
                      />
                    )}
                    {!liveModelWhisperOnlyCompatible && (
                      <p className="text-accent-orange text-xs">{liveModeModelConstraintMessage}</p>
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
                        {modelCacheStatus[activeDiarizationModel]?.exists
                          ? 'Downloaded'
                          : 'Missing'}
                      </span>
                    </div>
                  )}
                </div>
                <CustomSelect
                  value={diarizationModelSelection}
                  onChange={setDiarizationModelSelection}
                  options={[DIARIZATION_DEFAULT_MODEL, DIARIZATION_MODEL_CUSTOM_OPTION]}
                  className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  disabled={isRunning}
                />
                {diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION && (
                  <input
                    type="text"
                    value={diarizationCustomModel}
                    onChange={(e) => setDiarizationCustomModel(e.target.value)}
                    placeholder="owner/model-name"
                    disabled={isRunning}
                    className={`focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
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
                    };
                    return (
                      <div
                        key={vol.name}
                        className="flex items-center justify-between py-1 text-sm"
                      >
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
                    {docker.available ? 'No volumes found' : 'Container runtime not available'}
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

          {/* 6. Clean Up */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-2 pl-8 last:border-0 last:pb-0">
            <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
              <AlertTriangle size={14} />
            </div>
            <GlassCard title="6. Clean Up">
              <div className="rounded-xl border border-red-500/25 bg-red-500/5 p-4">
                <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                  <div className="space-y-1">
                    <p className="text-xs font-semibold tracking-wider text-red-300 uppercase">
                      Danger Zone
                    </p>
                    <p className="text-sm text-red-200/90">
                      Stop and remove container, remove all server images, delete runtime, and
                      remove any unchecked persistent resources.
                    </p>
                  </div>
                  <Button
                    variant="danger"
                    size="lg"
                    icon={<AlertTriangle size={16} />}
                    className="ml-auto h-12 w-44 shrink-0 border border-red-400/40 bg-red-500/25 text-red-100 shadow-[0_0_18px_rgba(239,68,68,0.35)] hover:bg-red-500/35"
                    onClick={openCleanAllDialog}
                    disabled={docker.operating || startupFlowPending}
                  >
                    Clean All
                  </Button>
                </div>
              </div>
            </GlassCard>
          </div>
        </div>
      </div>
      <Dialog
        open={isCleanAllDialogOpen}
        onClose={() => {
          if (!docker.operating) setIsCleanAllDialogOpen(false);
        }}
        className="relative z-60"
      >
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <DialogPanel className="w-full max-w-lg overflow-hidden rounded-3xl border border-red-500/25 bg-black/75 shadow-2xl backdrop-blur-xl">
            <div className="border-b border-red-500/20 bg-red-500/10 px-6 py-4">
              <DialogTitle className="text-lg font-semibold text-red-100">Clean All</DialogTitle>
              <p className="mt-1 text-sm text-red-200/90">
                Choose what to keep. Any unchecked resource below will be deleted.
              </p>
            </div>
            <div className="space-y-4 px-6 py-5">
              <p className="text-sm text-slate-300">
                Runtime volume is always removed. Order: container, images, selected volumes, then
                config/cache.
              </p>

              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                <input
                  type="checkbox"
                  checked={keepDataVolume}
                  onChange={(e) => setKeepDataVolume(e.target.checked)}
                  className="text-accent-cyan focus:ring-accent-cyan h-4 w-4 rounded border-white/20 bg-black/30"
                />
                <span className="text-sm text-slate-200">Keep Data Volume</span>
              </label>

              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                <input
                  type="checkbox"
                  checked={keepModelsVolume}
                  onChange={(e) => setKeepModelsVolume(e.target.checked)}
                  className="text-accent-cyan focus:ring-accent-cyan h-4 w-4 rounded border-white/20 bg-black/30"
                />
                <span className="text-sm text-slate-200">Keep Models Volume</span>
              </label>

              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                <input
                  type="checkbox"
                  checked={keepConfigDirectory}
                  onChange={(e) => setKeepConfigDirectory(e.target.checked)}
                  className="text-accent-cyan focus:ring-accent-cyan h-4 w-4 rounded border-white/20 bg-black/30"
                />
                <div>
                  <span className="text-sm text-slate-200">Keep Config Folder</span>
                  {!keepConfigDirectory && (
                    <p className="mt-0.5 text-xs text-slate-400">
                      Settings and session data will be cleared. Some app infrastructure files (GPU
                      cache, etc.) may be recreated while the app is running — restart for a fully
                      clean state.
                    </p>
                  )}
                </div>
              </label>
            </div>
            <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4">
              <Button
                variant="ghost"
                onClick={() => setIsCleanAllDialogOpen(false)}
                disabled={docker.operating}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                icon={<AlertTriangle size={14} />}
                onClick={() => {
                  void handleConfirmCleanAll();
                }}
                disabled={docker.operating || startupFlowPending}
              >
                Clean All
              </Button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
    </>
  );
};
