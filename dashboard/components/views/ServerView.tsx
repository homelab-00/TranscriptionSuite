import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { toast } from 'sonner';
import {
  Box,
  Cpu,
  HardDrive,
  Download,
  Loader2,
  RefreshCw,
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
import { ImageTagChips } from '../ui/ImageTagChips';
import { AppleSwitch } from '../ui/AppleSwitch';
import { NvidiaIcon } from '../ui/icons/NvidiaIcon';
import { AmdIcon } from '../ui/icons/AmdIcon';
import { IntelIcon } from '../ui/icons/IntelIcon';
import { AppleIcon } from '../ui/icons/AppleIcon';
import { GpuHealthCard } from './GpuHealthCard';
import { GpuDiagnosticModal, type GpuDiagnosticResultProp } from './GpuDiagnosticModal';

import { useActivityStore } from '../../src/stores/activityStore';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useServerStatus } from '../../src/hooks/useServerStatus';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { apiClient } from '../../src/api/client';
import { writeToClipboard } from '../../src/hooks/useClipboard';
import { formatDateDMY, compareVersionTags } from '../../src/services/versionUtils';
import { isWhisperModel, isMLXModel } from '../../src/services/modelCapabilities';
import { MODEL_REGISTRY, getModelsByFamily } from '../../src/services/modelRegistry';
import {
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MAIN_MODEL_CUSTOM_OPTION,
  MAIN_RECOMMENDED_MODEL,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  MODEL_DISABLED_OPTION,
  DISABLED_MODEL_SENTINEL,
  WHISPER_MEDIUM,
  MAIN_MODEL_PRESETS,
  LIVE_MODEL_PRESETS,
  VULKAN_RECOMMENDED_MODEL,
  resolveMainModelSelectionValue,
  resolveLiveModelSelectionValue,
  toBackendModelEnvValue,
} from '../../src/services/modelSelection';
import { getModelById } from '../../src/services/modelRegistry';
import type { OptionMeta } from '../ui/CustomSelect';
import { DEFAULT_SERVER_PORT } from '../../src/config/store';
import { isRuntimeProfile, type RuntimeProfile } from '../../src/types/runtime';

const MLX_DEFAULT_MODEL = 'mlx-community/parakeet-tdt-0.6b-v3';

interface ServerViewProps {
  onStartServer: (
    mode: 'local' | 'remote',
    runtimeProfile: RuntimeProfile,
    imageTag?: string,
    models?: {
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
      whispercppModel?: string;
    },
  ) => Promise<void>;
  startupFlowPending: boolean;
}

const DIARIZATION_SORTFORMER_OPTION = 'Sortformer (Metal; ≤ 4 speakers)';
const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';
const DIARIZATION_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
// Mac Metal gating: pyannote.audio 4.x has no working MPS path
// (pyannote/pyannote-audio#1886, #1337, #1091 — all closed wontfix).
const PYANNOTE_REPO_PATTERN = /^pyannote\//i;

// GGML model options for Vulkan sidecar — computed once from registry.
const GGML_MODELS = getModelsByFamily('whispercpp');
const GGML_OPTIONS = GGML_MODELS.map((m) => m.displayName);
const GGML_DISPLAY_TO_ID = new Map(GGML_MODELS.map((m) => [m.displayName, m.id]));
const GGML_ID_TO_DISPLAY = new Map(GGML_MODELS.map((m) => [m.id, m.displayName]));
const GGML_DEFAULT_DISPLAY =
  GGML_ID_TO_DISPLAY.get('ggml-large-v3-turbo.bin') ?? 'GGML Large v3 Turbo';
const ACTIVE_CARD_ACCENT_CLASS = 'border-accent-cyan/40! shadow-[0_0_15px_rgba(34,211,238,0.2)]!';
const FALLBACK_LIVE_WHISPER_MODEL = WHISPER_MEDIUM;

// Static sets for validation — include all models regardless of runtime profile.
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
  DIARIZATION_SORTFORMER_OPTION,
  DIARIZATION_DEFAULT_MODEL,
  DIARIZATION_MODEL_CUSTOM_OPTION,
]);

// IDs of models that require the Metal/MLX runtime.
const MLX_MODEL_IDS = new Set(MODEL_REGISTRY.filter((m) => m.family === 'mlx').map((m) => m.id));

const UI_SENTINEL_VALUES = new Set([
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MAIN_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  DIARIZATION_SORTFORMER_OPTION,
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
let cachedGpuInfo: { gpu: boolean; toolkit: boolean; vulkan: boolean } | null | undefined =
  undefined; // undefined = not yet checked

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
  if (!normalizedModel) {
    return { selection: DIARIZATION_SORTFORMER_OPTION, custom: '' };
  }
  if (normalizedModel === normalizeModelName(DIARIZATION_DEFAULT_MODEL)) {
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
  const [diarizationModelSelection, setDiarizationModelSelection] = useState(
    DIARIZATION_SORTFORMER_OPTION,
  );
  const [diarizationCustomModel, setDiarizationCustomModel] = useState('');
  const [diarizationHydrated, setDiarizationHydrated] = useState(false);
  const [whispercppModelSelection, setWhispercppModelSelection] = useState(GGML_DEFAULT_DISPLAY);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Model download cache state (checks Docker volume for HF model dirs)
  const [modelCacheStatus, setModelCacheStatus] = useState<
    Record<string, { exists: boolean; size?: string }>
  >({});
  const modelCacheCheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Runtime profile (persisted in electron-store)
  const [runtimeProfile, setRuntimeProfile] = useState<RuntimeProfile>('cpu');

  // Legacy-GPU image variant (Issue #83 — Pascal/Maxwell support).
  // Persisted in electron-store under `server.useLegacyGpu`.
  const [useLegacyGpu, setUseLegacyGpu] = useState<boolean>(false);
  const [legacyGpuDialogOpen, setLegacyGpuDialogOpen] = useState(false);
  // Pending state the user confirmed — applied when they accept the dialog.
  const [pendingLegacyGpuValue, setPendingLegacyGpuValue] = useState<boolean | null>(null);
  const [legacyGpuWipeVolume, setLegacyGpuWipeVolume] = useState<boolean>(true);
  // Guards the Confirm button against double-clicks while the IPC is in-flight.
  // Without this, a second click would re-fire `setUseLegacyGpu` with stale
  // `pendingLegacyGpuValue` (React state updates are batched).
  const [legacyGpuConfirmInFlight, setLegacyGpuConfirmInFlight] = useState<boolean>(false);

  // Metal (Apple Silicon) detection – derived from server-side feature check
  const mlxFeature = (adminStatus?.models as any)?.features?.mlx as
    | { available: boolean; reason: string }
    | undefined;
  const metalSupported = mlxFeature?.available ?? false;
  const [isAppleSilicon] = useState<boolean>(() => {
    return (window as any).electronAPI?.app?.getArch?.() === 'arm64';
  });

  // Native storage paths for bare-metal mode (loaded once on mount)
  const [nativeDataDir, setNativeDataDir] = useState<string | null>(null);
  const [nativeModelsDir, setNativeModelsDir] = useState<string | null>(null);
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.app?.getConfigDir) return;
    api.app
      .getConfigDir()
      .then((dir: string) => {
        setNativeDataDir(dir + '/data');
        setNativeModelsDir(dir + '/models');
      })
      .catch(() => {});
  }, []);

  // Derive model option lists filtered by the active runtime profile.
  // Metal mode:     only MLX models (non-MLX need Docker/ctranslate2).
  // Non-Metal mode: only non-MLX models (MLX needs Apple Silicon Metal).
  const isMetal = runtimeProfile === 'metal';
  const mainModelOptions = useMemo(() => {
    const presets = MAIN_MODEL_PRESETS.filter((id) =>
      isMetal ? MLX_MODEL_IDS.has(id) : !MLX_MODEL_IDS.has(id),
    );
    return [...presets, MODEL_DISABLED_OPTION, MAIN_MODEL_CUSTOM_OPTION];
  }, [isMetal]);
  const liveModelOptions = useMemo(() => {
    return [
      LIVE_MODEL_SAME_AS_MAIN_OPTION,
      ...LIVE_MODEL_PRESETS,
      MODEL_DISABLED_OPTION,
      LIVE_MODEL_CUSTOM_OPTION,
    ];
  }, []);
  // Diarization options: omit pyannote on Mac Metal — pyannote.audio MPS path is broken upstream.
  const diarizationOptions = useMemo(
    () =>
      isMetal
        ? [DIARIZATION_SORTFORMER_OPTION, DIARIZATION_MODEL_CUSTOM_OPTION]
        : [
            DIARIZATION_SORTFORMER_OPTION,
            DIARIZATION_DEFAULT_MODEL,
            DIARIZATION_MODEL_CUSTOM_OPTION,
          ],
    [isMetal],
  );

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

  // Vulkan sidecar image prompt state
  const [sidecarNeeded, setSidecarNeeded] = useState<boolean | null>(null); // null = not checked

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
          if (isRuntimeProfile(val)) {
            setRuntimeProfile(val);
            if (val === 'vulkan') {
              docker
                .hasSidecarImage()
                .then((exists) => setSidecarNeeded(!exists))
                .catch(() => {});
            }
          }
        })
        .catch(() => {});
      api.config
        .get('connection.authToken')
        .then((val: unknown) => {
          if (typeof val === 'string') setAuthToken(val);
        })
        .catch(() => {});
    }
    // Issue #83 — load the legacy-GPU toggle through the dedicated IPC.
    if (api?.server?.getUseLegacyGpu) {
      api.server
        .getUseLegacyGpu()
        .then((val: boolean) => setUseLegacyGpu(Boolean(val)))
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
      api.config.get('server.whispercppModel'),
    ])
      .then(
        ([
          storedMainSelection,
          storedMainCustom,
          storedLiveSelection,
          storedLiveCustom,
          storedDiarizationSelection,
          storedDiarizationCustom,
          storedWhispercppModel,
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
            getString(storedDiarizationSelection) ?? DIARIZATION_SORTFORMER_OPTION;
          let nextDiarizationCustom = getString(storedDiarizationCustom) ?? '';

          // Migrate the old 'Auto (best available)' label to the new Sortformer option.
          if (nextDiarizationSelection === 'Auto (best available)') {
            nextDiarizationSelection = DIARIZATION_SORTFORMER_OPTION;
          }

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
              nextDiarizationSelection = DIARIZATION_SORTFORMER_OPTION;
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
          const storedGgml = getString(storedWhispercppModel);
          if (storedGgml) {
            if (GGML_DISPLAY_TO_ID.has(storedGgml)) {
              // Stored as displayName — use directly
              setWhispercppModelSelection(storedGgml);
            } else {
              // Stored as model ID — convert to displayName
              const display = GGML_ID_TO_DISPLAY.get(storedGgml);
              if (display) setWhispercppModelSelection(display);
            }
          }
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

  // Persist runtime profile changes, check sidecar availability for Vulkan, and start/stop MLX for Metal
  const handleRuntimeProfileChange = useCallback(
    async (profile: RuntimeProfile) => {
      setRuntimeProfile(profile);
      const api = (window as any).electronAPI;
      if (api?.config) {
        api.config.set('server.runtimeProfile', profile);
      }
      // Leaving Metal: reset any MLX-only model selections back to non-MLX defaults.
      if (profile !== 'metal') {
        if (MLX_MODEL_IDS.has(mainModelSelection)) {
          setMainModelSelection(MAIN_RECOMMENDED_MODEL);
          api?.config?.set('server.mainModelSelection', MAIN_RECOMMENDED_MODEL);
        }
        if (MLX_MODEL_IDS.has(liveModelSelection)) {
          setLiveModelSelection(LIVE_MODEL_SAME_AS_MAIN_OPTION);
          api?.config?.set('server.liveModelSelection', LIVE_MODEL_SAME_AS_MAIN_OPTION);
        }
      }
      // Handle Vulkan sidecar image check
      if (profile === 'vulkan') {
        docker
          .hasSidecarImage()
          .then((exists) => setSidecarNeeded(!exists))
          .catch(() => {});
      } else {
        setSidecarNeeded(null);
        docker.cancelSidecarPull();
        useActivityStore.getState().updateActivity('sidecar-vulkan', { status: 'dismissed' });
      }
      // Warn if Metal selected on unsupported hardware (still allow the selection)
      if (
        profile === 'metal' &&
        !(isAppleSilicon && (mlxFeature === undefined || metalSupported))
      ) {
        toast.error(
          mlxFeature?.reason === 'not_apple_silicon' || !isAppleSilicon
            ? 'Metal requires Apple Silicon (M-series Mac).'
            : mlxFeature?.reason === 'mlx_whisper_not_installed'
              ? 'mlx-whisper is not installed. Run: uv sync --extra mlx'
              : 'Metal (MLX) is not available on this machine.',
        );
      }

      // Handle MLX native server start/stop for Metal
      if (!api?.mlx) return;
      if (profile !== 'metal') {
        // Leaving Metal — stop the native server if it is running or errored.
        const current = await api.mlx.getStatus().catch(() => 'stopped');
        if (current === 'running' || current === 'starting' || current === 'error') {
          await api.mlx.stop().catch(() => {});
        }
      } else {
        // Entering Metal — start the native server if it is not already up.
        const current = await api.mlx.getStatus().catch(() => 'stopped');
        if (current === 'stopped' || current === 'error') {
          try {
            const port = (await api.config?.get('server.port').catch(() => 9786)) ?? 9786;
            const hfToken = (await api.config?.get('server.hfToken').catch(() => '')) ?? '';
            const storedModel =
              (await api.config?.get('server.mainModelSelection').catch(() => '')) ?? '';
            const storedCustomModel =
              (await api.config?.get('server.mainCustomModel').catch(() => '')) ?? '';
            const storedLiveModel =
              (await api.config?.get('server.liveModelSelection').catch(() => '')) ?? '';
            const storedLiveCustom =
              (await api.config?.get('server.liveCustomModel').catch(() => '')) ?? '';
            const storedDiarizationModel =
              (await api.config?.get('server.diarizationModelSelection').catch(() => '')) ?? '';
            const storedDiarizationCustom_auto =
              (await api.config?.get('server.diarizationCustomModel').catch(() => '')) ?? '';
            const resolvedDiarization =
              storedDiarizationModel === DIARIZATION_MODEL_CUSTOM_OPTION
                ? storedDiarizationCustom_auto.trim()
                : storedDiarizationModel === DIARIZATION_SORTFORMER_OPTION ||
                    storedDiarizationModel === 'Auto (best available)' ||
                    !storedDiarizationModel
                  ? ''
                  : storedDiarizationModel;
            const resolvedMain =
              resolveMainModelSelectionValue(storedModel, storedCustomModel, '') ||
              MLX_DEFAULT_MODEL;
            const resolvedLive = resolveLiveModelSelectionValue(
              storedLiveModel,
              storedLiveCustom,
              resolvedMain,
              '',
            );
            const normalizedLive = normalizeLiveModelToWhisper(resolvedLive);
            await api.mlx.start({
              port: Number(port),
              hfToken: hfToken || undefined,
              mainTranscriberModel: sanitizeModelName(resolvedMain) || MLX_DEFAULT_MODEL,
              liveTranscriberModel: sanitizeModelName(normalizedLive) || undefined,
              diarizationModel: resolvedDiarization || undefined,
            });
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            toast.error(`Failed to start Metal server: ${msg}`);
          }
        }
      }
    },
    [mainModelSelection, liveModelSelection, docker.hasSidecarImage, docker.cancelSidecarPull],
  );
  const containerStatus = docker.container;
  const isRunning = containerStatus.running;
  const isRunningAndHealthy = isRunning && containerStatus.health === 'healthy';

  // MLX (native process) server state
  type MLXStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error';
  const [mlxStatus, setMlxStatus] = useState<MLXStatus>('stopped');

  // Tracks model values used when the MLX server was last started — used to detect
  // changes that require a restart while the server is running.
  const committedModelsRef = useRef<{
    mainTranscriber: string;
    liveModel: string;
    diarizationModel: string;
  } | null>(null);

  // Sync mlxStatus from the main process on mount and subscribe to push updates.
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    api.mlx
      .getStatus()
      .then(setMlxStatus)
      .catch(() => {});
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

    // Only seed model selections from the running server when the user has no
    // locally-persisted preference (still at the loading placeholder). If a real
    // preference was restored from electron-store, keep it — otherwise, navigating
    // away and returning would overwrite the user's selection with whatever model
    // the server happens to be running (which may be an older choice).
    if (mainModelSelection === MODEL_DEFAULT_LOADING_PLACEHOLDER) {
      const mappedMain = mapMainModelToSelection(configuredMainModel);
      const mappedLive = mapLiveModelToSelection(configuredLiveModel, configuredMainModel);

      setMainModelSelection(mappedMain.selection);
      setMainCustomModel(mappedMain.custom);
      setLiveModelSelection(mappedLive.selection);
      setLiveCustomModel(mappedLive.custom);
    }

    setModelsHydrated(true);
  }, [
    adminStatus,
    configuredMainModel,
    configuredLiveModel,
    localSelectionsHydrated,
    mainModelSelection,
    modelsHydrated,
  ]);

  useEffect(() => {
    if (!localSelectionsHydrated || diarizationHydrated || !adminStatus) return;

    // Only seed diarization selection from the running server when no
    // locally-persisted preference exists (still at initial default).
    // If a real preference was restored from electron-store, keep it —
    // otherwise navigating away and returning would overwrite the user's
    // selection with whatever the server reports.
    if (diarizationModelSelection === DIARIZATION_SORTFORMER_OPTION) {
      const mappedDiarization = mapDiarizationModelToSelection(configuredDiarizationModel);
      setDiarizationModelSelection(mappedDiarization.selection);
      setDiarizationCustomModel(mappedDiarization.custom);
    }

    setDiarizationHydrated(true);
  }, [
    adminStatus,
    configuredDiarizationModel,
    diarizationHydrated,
    diarizationModelSelection,
    localSelectionsHydrated,
  ]);

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

  // Active diarization model name — empty string = Sortformer (server auto-select)
  const activeDiarizationModel =
    diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION
      ? diarizationCustomModel.trim() || configuredDiarizationModel || DIARIZATION_DEFAULT_MODEL
      : diarizationModelSelection === DIARIZATION_SORTFORMER_OPTION
        ? ''
        : DIARIZATION_DEFAULT_MODEL;

  // MLX native-process start/stop handlers (depend on activeTranscriber declared above)
  const handleMLXStart = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    try {
      const port = (await api.config?.get('server.port').catch(() => 9786)) ?? 9786;
      const hfToken = (await api.config?.get('server.hfToken').catch(() => '')) ?? '';
      const mainModel = sanitizeModelName(activeTranscriber) || MLX_DEFAULT_MODEL;
      const liveModel = sanitizeModelName(normalizedLiveModel) || undefined;
      const diarizationModel = sanitizeModelName(activeDiarizationModel) || undefined;
      await api.mlx.start({
        port: Number(port),
        hfToken: hfToken || undefined,
        mainTranscriberModel: mainModel,
        liveTranscriberModel: liveModel,
        diarizationModel: diarizationModel,
      });
      committedModelsRef.current = {
        mainTranscriber: mainModel,
        liveModel: liveModel ?? '',
        diarizationModel: diarizationModel ?? '',
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to start Metal server: ${msg}`);
    }
  }, [activeTranscriber, normalizedLiveModel, activeDiarizationModel]);

  const handleMLXStop = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    await api.mlx.stop();
  }, []);

  // Seed committedModelsRef on first render where the MLX server is already running
  // (e.g. app launched with metal profile; server auto-started before view mounted).
  useEffect(() => {
    if (!localSelectionsHydrated || !modelsHydrated || !diarizationHydrated) return;
    if (mlxStatus !== 'running') return;
    if (committedModelsRef.current !== null) return;
    committedModelsRef.current = {
      mainTranscriber: sanitizeModelName(activeTranscriber) || MLX_DEFAULT_MODEL,
      liveModel: sanitizeModelName(normalizedLiveModel) ?? '',
      diarizationModel: sanitizeModelName(activeDiarizationModel) ?? '',
    };
  }, [
    localSelectionsHydrated,
    modelsHydrated,
    diarizationHydrated,
    mlxStatus,
    activeTranscriber,
    normalizedLiveModel,
    activeDiarizationModel,
  ]);

  // Auto-restart the MLX server when the user changes the main transcriber, live model,
  // or diarization model while the server is already running in bare-metal mode.
  useEffect(() => {
    if (!isMetal || !localSelectionsHydrated || !modelsHydrated || !diarizationHydrated) return;
    if (mlxStatus !== 'running') return;
    if (!committedModelsRef.current) return;

    const currentMain = sanitizeModelName(activeTranscriber) || MLX_DEFAULT_MODEL;
    const currentLive = sanitizeModelName(normalizedLiveModel) ?? '';
    const currentDiarization = sanitizeModelName(activeDiarizationModel) ?? '';
    const committed = committedModelsRef.current;

    if (
      currentMain === committed.mainTranscriber &&
      currentLive === committed.liveModel &&
      currentDiarization === committed.diarizationModel
    ) {
      return;
    }

    // Debounce so rapid selection changes (e.g. typing a custom model name)
    // don't trigger multiple consecutive restarts.
    const timerId = setTimeout(async () => {
      const api = (window as any).electronAPI;
      if (!api?.mlx) return;
      // Re-check status at fire time — user may have stopped the server manually.
      const statusNow = await api.mlx.getStatus().catch(() => 'stopped');
      if (statusNow !== 'running') return;
      // Re-check committed ref — a manual start may have updated it already.
      const latestCommitted = committedModelsRef.current;
      if (
        latestCommitted &&
        currentMain === latestCommitted.mainTranscriber &&
        currentLive === latestCommitted.liveModel &&
        currentDiarization === latestCommitted.diarizationModel
      ) {
        return;
      }
      const toastId = toast.loading('Restarting inference server for model change…');
      try {
        await api.mlx.stop();
        const port = (await api.config?.get('server.port').catch(() => 9786)) ?? 9786;
        const hfToken = (await api.config?.get('server.hfToken').catch(() => '')) ?? '';
        await api.mlx.start({
          port: Number(port),
          hfToken: hfToken || undefined,
          mainTranscriberModel: currentMain,
          liveTranscriberModel: currentLive || undefined,
          diarizationModel: currentDiarization || undefined,
        });
        committedModelsRef.current = {
          mainTranscriber: currentMain,
          liveModel: currentLive,
          diarizationModel: currentDiarization,
        };
        toast.success('Inference server restarted.', { id: toastId });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error(`Failed to restart Metal server: ${msg}`, { id: toastId });
      }
    }, 1500);

    return () => clearTimeout(timerId);
  }, [
    isMetal,
    localSelectionsHydrated,
    modelsHydrated,
    diarizationHydrated,
    mlxStatus,
    activeTranscriber,
    normalizedLiveModel,
    activeDiarizationModel,
  ]);

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

  // Mac Metal: auto-migrate persisted Pyannote diarization choice to Sortformer.
  // Single effect handles both initial mount AND mid-session profile toggles
  // (runtimeProfile is hydrated by a separate effect, so we cannot extend the
  // diarization Promise.all chain). The state change is persisted by the
  // existing auto-persist effect at line ~1019. See pyannote/pyannote-audio#1886.
  useEffect(() => {
    if (!isMetal || !diarizationHydrated) return;
    if (diarizationModelSelection !== DIARIZATION_DEFAULT_MODEL) return;
    setDiarizationModelSelection(DIARIZATION_SORTFORMER_OPTION);
  }, [isMetal, diarizationHydrated, diarizationModelSelection]);

  // Metal mode: auto-switch a non-MLX main model to the MLX default.
  useEffect(() => {
    if (!localSelectionsHydrated || runtimeProfile !== 'metal') return;
    const resolved = resolveMainModelSelectionValue(mainModelSelection, mainCustomModel, '');
    if (resolved && !isMLXModel(resolved) && resolved !== MODEL_DEFAULT_LOADING_PLACEHOLDER) {
      setMainModelSelection(MLX_DEFAULT_MODEL);
      setMainCustomModel('');
    }
  }, [runtimeProfile, localSelectionsHydrated, mainModelSelection, mainCustomModel]);

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

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    void api.config.set('server.whispercppModel', whispercppModelSelection).catch(() => {});
  }, [localSelectionsHydrated, whispercppModelSelection]);

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

  // Compute per-option metadata for the Main Transcriber dropdown.
  // Models requiring a different runtime are dimmed with a badge.
  const mainModelOptionMeta = useMemo<Record<string, OptionMeta>>(() => {
    const meta: Record<string, OptionMeta> = {};
    for (const option of MAIN_MODEL_PRESETS) {
      const info = getModelById(option);
      if (!info?.requiresRuntime) continue;
      if (runtimeProfile === 'vulkan' && info.requiresRuntime === 'cuda') {
        meta[option] = { dim: true, badge: 'Requires CUDA' };
      } else if (
        (runtimeProfile === 'gpu' || runtimeProfile === 'cpu') &&
        info.requiresRuntime === 'vulkan'
      ) {
        meta[option] = { dim: true, badge: 'Requires Vulkan' };
      }
    }
    return meta;
  }, [runtimeProfile]);

  // Show a suggestion to use the recommended GGML model when the user switches to Vulkan
  // mode and their current main model selection requires CUDA (not usable in Vulkan mode).
  // Skips sentinels, custom options, and models that are already Vulkan-compatible.
  const showVulkanModelSuggestion =
    runtimeProfile === 'vulkan' &&
    !isRunning &&
    mainModelSelection !== VULKAN_RECOMMENDED_MODEL &&
    mainModelOptionMeta[mainModelSelection]?.badge === 'Requires CUDA';

  // ─── Image tag selection (merged remote + local) ─────────────────────────

  const localTagSet = useMemo(() => new Set(docker.images.map((i) => i.tag)), [docker.images]);

  const localDateMap = useMemo(
    () => new Map(docker.images.map((i) => [i.tag, i.created])),
    [docker.images],
  );

  const hasRemoteTags = docker.remoteTags.length > 0;

  // Build the merged tag list for ImageTagChips
  const { mergedTags, defaultImageTag } = useMemo(() => {
    if (!hasRemoteTags) {
      // Fallback: offline — convert local images to RemoteTag shape, sorted by semver
      const tags = docker.images
        .map((i) => ({ tag: i.tag, created: i.created }))
        .sort((a, b) => compareVersionTags(a.tag, b.tag));
      const def = tags.find((rt) => !/rc/i.test(rt.tag))?.tag ?? tags[0]?.tag ?? 'latest';
      return { mergedTags: tags, defaultImageTag: def };
    }

    // Merge remote tags with local-only tags and sort by semver so local dev
    // builds (e.g. v1.3.1) slot into the correct position in the chip row.
    const remoteTagSet = new Set(docker.remoteTags.map((rt) => rt.tag));
    const localOnly = docker.images
      .filter((i) => !remoteTagSet.has(i.tag))
      .map((i) => ({ tag: i.tag, created: i.created }));

    const tags = [...docker.remoteTags, ...localOnly].sort((a, b) =>
      compareVersionTags(a.tag, b.tag),
    );
    const def = tags.find((rt) => !/rc/i.test(rt.tag))?.tag ?? tags[0]?.tag ?? 'latest';
    return { mergedTags: tags, defaultImageTag: def };
  }, [hasRemoteTags, docker.remoteTags, docker.images]);

  const [selectedImage, setSelectedImage] = useState(defaultImageTag);

  // Reset selection when default changes OR the selected tag disappears from the list
  const prevDefaultRef = useRef(defaultImageTag);
  useEffect(() => {
    const prev = prevDefaultRef.current;
    prevDefaultRef.current = defaultImageTag;
    const allTags = mergedTags.map((rt) => rt.tag);
    if (!allTags.includes(selectedImage)) {
      setSelectedImage(defaultImageTag);
    } else if (prev !== defaultImageTag && !allTags.includes(selectedImage)) {
      setSelectedImage(defaultImageTag);
    }
  }, [defaultImageTag, mergedTags, selectedImage]);

  // Resolve display tag to the value Docker commands need (just the tag string)
  const selectedTagForActions = selectedImage;
  const selectedTagForStart = docker.images.length > 0 ? selectedTagForActions : undefined;

  // ─── Setup Checklist ────────────────────────────────────────────────────────

  const [setupDismissed, setSetupDismissed] = useState(true); // hide until loaded
  const [setupExpanded, setSetupExpanded] = useState(true);
  const [gpuInfo, setGpuInfo] = useState<{
    gpu: boolean;
    toolkit: boolean;
    vulkan: boolean;
  } | null>(cachedGpuInfo ?? null);

  // ─── GPU Health Card state (NVIDIA Linux only) ─────────────────────────────
  // Phase 2 of the CUDA error 999 recovery plan. Three pieces of state feed the
  // GpuHealthCard rendered below the setup checklist:
  //   - gpuPreflight: result of dockerManager.validateGpuPreflight() — cheap
  //     host checks (CDI spec, /dev/char symlinks, nvidia_uvm). Drives the
  //     yellow "may be misconfigured" state when a check fails.
  //   - gpuBackendError: structured object built from useServerStatus()'s
  //     gpuError + gpuErrorRecoveryHint when /api/status reports a GPU failure.
  //     Drives the red "fell back to CPU" state with the recovery hint visible.
  //   - hostPlatform: read once from electronAPI.app.getPlatform() so the card
  //     can gate on Linux without depending on navigator.platform (which may
  //     report 'Linux x86_64' or be absent in jsdom test mounts).
  const [gpuPreflight, setGpuPreflight] = useState<{
    status: 'healthy' | 'warning' | 'unknown';
    checks: Array<{
      name: string;
      pass: boolean;
      fixCommand?: string;
      docsUrl?: string;
    }>;
  } | null>(null);
  const [gpuBackendError, setGpuBackendError] = useState<{
    status: 'unrecoverable';
    error: string;
    recovery_hint?: string;
  } | null>(null);
  const [hostPlatform, setHostPlatform] = useState<string>('unknown');

  // Subscribe to backend GPU error via the existing useServerStatus poll
  // (polls /api/status every 10s through React Query). When the backend
  // reports gpuError, build the structured object the GpuHealthCard expects.
  // The recovery_hint is only present when cuda_health_check matched the
  // error-999 fingerprint; we pass it through verbatim.
  const { gpuError, gpuErrorRecoveryHint } = useServerStatus();
  useEffect(() => {
    if (gpuError) {
      setGpuBackendError({
        status: 'unrecoverable',
        error: gpuError,
        recovery_hint: gpuErrorRecoveryHint ?? undefined,
      });
    } else {
      setGpuBackendError(null);
    }
  }, [gpuError, gpuErrorRecoveryHint]);

  // Read host platform once via electronAPI bridge. Synchronous in production
  // (preload returns process.platform directly); defaults to 'unknown' for
  // jsdom/test mounts that don't expose getPlatform.
  useEffect(() => {
    const api = (window as any).electronAPI;
    const getPlatformFn = api?.app?.getPlatform;
    if (typeof getPlatformFn !== 'function') return;
    try {
      const p = getPlatformFn();
      if (typeof p === 'string' && p) setHostPlatform(p);
    } catch {
      // Best-effort: leave hostPlatform as 'unknown'; card will not render.
    }
  }, []);

  // Run-diagnostic handler for the "Run Full Diagnostic" button on the card.
  // Awaits the docker:runGpuDiagnostic IPC, which spawns scripts/diagnose-gpu.sh,
  // waits for it to finish, parses the log, and returns a structured summary.
  // Result is surfaced in <GpuDiagnosticModal> below — replaces the original
  // window.alert flow.
  const [diagnosticRunning, setDiagnosticRunning] = useState(false);
  const [diagnosticResult, setDiagnosticResult] = useState<GpuDiagnosticResultProp | null>(null);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);

  const handleRunGpuDiagnostic = useCallback((): void => {
    const api = (window as any).electronAPI;
    if (!api?.docker?.runGpuDiagnostic || diagnosticRunning) return;
    setDiagnosticRunning(true);
    api.docker
      .runGpuDiagnostic()
      .then((res: GpuDiagnosticResultProp) => {
        if (res.status === 'unsupported') {
          toast.message('GPU diagnostic is for Linux NVIDIA hosts only.');
          return;
        }
        setDiagnosticResult(res);
        setDiagnosticOpen(true);
      })
      .catch(() => {
        toast.error('Failed to run GPU diagnostic — see console.');
      })
      .finally(() => {
        setDiagnosticRunning(false);
      });
  }, [diagnosticRunning]);

  const handleCloseDiagnostic = useCallback((): void => {
    setDiagnosticOpen(false);
  }, []);

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
        .then((info: { gpu: boolean; toolkit: boolean; vulkan: boolean }) => {
          cachedGpuInfo = info;
          setGpuInfo(info);
          // Auto-set runtime profile based on hardware detection.
          // Runs exactly once: on fresh install or upgrade from a version without the flag.
          // Priority: Metal (Apple Silicon) > NVIDIA GPU > Vulkan (AMD/Intel) > CPU
          api.config
            ?.get('server.gpuAutoDetectDone')
            .then((done: unknown) => {
              if (done === true) return; // already ran — respect user's stored choice
              // Determine best profile for this hardware
              let detected: RuntimeProfile = 'cpu';
              if (metalSupported) {
                detected = 'metal';
              } else if (info.gpu && info.toolkit) {
                detected = 'gpu';
              } else if (info.vulkan) {
                detected = 'vulkan';
              }
              handleRuntimeProfileChange(detected);
              // If Metal was selected, also set the default MLX model
              if (detected === 'metal') {
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
              }
              // Mark auto-detection as done so it never re-runs
              api.config?.set('server.gpuAutoDetectDone', true);
            })
            .catch(() => {});
        })
        .catch(() => {
          cachedGpuInfo = null;
          setGpuInfo(null);
        });
    }
  }, []);

  // Re-fetch GPU preflight whenever an NVIDIA GPU is detected — including
  // re-mounts of ServerView where cachedGpuInfo was already populated by
  // an earlier mount (in which case the GPU-detection effect skips).
  useEffect(() => {
    if (!gpuInfo?.gpu) return;
    const api = (window as any).electronAPI;
    if (!api?.docker?.validateGpuPreflight) return;
    api.docker
      .validateGpuPreflight()
      .then((p: typeof gpuPreflight) => setGpuPreflight(p))
      .catch(() => setGpuPreflight(null));
  }, [gpuInfo?.gpu]);

  // Setup checks — gated by the currently selected runtime profile
  const rtName = docker.runtimeKind ?? 'Docker';
  const gpuSatisfied = gpuInfo?.gpu ?? false;
  // Hardware check (arm64 mac) passes immediately via Electron; server report only
  // refines whether mlx_whisper is actually installed.
  const metalSatisfied = isAppleSilicon && (mlxFeature === undefined || metalSupported);
  const needsDocker = runtimeProfile !== 'metal';
  const needsNvidia = runtimeProfile === 'gpu';
  const needsMetal = runtimeProfile === 'metal';
  const setupChecks = [
    {
      label: `${rtName} installed`,
      ok: docker.available,
      na: !needsDocker,
      hint: !needsDocker
        ? 'Not needed for Metal runtime'
        : (docker.detectionGuidance ?? 'Install Docker Engine, Docker Desktop, or Podman'),
    },
    {
      label: `${rtName} Compose available`,
      ok: docker.composeAvailable,
      na: !needsDocker,
      hint: !needsDocker
        ? 'Not needed for Metal runtime'
        : 'Install docker-compose-v2 (Debian/Ubuntu) or Docker Desktop',
    },
    {
      label: `${rtName} image pulled`,
      ok: docker.images.length > 0,
      na: !needsDocker,
      hint: !needsDocker ? 'Not needed for Metal runtime' : 'Pull an image below to get started',
    },
    {
      label: 'NVIDIA GPU detected',
      ok: gpuSatisfied,
      na: !needsNvidia,
      warn: needsNvidia && gpuInfo !== null && !gpuSatisfied,
      hint: !needsNvidia
        ? 'Not needed for selected runtime'
        : gpuSatisfied
          ? gpuInfo?.toolkit
            ? 'nvidia-container-toolkit ready'
            : 'Run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml'
          : 'Install NVIDIA drivers and nvidia-container-toolkit',
    },
    {
      label: 'Apple Silicon Metal',
      ok: metalSatisfied,
      na: !needsMetal,
      warn: needsMetal && !metalSatisfied,
      hint: !needsMetal
        ? 'Not needed for selected runtime'
        : metalSatisfied
          ? mlxFeature === undefined
            ? 'Apple Silicon detected'
            : 'MLX acceleration available'
          : mlxFeature?.reason === 'not_apple_silicon'
            ? 'Intel Mac — not supported'
            : mlxFeature?.reason === 'mlx_whisper_not_installed'
              ? 'mlx-whisper not installed — run: uv sync --extra mlx'
              : !isAppleSilicon
                ? 'Apple Silicon (arm64) required'
                : 'MLX unavailable',
    },
  ];
  // allPassed: na items (not required for this runtime) count as passing
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

  // Issue 103: shared by the "Fetch Fresh Image" button and the in-banner
  // Retry button so a user can re-attempt without re-navigating after a
  // failure. The activity-store entry tracks the same dlId for both paths.
  // (Avoid issue-number references with a leading hash in scanned files —
  //  the UI-contract color regex matches 3-digit hex shorthand and would
  //  pollute the literal palette.)
  const handleFetchFreshImage = useCallback(async (): Promise<void> => {
    if (!selectedTagForActions) return;
    const dlId = `docker-image-${selectedTagForActions}`;
    const store = useActivityStore.getState();
    store.addActivity({
      id: dlId,
      category: 'download',
      label: `Server Image (${selectedTagForActions})`,
      legacyType: 'docker-image',
    });
    try {
      await docker.pullImage(selectedTagForActions);
      useActivityStore
        .getState()
        .updateActivity(dlId, { status: 'complete', completedAt: Date.now() });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Pull failed';
      useActivityStore.getState().updateActivity(dlId, {
        status: 'error',
        error: msg,
        completedAt: Date.now(),
      });
    }
  }, [docker, selectedTagForActions]);

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
              className={`overflow-hidden rounded-xl border transition-all duration-300 ${allPassed ? 'border-green-500/20 bg-green-500/10' : 'border-accent-orange/20 bg-accent-orange/10'}`}
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
                    {setupChecks.filter((c) => !c.na && c.ok).length}/
                    {setupChecks.filter((c) => !c.na).length} checks passed
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
                      {(check as any).na ? (
                        <MinusCircle size={15} className="shrink-0 text-slate-600" />
                      ) : check.ok ? (
                        <CheckCircle2 size={15} className="shrink-0 text-green-400" />
                      ) : check.warn ? (
                        <AlertTriangle size={15} className="text-accent-orange shrink-0" />
                      ) : (
                        <XCircle size={15} className="shrink-0 text-red-400" />
                      )}
                      <span
                        className={`text-sm ${
                          (check as any).na
                            ? 'text-slate-600'
                            : check.ok
                              ? 'text-slate-300'
                              : 'text-white'
                        }`}
                      >
                        {check.label}
                      </span>
                      <span
                        className={`ml-auto text-xs ${(check as any).na ? 'text-slate-700' : 'text-slate-500'}`}
                      >
                        {check.hint}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/*
            GPU Health card (NVIDIA Linux only). Sits adjacent to the setup
            checklist so all hardware/runtime status is colocated at the top
            of the wizard. Self-gates: returns null when gpuDetected is false,
            so the outer Linux + NVIDIA conditional is the authoritative gate.
            See: dashboard/components/views/GpuHealthCard.tsx
            Plan:  docs/superpowers/plans/2026-04-29-cuda-error-999-recovery.md
          */}
          {hostPlatform === 'linux' && (gpuInfo?.gpu ?? false) && (
            <GpuHealthCard
              gpuDetected={true}
              preflight={gpuPreflight}
              backendError={gpuBackendError}
              onRunDiagnostic={handleRunGpuDiagnostic}
              running={diagnosticRunning}
            />
          )}

          <GpuDiagnosticModal
            isOpen={diagnosticOpen}
            result={diagnosticResult}
            onClose={handleCloseDiagnostic}
          />

          {/* 1. Docker Image or Inference Server (metal) Card */}
          {runtimeProfile === 'metal' ? (
            <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
              <div
                className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${mlxStatus === 'running' ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : mlxStatus === 'starting' || mlxStatus === 'stopping' ? 'bg-accent-orange text-slate-900 shadow-[0_0_15px_rgba(251,146,60,0.5)]' : 'bg-slate-800 text-slate-300'}`}
              >
                <Zap size={14} />
              </div>
              <GlassCard
                title="1. Inference Server"
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
                      disabled={
                        mlxStatus === 'running' ||
                        mlxStatus === 'starting' ||
                        mlxStatus === 'stopping'
                      }
                    >
                      {mlxStatus === 'starting' ? (
                        <>
                          <Loader2 size={14} className="animate-spin" /> Starting…
                        </>
                      ) : (
                        <>
                          <Zap size={14} /> Start Metal Server
                        </>
                      )}
                    </Button>
                    <Button
                      variant="danger"
                      className="h-9 px-4"
                      onClick={handleMLXStop}
                      disabled={mlxStatus !== 'running' && mlxStatus !== 'starting'}
                    >
                      {mlxStatus === 'stopping' ? (
                        <>
                          <Loader2 size={14} className="animate-spin" /> Stopping…
                        </>
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
                            {formatDateDMY(docker.images[0].created) ??
                              docker.images[0].created.split(' ')[0]}
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
                      {/*
                        GH-83 EC-7+12: distinguish "registry returned 404" from
                        "registry returned an empty tag list". The legacy-GPU
                        package (`…-server-legacy`) can legitimately return 404
                        between the GH-83 merge and the first `--variant legacy`
                        publish, leaving the tag chip row empty with no signal.
                        Surface a dedicated unpublished state when we see 404
                        + useLegacyGpu so the user knows to fall back to a
                        local build or wait for the next release instead of
                        silently getting zero chips.
                      */}
                      {docker.remoteTagsStatus === 'not-published' && useLegacyGpu ? (
                        <div className="border-accent-amber/30 bg-accent-amber/5 rounded-lg border px-3 py-2 text-xs text-slate-400">
                          Legacy image not yet published for this release. Pull a default image and
                          toggle legacy mode off, or wait for the next release.
                        </div>
                      ) : (
                        <ImageTagChips
                          remoteTags={mergedTags}
                          localTags={localTagSet}
                          localDates={localDateMap}
                          value={selectedImage}
                          onChange={setSelectedImage}
                        />
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col justify-end space-y-2">
                    <Button
                      variant="secondary"
                      className="h-10 w-full"
                      onClick={handleFetchFreshImage}
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
                        onClick={() => {
                          docker.cancelPull();
                          const dlId = `docker-image-${selectedTagForActions}`;
                          useActivityStore.getState().updateActivity(dlId, { status: 'dismissed' });
                        }}
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
                  <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                    <span className="min-w-0 flex-1">{docker.operationError}</span>
                    {selectedTagForActions && (
                      <Button
                        variant="secondary"
                        size="sm"
                        className="shrink-0"
                        onClick={handleFetchFreshImage}
                        disabled={docker.operating || docker.pulling}
                      >
                        Retry
                      </Button>
                    )}
                  </div>
                )}
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
                            ...(runtimeProfile === 'vulkan'
                              ? {
                                  whispercppModel: `/models/${GGML_DISPLAY_TO_ID.get(whispercppModelSelection) ?? 'ggml-large-v3-turbo.bin'}`,
                                }
                              : {}),
                          })
                        }
                        disabled={
                          docker.operating ||
                          isRunning ||
                          startupFlowPending ||
                          !liveModelWhisperOnlyCompatible ||
                          (needsDocker && !docker.composeAvailable)
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
                            ...(runtimeProfile === 'vulkan'
                              ? {
                                  whispercppModel: `/models/${GGML_DISPLAY_TO_ID.get(whispercppModelSelection) ?? 'ggml-large-v3-turbo.bin'}`,
                                }
                              : {}),
                          })
                        }
                        disabled={
                          docker.operating ||
                          isRunning ||
                          startupFlowPending ||
                          !liveModelWhisperOnlyCompatible ||
                          (needsDocker && !docker.composeAvailable)
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

          {/* 2. Instance Settings Card */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
            <div
              className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${isRunning || mlxStatus === 'running' ? `bg-accent-cyan text-slate-900 ${isRunningAndHealthy || mlxStatus === 'running' ? 'shadow-[0_0_15px_rgba(34,211,238,0.5)]' : ''}` : containerStatus.exists ? 'bg-accent-orange text-slate-900 shadow-[0_0_15px_rgba(251,146,60,0.5)]' : 'bg-slate-800 text-slate-300'}`}
            >
              <Box size={16} />
            </div>
            <GlassCard
              title="2. Instance Settings"
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
                      <NvidiaIcon size={14} />
                      GPU (CUDA)
                    </button>
                    <button
                      onClick={() => handleRuntimeProfileChange('vulkan')}
                      disabled={isRunning}
                      className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all ${
                        runtimeProfile === 'vulkan'
                          ? 'bg-accent-rose/15 border-accent-rose/40 text-accent-rose shadow-[0_0_10px_rgba(244,63,94,0.15)]'
                          : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                      } ${isRunning ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                    >
                      <span className="flex h-5 w-10 flex-col items-center justify-center -space-y-1">
                        <AmdIcon size={30} />
                        <IntelIcon size={30} />
                      </span>
                      GPU (Vulkan)
                    </button>
                    <button
                      onClick={() => handleRuntimeProfileChange('metal')}
                      disabled={isRunning}
                      className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all ${
                        runtimeProfile === 'metal'
                          ? 'border-violet-500/40 bg-violet-500/15 text-violet-400 shadow-[0_0_10px_rgba(167,139,250,0.15)]'
                          : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                      } ${isRunning ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                    >
                      <AppleIcon size={14} />
                      GPU (Metal)
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
                  {runtimeProfile === 'vulkan' && !isRunning && (
                    <span className="text-xs text-slate-500 italic">
                      AMD/Intel GPU via whisper.cpp — no diarization or live mode
                    </span>
                  )}
                  {runtimeProfile === 'cpu' && !isRunning && (
                    <span className="text-xs text-slate-500 italic">
                      Slower transcription, no NVIDIA GPU required
                    </span>
                  )}
                </div>

                {/*
                  Legacy-GPU image toggle (Issue #83 — Pascal/Maxwell support).
                  Gated to GPU (CUDA) runtime only: the cu126 wheels are
                  pointless on Vulkan, CPU, or Metal, and surfacing the toggle
                  there would invite confusion. Pascal/Maxwell users must
                  pick GPU (CUDA) first — the README's §2.4 note tells them so.
                  Switching repos requires a container restart and clears the
                  runtime volume so the next bootstrap re-syncs wheels from the
                  new PyTorch index — this is handled via a confirmation dialog.
                */}
                {runtimeProfile === 'gpu' && (
                  <div className="flex items-center gap-3 border-b border-white/5 pb-4">
                    <AppleSwitch
                      checked={useLegacyGpu}
                      // Disabled when the container exists at all — even stopped
                      // containers still hold a reference to the runtime volume,
                      // so the wipe-on-toggle would silently fail. User must
                      // remove the container (Stop + cleanup) before switching.
                      disabled={isRunning || containerStatus.exists}
                      onChange={(next) => {
                        // Don't apply immediately — show the confirmation
                        // dialog so the user acknowledges the restart
                        // requirement and chooses the wipe-volume option.
                        setPendingLegacyGpuValue(next);
                        setLegacyGpuWipeVolume(true);
                        setLegacyGpuDialogOpen(true);
                      }}
                      size="sm"
                    />
                    <span className="text-sm font-medium text-slate-300">
                      Use legacy-GPU image (GTX 10-series / 900-series and older)
                    </span>
                    <span className="text-xs text-slate-500 italic">
                      {containerStatus.exists && !isRunning
                        ? 'Remove the existing container to switch variants'
                        : 'cu126 wheels — required for Pascal/Maxwell cards (GTX 1050–1080 Ti, GTX 900s, Tesla P/M, Quadro P/M)'}
                    </span>
                  </div>
                )}
                {runtimeProfile === 'vulkan' && !isRunning && sidecarNeeded && (
                  <div className="border-accent-rose/20 bg-accent-rose/5 flex items-center gap-3 rounded-lg border px-4 py-3">
                    {docker.sidecarPulling ? (
                      <>
                        <Loader2 size={14} className="text-accent-rose animate-spin" />
                        <span className="text-sm text-slate-300">
                          Downloading Vulkan sidecar image...
                        </span>
                        <button
                          onClick={() => {
                            docker.cancelSidecarPull();
                            useActivityStore
                              .getState()
                              .updateActivity('sidecar-vulkan', { status: 'dismissed' });
                          }}
                          className="ml-auto text-xs text-slate-400 underline hover:text-slate-200"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <Download size={14} className="text-accent-rose" />
                        <span className="text-sm text-slate-300">
                          {docker.operationError
                            ? `Download failed: ${docker.operationError}`
                            : 'Vulkan mode requires the whisper.cpp sidecar image.'}
                        </span>
                        <Button
                          variant="secondary"
                          className="ml-auto h-8 px-3 text-xs"
                          disabled={docker.operating}
                          onClick={async () => {
                            const dlId = 'sidecar-vulkan';
                            useActivityStore.getState().addActivity({
                              id: dlId,
                              category: 'download',
                              label: 'Vulkan Sidecar (whisper.cpp)',
                              legacyType: 'sidecar-image',
                            });
                            try {
                              await docker.pullSidecarImage();
                              useActivityStore.getState().updateActivity(dlId, {
                                status: 'complete',
                                completedAt: Date.now(),
                              });
                            } catch (err: unknown) {
                              const msg = err instanceof Error ? err.message : 'Pull failed';
                              useActivityStore.getState().updateActivity(dlId, {
                                status: 'error',
                                error: msg,
                                completedAt: Date.now(),
                              });
                            }
                            const hasIt = await docker.hasSidecarImage();
                            if (hasIt) setSidecarNeeded(false);
                          }}
                        >
                          Download
                        </Button>
                        <button
                          onClick={() => setSidecarNeeded(false)}
                          className="text-xs text-slate-500 hover:text-slate-300"
                        >
                          Skip
                        </button>
                      </>
                    )}
                  </div>
                )}

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
                      options={mainModelOptions}
                      optionMeta={mainModelOptionMeta}
                      accentColor="magenta"
                      className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                      disabled={isRunning}
                    />
                    {showVulkanModelSuggestion && (
                      <p className="text-xs text-amber-400">
                        Vulkan mode works best with GGML models.{' '}
                        <button
                          className="underline hover:text-amber-300"
                          onClick={() => setMainModelSelection(VULKAN_RECOMMENDED_MODEL)}
                        >
                          Use {VULKAN_RECOMMENDED_MODEL}
                        </button>
                      </p>
                    )}
                    {runtimeProfile === 'vulkan' && (
                      <p className="text-xs text-slate-500 italic">
                        Switching models requires a server restart.
                      </p>
                    )}
                    {runtimeProfile === 'vulkan' && (
                      <div className="space-y-1.5">
                        <label className="text-xs font-medium text-purple-400">
                          GGML Sidecar Model
                        </label>
                        <CustomSelect
                          value={whispercppModelSelection}
                          onChange={setWhispercppModelSelection}
                          options={GGML_OPTIONS}
                          className="h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1 focus:ring-purple-400"
                          disabled={isRunning}
                        />
                      </div>
                    )}
                    {MLX_MODEL_IDS.has(mainModelSelection) && (
                      <p className="flex items-center gap-1 text-xs text-violet-400">
                        <Zap size={10} />
                        Metal / MLX accelerated
                      </p>
                    )}
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
                      options={liveModelOptions}
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
                  options={diarizationOptions}
                  className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  disabled={isRunning}
                />
                {isMetal && (
                  <p className="text-xs text-slate-500 italic">
                    Pyannote diarization is not supported on Apple Silicon (pyannote.audio MPS path
                    is broken upstream — see pyannote/pyannote-audio#1886). Sortformer (Metal) is
                    the recommended diarizer on Mac.
                  </p>
                )}
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
                {isMetal &&
                  diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION &&
                  PYANNOTE_REPO_PATTERN.test(diarizationCustomModel.trim()) && (
                    <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                      <span>
                        Custom pyannote repos are not supported on Apple Silicon — switch to
                        Sortformer.
                      </span>
                    </div>
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
                !isMetal ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<RefreshCw size={14} />}
                    onClick={() => docker.refreshVolumes()}
                  >
                    Refresh
                  </Button>
                ) : undefined
              }
            >
              <div className="space-y-4">
                {isMetal ? (
                  // Bare-metal mode: show native filesystem paths instead of Docker volumes
                  <>
                    {[
                      { label: 'Data directory', path: nativeDataDir, color: 'bg-blue-500' },
                      {
                        label: 'Models cache (HF_HOME)',
                        path: nativeModelsDir,
                        color: 'bg-purple-500',
                      },
                    ].map(({ label, path: dir, color }) => (
                      <div key={label} className="flex items-center justify-between py-1 text-sm">
                        <div className="flex items-center gap-3">
                          <div className={`h-2 w-2 rounded-full ${color}`} />
                          <span className="text-slate-300">{label}</span>
                        </div>
                        <span
                          className="max-w-[55%] truncate text-right font-mono text-xs text-slate-400"
                          title={dir ?? ''}
                        >
                          {dir ?? '…'}
                        </span>
                      </div>
                    ))}
                    <p className="text-xs text-slate-500 italic">
                      Managed by the native server process. Delete these directories to clear cached
                      models or transcription data.
                    </p>
                  </>
                ) : docker.volumes.length > 0 ? (
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

                {!isMetal && docker.volumes.length > 0 && (
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

      {/*
        Legacy-GPU image toggle confirmation (Issue #83).
        Switching repos requires a container restart; offering to wipe the
        runtime volume ensures the next bootstrap re-syncs wheels from the
        new PyTorch index. If the container is still running, the wipe is
        best-effort — the IPC handler logs a warning and the user should
        stop the container first.
      */}
      <Dialog
        open={legacyGpuDialogOpen}
        onClose={() => {
          setLegacyGpuDialogOpen(false);
          setPendingLegacyGpuValue(null);
        }}
        className="relative z-60"
      >
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <DialogPanel className="border-accent-orange/25 w-full max-w-lg overflow-hidden rounded-3xl border bg-black/75 shadow-2xl backdrop-blur-xl">
            <div className="border-accent-orange/20 bg-accent-orange/10 border-b px-6 py-4">
              <DialogTitle className="text-accent-orange text-lg font-semibold">
                {pendingLegacyGpuValue ? 'Enable legacy-GPU image?' : 'Disable legacy-GPU image?'}
              </DialogTitle>
              <p className="mt-1 text-sm text-slate-300">
                {pendingLegacyGpuValue
                  ? 'Switches to the cu126 image for Pascal/Maxwell cards (GTX 10-series, GTX 900s, Tesla P/M, Quadro P/M — sm_50..sm_61).'
                  : 'Switches back to the default cu129 image for modern GPUs (sm_70 and newer).'}
              </p>
            </div>
            <div className="space-y-4 px-6 py-5">
              <p className="text-sm text-slate-300">
                This change requires a container restart. Any currently-running container will keep
                its existing image until you stop and restart it.
              </p>
              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                <input
                  type="checkbox"
                  checked={legacyGpuWipeVolume}
                  onChange={(e) => setLegacyGpuWipeVolume(e.target.checked)}
                  className="text-accent-cyan focus:ring-accent-cyan h-4 w-4 rounded border-white/20 bg-black/30"
                />
                <div>
                  <span className="text-sm text-slate-200">
                    Wipe runtime volume now (recommended)
                  </span>
                  <p className="mt-0.5 text-xs text-slate-400">
                    Forces the next bootstrap to re-sync PyTorch wheels from the new index. Skip
                    only if you plan to wipe it yourself.
                  </p>
                </div>
              </label>
            </div>
            <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4">
              <Button
                variant="ghost"
                onClick={() => {
                  setLegacyGpuDialogOpen(false);
                  setPendingLegacyGpuValue(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={legacyGpuConfirmInFlight}
                onClick={() => {
                  const next = pendingLegacyGpuValue;
                  if (next === null || legacyGpuConfirmInFlight) {
                    setLegacyGpuDialogOpen(false);
                    return;
                  }
                  const api = (window as any).electronAPI;
                  if (!api?.server?.setUseLegacyGpu) {
                    setLegacyGpuDialogOpen(false);
                    setPendingLegacyGpuValue(null);
                    return;
                  }
                  setLegacyGpuConfirmInFlight(true);
                  // Close + clear the pending value synchronously so the dialog
                  // dismisses immediately. The promise chain uses the captured
                  // `next` local instead of reading state, so later updates
                  // remain correct even if the user dismisses via Escape.
                  setLegacyGpuDialogOpen(false);
                  setPendingLegacyGpuValue(null);
                  // GH-99: clear stale remote-tag chips synchronously so the
                  // user doesn't see default-repo tags while the legacy repo
                  // is being queried (the IPC + refetch takes ~1-2s).
                  docker.clearRemoteTags?.();
                  api.server
                    .setUseLegacyGpu(next, legacyGpuWipeVolume)
                    .then(
                      (result: {
                        useLegacyGpu: boolean;
                        runtimeVolumeWiped: boolean;
                        runtimeVolumeWipeError: string | null;
                      }) => {
                        setUseLegacyGpu(next);
                        // GH-99: re-fetch against the now-active variant's
                        // GHCR repo. Fire-and-forget — refresh errors surface
                        // through the existing `remoteTagsStatus` channel.
                        void docker.refreshRemoteTags?.();
                        const base = `${next ? 'Enabled' : 'Disabled'} legacy-GPU image. `;
                        if (legacyGpuWipeVolume && !result.runtimeVolumeWiped) {
                          // Wipe was requested but failed — tell the user so
                          // they know the runtime volume still holds old wheels.
                          toast.error(
                            base +
                              `Runtime volume wipe failed${
                                result.runtimeVolumeWipeError
                                  ? `: ${result.runtimeVolumeWipeError}`
                                  : ''
                              }. Remove the container and try again.`,
                          );
                        } else {
                          toast.success(base + 'Restart the container to apply.');
                        }
                      },
                    )
                    .catch((err: unknown) => {
                      const msg = err instanceof Error ? err.message : String(err);
                      toast.error(`Failed to update legacy-GPU setting: ${msg}`);
                    })
                    .finally(() => {
                      setLegacyGpuConfirmInFlight(false);
                    });
                }}
              >
                {legacyGpuConfirmInFlight ? 'Confirming…' : 'Confirm'}
              </Button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
    </>
  );
};
