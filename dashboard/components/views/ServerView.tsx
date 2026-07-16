import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { toast } from 'sonner';
import {
  Cpu,
  HardDrive,
  Download,
  Globe,
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
  FolderOpen,
  Laptop,
  Radio,
  SlidersHorizontal,
  Zap,
  MinusCircle,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { ImageTagChips } from '../ui/ImageTagChips';
import { AppleSwitch } from '../ui/AppleSwitch';
import { SelectorGroup } from '../ui/SelectorGroup';
import { SelectorTile } from '../ui/SelectorTile';
import { NvidiaIcon } from '../ui/icons/NvidiaIcon';
import { AmdIcon } from '../ui/icons/AmdIcon';
import { IntelIcon } from '../ui/icons/IntelIcon';
import { AppleIcon } from '../ui/icons/AppleIcon';
import { GpuHealthCard } from './GpuHealthCard';
import { GpuDiagnosticModal, type GpuDiagnosticResultProp } from './GpuDiagnosticModal';
import { InstanceSettingsSelectors } from './server/InstanceSettingsSelectors';
import { RemoteConnectionCard } from './server/RemoteConnectionCard';
import { StartupActivityInline } from './server/StartupActivityInline';

import { useNotificationsStore } from '../../src/stores/notificationsStore';
import { SERVER_START_ID } from '../../src/utils/startupEventMapping';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useServerStatus } from '../../src/hooks/useServerStatus';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { useModelCache } from '../../src/hooks/useModelCache';
import { useModelDownloads } from '../../src/hooks/useModelDownloads';
import { apiClient } from '../../src/api/client';
import { writeToClipboard } from '../../src/hooks/useClipboard';
import { formatDateDMY, compareVersionTags } from '../../src/services/versionUtils';
import {
  isWhisperModel,
  isWhisperCppModel,
  isMLXModel,
  isSenseVoiceModel,
} from '../../src/services/modelCapabilities';
import { getModelsByFamily } from '../../src/services/modelRegistry';
import {
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  LEGACY_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  MODEL_DISABLED_OPTION,
  DISABLED_MODEL_SENTINEL,
  WHISPER_MEDIUM,
  MAIN_MODEL_PRESETS,
  MAIN_RECOMMENDED_MODEL,
  LIVE_MODEL_PRESETS,
  VULKAN_RECOMMENDED_MODEL,
  resolveMainModelSelectionValue,
  resolveLiveModelSelectionValue,
  toBackendModelEnvValue,
} from '../../src/services/modelSelection';
import {
  DIARIZATION_CAMPP_OPTION,
  DIARIZATION_DEFAULT_MODEL,
  DIARIZATION_SORTFORMER_OPTION,
  MLX_DEFAULT_MODEL,
  defaultMainModelFor,
  familyChoiceForModel,
  isFamilyChoiceEnabledFor,
  liveModelsFor,
  modelsForFamilyChoice,
} from '../../src/services/instanceMatrix';
import { isRuntimeProfile, type RuntimeProfile } from '../../src/types/runtime';

interface ServerViewProps {
  onStartServer: (
    mode: 'local' | 'remote',
    runtimeProfile: RuntimeProfile,
    imageTag?: string,
    models?: {
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
      sensevoiceDiarizationEngine?: string;
      whispercppModel?: string;
    },
  ) => Promise<void>;
  startupFlowPending: boolean;
}

// The diarization option strings (CAM++, Sortformer, pyannote, Custom) are
// persisted verbatim in electron-store and now live in instanceMatrix.ts.
// CAM++ sends SENSEVOICE_DIARIZATION_ENGINE=funasr with an EMPTY
// DIARIZATION_MODEL, so the server keeps its config.yaml pyannote default as
// the fallback diarizer if cam++ fails to load.
// CAM++'s HuggingFace repo (cache dir models--funasr--campplus). Used only for
// the download badge / cache check, since CAM++ sends an empty DIARIZATION_MODEL.
const CAMPP_HF_REPO = 'funasr/campplus';

// GGML models for the Vulkan sidecar — computed once from registry. In Vulkan
// mode these populate the Main Transcriber dropdown (Branch B: the main pick
// drives the sidecar). GGML_DISPLAY_TO_ID is retained only to migrate the
// legacy `server.whispercppModel` value (persisted as a display name).
const GGML_MODELS = getModelsByFamily('whispercpp');
const GGML_DISPLAY_TO_ID = new Map(GGML_MODELS.map((m) => [m.displayName, m.id]));
const ACTIVE_CARD_ACCENT_CLASS = 'border-accent-cyan/40! shadow-[0_0_15px_rgba(34,211,238,0.2)]!';
const FALLBACK_LIVE_WHISPER_MODEL = WHISPER_MEDIUM;

// Static sets for validation — include all models regardless of runtime profile.
const MAIN_MODEL_SELECTION_OPTIONS = new Set([
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  ...MAIN_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
]);
const LIVE_MODEL_SELECTION_OPTIONS = new Set([
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  ...LIVE_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
]);
const DIARIZATION_MODEL_SELECTION_OPTIONS = new Set([
  DIARIZATION_CAMPP_OPTION,
  DIARIZATION_SORTFORMER_OPTION,
  DIARIZATION_DEFAULT_MODEL,
]);

const UI_SENTINEL_VALUES = new Set([
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  LEGACY_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  DIARIZATION_CAMPP_OPTION,
  DIARIZATION_SORTFORMER_OPTION,
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

// Session-level GPU detection cache — survives view unmount/remount.
// `wslSupport` is populated by `checkGpu()` only on Win32 (GH-101 follow-up);
// it gates the experimental Vulkan-WSL2 runtime profile button below.
let cachedGpuInfo:
  | {
      gpu: boolean;
      toolkit: boolean;
      vulkan: boolean;
      wslSupport?: { available: boolean; gpuPassthroughDetected: boolean; reason?: string };
    }
  | null
  | undefined = undefined; // undefined = not yet checked

function normalizeModelName(value: string): string {
  return value.trim().toLowerCase();
}

function findCaseInsensitivePreset(value: string, options: string[]): string | null {
  const normalizedValue = normalizeModelName(value);
  if (!normalizedValue) return null;
  const match = options.find((option) => normalizeModelName(option) === normalizedValue);
  return match ?? null;
}

function isLiveCompatibleModel(modelName: string): boolean {
  return isWhisperModel(modelName) || isWhisperCppModel(modelName);
}

function normalizeLiveModelToWhisper(modelName: string): string {
  if (modelName === DISABLED_MODEL_SENTINEL) return modelName;
  return isLiveCompatibleModel(modelName) ? modelName : FALLBACK_LIVE_WHISPER_MODEL;
}

// Map server-reported model names to UI selections. The custom-repo option is
// gone, so a model the pickers cannot represent falls back to a preset default
// instead of a "Custom" selection.
function mapMainModelToSelection(modelName: string): string {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel || normalizedModel === normalizeModelName(DISABLED_MODEL_SENTINEL)) {
    return MODEL_DISABLED_OPTION;
  }
  return findCaseInsensitivePreset(modelName, MAIN_MODEL_PRESETS) ?? MAIN_RECOMMENDED_MODEL;
}

function mapLiveModelToSelection(modelName: string, mainModelName: string): string {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel || normalizedModel === normalizeModelName(DISABLED_MODEL_SENTINEL)) {
    return MODEL_DISABLED_OPTION;
  }

  const normalizedLiveModel = normalizeLiveModelToWhisper(modelName);
  if (
    isLiveCompatibleModel(mainModelName) &&
    normalizeModelName(normalizedLiveModel) === normalizeModelName(mainModelName)
  ) {
    return LIVE_MODEL_SAME_AS_MAIN_OPTION;
  }

  return (
    findCaseInsensitivePreset(normalizedLiveModel, LIVE_MODEL_PRESETS) ??
    FALLBACK_LIVE_WHISPER_MODEL
  );
}

function mapDiarizationModelToSelection(modelName: string): string {
  const normalizedModel = normalizeModelName(modelName);
  if (!normalizedModel) {
    return DIARIZATION_SORTFORMER_OPTION;
  }
  return DIARIZATION_DEFAULT_MODEL;
}

export const ServerView: React.FC<ServerViewProps> = ({ onStartServer, startupFlowPending }) => {
  const { status: adminStatus, refresh: refreshAdminStatus } = useAdminStatus();
  const docker = useDockerContext();

  // Model selection state
  const [mainModelSelection, setMainModelSelection] = useState(MODEL_DEFAULT_LOADING_PLACEHOLDER);
  const [liveModelSelection, setLiveModelSelection] = useState(LIVE_MODEL_SAME_AS_MAIN_OPTION);
  const [localSelectionsHydrated, setLocalSelectionsHydrated] = useState(false);
  const [modelsHydrated, setModelsHydrated] = useState(false);
  const [diarizationModelSelection, setDiarizationModelSelection] = useState(
    DIARIZATION_SORTFORMER_OPTION,
  );
  const [diarizationHydrated, setDiarizationHydrated] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Model download cache check debounce timer. The cache state itself lives
  // in useModelCache (wired below, once isRunning/isMetal are defined) so it
  // has exactly one owner shared with the Model Manager modal.
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

  // Per-row "copied" feedback for the persistent-volume path actions (GH-137).
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  // Open a native directory in the OS file manager; on failure (e.g. the dir
  // does not exist yet) fall back to its parent.
  const handleOpenNativePath = useCallback(async (dir: string | null) => {
    if (!dir) return;
    const api = (window as any).electronAPI;
    if (!api?.app?.openPath) return;
    try {
      const err: string = await api.app.openPath(dir);
      if (err) {
        const parent = dir.replace(/[\\/]+[^\\/]*[\\/]*$/, '');
        if (parent && parent !== dir) await api.app.openPath(parent).catch(() => {});
      }
    } catch {
      /* best-effort — opening a folder must never crash the view */
    }
  }, []);

  const handleCopyNativePath = useCallback((dir: string | null, label: string) => {
    if (!dir) return;
    writeToClipboard(dir).catch(() => {});
    setCopiedPath(label);
    setTimeout(() => setCopiedPath((c) => (c === label ? null : c)), 2000);
  }, []);

  // Runtime profile shorthands. Valid model families, live options and
  // diarization engines per runtime are encoded in instanceMatrix.ts and
  // rendered by InstanceSettingsSelectors.
  const isMetal = runtimeProfile === 'metal';
  const isVulkan = runtimeProfile === 'vulkan' || runtimeProfile === 'vulkan-wsl2';

  // Clean-all modal state
  const [isCleanAllDialogOpen, setIsCleanAllDialogOpen] = useState(false);
  const [keepDataVolume, setKeepDataVolume] = useState(false);
  const [keepModelsVolume, setKeepModelsVolume] = useState(false);
  const [keepConfigDirectory, setKeepConfigDirectory] = useState(false);

  // Vulkan sidecar image prompt state
  const [sidecarNeeded, setSidecarNeeded] = useState<boolean | null>(null); // null = not checked

  // Server mode badge (local vs remote)
  const [serverMode, setServerMode] = useState<'local' | 'remote' | null>(null);

  // Load persisted runtime profile and legacy-GPU toggle on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('server.runtimeProfile')
        .then((val: unknown) => {
          if (isRuntimeProfile(val)) {
            // Normalize stale 'vulkan-wsl2' if the profile was persisted on a
            // Win32 host and the user has since moved the dashboard to Linux
            // or macOS (GH-101 follow-up). Otherwise the four-button row in
            // the Instance Settings card would show no active state at all,
            // and the user would have to dig through Settings to recover.
            // Falling back to 'cpu' is the safe universal default; the
            // auto-detect block below will pick a better profile if eligible
            // (only runs once per machine, gated by `gpuAutoDetectDone`).
            const normalized: RuntimeProfile =
              val === 'vulkan-wsl2' && (window as any).electronAPI?.app?.getPlatform?.() !== 'win32'
                ? 'cpu'
                : val;
            setRuntimeProfile(normalized);
            if (normalized !== val) {
              api.config?.set?.('server.runtimeProfile', normalized).catch(() => {});
            }
            if (normalized === 'vulkan') {
              docker
                .hasSidecarImage()
                .then((exists) => setSidecarNeeded(!exists))
                .catch(() => {});
            }
          }
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
      api.config.get('server.sensevoiceDiarizationEngine'),
      api.config.get('server.whispercppModel'),
      api.config.get('server.runtimeProfile'),
    ])
      .then(
        ([
          storedMainSelection,
          storedMainCustom,
          storedLiveSelection,
          storedLiveCustom,
          storedDiarizationSelection,
          storedDiarizationCustom,
          storedSensevoiceEngine,
          storedWhispercppModel,
          storedRuntimeProfile,
        ]: unknown[]) => {
          if (!active) return;

          // ── Legacy custom-repo migration ──────────────────────────────────
          // The "Custom (HuggingFace repo)" option was removed. If a stored
          // selection is the old Custom sentinel, adopt the stored custom text
          // as the candidate model name — it may match a preset (e.g. a repo
          // that later became a registry model); anything else falls through
          // the unknown-value fallbacks below. The retired custom keys are
          // cleared afterwards so this can never re-fire.
          let nextMainSelection =
            getString(storedMainSelection) ?? MODEL_DEFAULT_LOADING_PLACEHOLDER;
          if (nextMainSelection === LEGACY_CUSTOM_OPTION) {
            nextMainSelection = getString(storedMainCustom) ?? '';
          }

          if (!MAIN_MODEL_SELECTION_OPTIONS.has(nextMainSelection)) {
            if (
              normalizeModelName(nextMainSelection) === normalizeModelName(DISABLED_MODEL_SENTINEL)
            ) {
              nextMainSelection = MODEL_DISABLED_OPTION;
            } else {
              nextMainSelection =
                findCaseInsensitivePreset(nextMainSelection, MAIN_MODEL_PRESETS) ??
                MODEL_DEFAULT_LOADING_PLACEHOLDER;
            }
          }

          let nextLiveSelection = getString(storedLiveSelection) ?? LIVE_MODEL_SAME_AS_MAIN_OPTION;
          if (nextLiveSelection === LEGACY_CUSTOM_OPTION) {
            nextLiveSelection = getString(storedLiveCustom) ?? '';
          }

          if (!LIVE_MODEL_SELECTION_OPTIONS.has(nextLiveSelection)) {
            if (
              normalizeModelName(nextLiveSelection) === normalizeModelName(DISABLED_MODEL_SENTINEL)
            ) {
              nextLiveSelection = MODEL_DISABLED_OPTION;
            } else {
              nextLiveSelection =
                findCaseInsensitivePreset(nextLiveSelection, LIVE_MODEL_PRESETS) ??
                LIVE_MODEL_SAME_AS_MAIN_OPTION;
            }
          }

          const resolvedMainModel = resolveMainModelSelectionValue(nextMainSelection, '');
          const resolvedLiveModel = resolveLiveModelSelectionValue(
            nextLiveSelection,
            resolvedMainModel,
          );
          if (
            resolvedLiveModel !== DISABLED_MODEL_SENTINEL &&
            !isLiveCompatibleModel(resolvedLiveModel)
          ) {
            nextLiveSelection = FALLBACK_LIVE_WHISPER_MODEL;
          }

          // ── Merged diarization control (one-shot migration) ──────────────
          // The diarization engine used to be a second, separate dropdown backed by
          // server.sensevoiceDiarizationEngine. It is now folded into this one
          // control, which keeps the original server.diarizationModelSelection key
          // so the Model Manager tab and the Metal boot auto-start in
          // electron/main.ts keep reading the same value. A new key would have
          // desynced those readers, and whichever component mounted first would win.
          //
          // The retired engine key doubles as the migration marker: it is consumed
          // (cleared to an empty string, which getString reports as null) once the
          // fold is applied, so this can never re-fire. If that write ever failed,
          // the migration would merely re-apply the setting the user was already
          // effectively running before the merge, which is benign.
          const legacyEngineRaw = getString(storedSensevoiceEngine);
          let nextDiarizationSelection =
            getString(storedDiarizationSelection) ?? DIARIZATION_SORTFORMER_OPTION;
          if (nextDiarizationSelection === LEGACY_CUSTOM_OPTION) {
            nextDiarizationSelection = getString(storedDiarizationCustom) ?? '';
          }

          if (legacyEngineRaw) {
            // Preserve EFFECTIVE behavior: pre-merge, a SenseVoice main plus
            // engine=CAM++ meant CAM++ actually ran and the diarization-model pick
            // was ignored entirely. Every other combination kept the model pick,
            // because engine=funasr was a no-op for non-SenseVoice mains.
            const migratedMainModel = resolveMainModelSelectionValue(
              nextMainSelection,
              configuredMainModel,
            );
            if (
              legacyEngineRaw === DIARIZATION_CAMPP_OPTION &&
              isSenseVoiceModel(migratedMainModel)
            ) {
              nextDiarizationSelection = DIARIZATION_CAMPP_OPTION;
            }
            void api.config.set('server.sensevoiceDiarizationEngine', '').catch(() => {});
          }

          // Migrate the old 'Auto (best available)' label to the Sortformer option.
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
              // Formerly a custom repo — fall back to the pyannote default.
              nextDiarizationSelection = DIARIZATION_DEFAULT_MODEL;
            } else {
              nextDiarizationSelection = DIARIZATION_SORTFORMER_OPTION;
            }
          }

          // Branch B migration: the dedicated "GGML Sidecar Model" selector is
          // gone — the Main Transcriber now owns the sidecar model in Vulkan
          // mode. If a user is upgrading from that era and their persisted main
          // pick isn't a GGML model, seed it from the old `server.whispercppModel`
          // value (stored as a display name) or the recommended GGML, so the
          // sidecar always has a valid model to load.
          const storedProfile = getString(storedRuntimeProfile);
          const isVulkanProfile = storedProfile === 'vulkan' || storedProfile === 'vulkan-wsl2';
          if (isVulkanProfile && !isWhisperCppModel(resolvedMainModel)) {
            const storedGgml = getString(storedWhispercppModel);
            const migratedId =
              (storedGgml &&
                (GGML_DISPLAY_TO_ID.get(storedGgml) ??
                  (isWhisperCppModel(storedGgml) ? storedGgml : undefined))) ??
              VULKAN_RECOMMENDED_MODEL;
            nextMainSelection = migratedId;
          }

          // Consume the retired custom-repo keys (one-shot; see migration
          // note above). Failures are benign — the same normalization simply
          // re-runs on the next mount.
          if (
            getString(storedMainCustom) ||
            getString(storedLiveCustom) ||
            getString(storedDiarizationCustom)
          ) {
            void api.config.set('server.mainCustomModel', '').catch(() => {});
            void api.config.set('server.liveCustomModel', '').catch(() => {});
            void api.config.set('server.diarizationCustomModel', '').catch(() => {});
          }

          setMainModelSelection(nextMainSelection);
          setLiveModelSelection(nextLiveSelection);
          setDiarizationModelSelection(nextDiarizationSelection);
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

  // Persist runtime profile changes, reset selections the new runtime cannot
  // run, and check sidecar availability for Vulkan. Selecting a runtime never
  // downloads anything: even Metal only persists the profile — the native MLX
  // server (whose startup pre-downloads models) starts from the Inference
  // Server card's Start button.
  const handleRuntimeProfileChange = useCallback(
    async (profile: RuntimeProfile) => {
      setRuntimeProfile(profile);
      const api = (window as any).electronAPI;
      if (api?.config) {
        api.config.set('server.runtimeProfile', profile);
      }
      // Reset a main model the new runtime cannot run to the runtime's
      // recommended default. Subsumes the old special cases (MLX ids off
      // Metal, NeMo on CPU — GH-125) and also covers GGML mains left over
      // from a Vulkan profile, which used to survive the switch.
      const resolvedMain = resolveMainModelSelectionValue(mainModelSelection, '');
      const mainFamily = familyChoiceForModel(resolvedMain);
      let mainAfterReset = resolvedMain;
      if (mainFamily && !isFamilyChoiceEnabledFor(mainFamily, profile)) {
        const nextDefault = defaultMainModelFor(profile);
        mainAfterReset = nextDefault;
        setMainModelSelection(nextDefault);
        api?.config?.set('server.mainModelSelection', nextDefault);
      }
      // Live picks are whisper/whispercpp-only; GGML live models are invalid
      // off Vulkan and MLX ids are never valid. Fall back to Same-as-main —
      // the live-compatibility effect below refines that if the main model
      // cannot serve Live Mode either.
      if (
        liveModelSelection !== LIVE_MODEL_SAME_AS_MAIN_OPTION &&
        liveModelSelection !== MODEL_DISABLED_OPTION
      ) {
        const resolvedLive = resolveLiveModelSelectionValue(liveModelSelection, mainAfterReset);
        const liveFamily = familyChoiceForModel(resolvedLive);
        const liveInvalid =
          liveFamily !== null &&
          liveFamily !== 'whisper' &&
          !(liveFamily === 'whispercpp' && isFamilyChoiceEnabledFor('whispercpp', profile));
        if (liveInvalid) {
          setLiveModelSelection(LIVE_MODEL_SAME_AS_MAIN_OPTION);
          api?.config?.set('server.liveModelSelection', LIVE_MODEL_SAME_AS_MAIN_OPTION);
        }
      }
      // Handle Vulkan sidecar image check (read-only — the actual pull is an
      // explicit button in the sidecar banner).
      if (profile === 'vulkan') {
        docker
          .hasSidecarImage()
          .then((exists) => setSidecarNeeded(!exists))
          .catch(() => {});
      } else {
        setSidecarNeeded(null);
        docker.cancelSidecarPull();
        useNotificationsStore.getState().dismissToast('sidecar-vulkan');
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

      // Leaving Metal — stop the native server if it is running or errored.
      // (Entering Metal deliberately does NOT start it; see the Start button.)
      if (!api?.mlx) return;
      if (profile !== 'metal') {
        const current = await api.mlx.getStatus().catch(() => 'stopped');
        if (current === 'running' || current === 'starting' || current === 'error') {
          await api.mlx.stop().catch(() => {});
        }
      }
    },
    [
      mainModelSelection,
      liveModelSelection,
      isAppleSilicon,
      metalSupported,
      mlxFeature,
      docker.hasSidecarImage,
      docker.cancelSidecarPull,
    ],
  );
  const containerStatus = docker.container;
  const isRunning = containerStatus.running;
  const isRunningAndHealthy = isRunning && containerStatus.health === 'healthy';

  // Single owner of the model-download cache and in-flight-download state,
  // consumed by the Instance Settings selectors.
  const { modelCacheStatus, refreshCacheStatus } = useModelCache({ isRunning, isMetal });

  // Host-side GGML cache status (vulkan-wsl2 only - models live on the
  // Windows filesystem, outside the Docker volume).
  const [hostCacheStatus, setHostCacheStatus] = useState<Record<string, { exists: boolean }>>({});
  const isVulkanWsl2 = runtimeProfile === 'vulkan-wsl2';

  const refreshHostCacheStatus = useCallback(async (ids: readonly string[]) => {
    const api = (window as any).electronAPI;
    if (!api?.docker?.isGgmlModelDownloadedOnHost) return;
    const entries = await Promise.all(
      ids.map(async (id) => {
        const exists = await api.docker.isGgmlModelDownloadedOnHost(id).catch(() => false);
        return [id, { exists }] as const;
      }),
    );
    setHostCacheStatus((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
  }, []);

  useEffect(() => {
    if (!isVulkanWsl2) return;
    void refreshHostCacheStatus(GGML_MODELS.map((m) => m.id));
  }, [isVulkanWsl2, refreshHostCacheStatus]);

  const { downloadingIds, downloadModel, removeModel } = useModelDownloads({
    isMetal,
    runtimeProfile,
    refreshCacheStatus,
    refreshHostCacheStatus,
  });

  // vulkan-wsl2: GGML weights live on the Windows host filesystem, outside the
  // Docker volume, so the container-side cache check can't see them. Overlay
  // the host-side status (GGML ids only) so the model picker's cached/missing
  // dots stay truthful for whisper.cpp models on that profile.
  const effectiveModelCacheStatus = useMemo(
    () => (isVulkanWsl2 ? { ...modelCacheStatus, ...hostCacheStatus } : modelCacheStatus),
    [isVulkanWsl2, modelCacheStatus, hostCacheStatus],
  );

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
      setMainModelSelection(mapMainModelToSelection(configuredMainModel));
      setLiveModelSelection(mapLiveModelToSelection(configuredLiveModel, configuredMainModel));
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
      setDiarizationModelSelection(mapDiarizationModelToSelection(configuredDiarizationModel));
    }

    setDiarizationHydrated(true);
  }, [
    adminStatus,
    configuredDiarizationModel,
    diarizationHydrated,
    diarizationModelSelection,
    localSelectionsHydrated,
  ]);

  const activeTranscriber = resolveMainModelSelectionValue(mainModelSelection, configuredMainModel);
  // SenseVoice-only: the diarization-engine selector is greyed unless the main
  // transcriber is a SenseVoice model.
  const isSenseVoiceMain = isSenseVoiceModel(activeTranscriber);
  const activeLiveModel = resolveLiveModelSelectionValue(liveModelSelection, activeTranscriber);
  const normalizedLiveModel = normalizeLiveModelToWhisper(activeLiveModel);
  // Vulkan sidecar boot/launch model, derived from the Main Transcriber pick
  // (Branch B). The backend swaps to the live model at runtime via /load; this
  // is only the model the sidecar pre-loads at startup. Guarded so a non-GGML
  // value can never reach the sidecar.
  const vulkanSidecarModelPath = `/models/${
    isWhisperCppModel(activeTranscriber) ? activeTranscriber : VULKAN_RECOMMENDED_MODEL
  }`;
  const liveModelWhisperOnlyCompatible =
    activeLiveModel === DISABLED_MODEL_SENTINEL || isLiveCompatibleModel(activeLiveModel);
  const liveModeModelConstraintMessage =
    'Live Mode supports faster-whisper and whisper.cpp (GGML) models.';

  // Active diarization model name — empty string = server auto-select. Both
  // Sortformer and CAM++ send an EMPTY DIARIZATION_MODEL: Sortformer is picked
  // server-side (empty model + mps/cpu), and CAM++ runs SenseVoice's integrated
  // single-pass diarizer while leaving the config.yaml pyannote default in place
  // as the fallback if cam++ fails to load.
  const activeDiarizationModel =
    diarizationModelSelection === DIARIZATION_SORTFORMER_OPTION ||
    diarizationModelSelection === DIARIZATION_CAMPP_OPTION
      ? ''
      : DIARIZATION_DEFAULT_MODEL;

  // SenseVoice diarization engine env value: 'funasr' only when the merged
  // dropdown is set to CAM++, else 'pyannote'. This is a harmless no-op unless
  // the main transcriber is SenseVoice (the server ignores it otherwise).
  const sensevoiceEngineValue =
    diarizationModelSelection === DIARIZATION_CAMPP_OPTION ? 'funasr' : 'pyannote';

  // Model id used for the download badge / cache check. CAM++ sends an empty
  // DIARIZATION_MODEL, so surface CAM++'s own HuggingFace repo instead.
  const diarizationStatusModelId =
    diarizationModelSelection === DIARIZATION_CAMPP_OPTION ? CAMPP_HF_REPO : activeDiarizationModel;

  // MLX native-process start/stop handlers (depend on activeTranscriber declared above)
  const handleMLXStart = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (!api?.mlx) return;
    useNotificationsStore.getState().notify({
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      detail: 'Launching the Metal (MLX) server process',
      status: 'active',
      progress: 0,
    });
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
      useNotificationsStore.getState().updateNotification(SERVER_START_ID, {
        title: 'Server failed to start',
        status: 'error',
        error: msg,
      });
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

  // Hard-reset any non-Live-compatible model selection to the default whisper model.
  // Live Mode accepts faster-whisper and whisper.cpp (GGML) backends.
  useEffect(() => {
    if (
      !localSelectionsHydrated ||
      activeLiveModel === DISABLED_MODEL_SENTINEL ||
      isLiveCompatibleModel(activeLiveModel)
    )
      return;
    setLiveModelSelection(FALLBACK_LIVE_WHISPER_MODEL);
  }, [activeLiveModel, localSelectionsHydrated]);

  // Metal mode: auto-switch a non-MLX main model to the MLX default.
  useEffect(() => {
    if (!localSelectionsHydrated || runtimeProfile !== 'metal') return;
    const resolved = resolveMainModelSelectionValue(mainModelSelection, '');
    if (resolved && !isMLXModel(resolved) && resolved !== MODEL_DEFAULT_LOADING_PLACEHOLDER) {
      setMainModelSelection(MLX_DEFAULT_MODEL);
    }
  }, [runtimeProfile, localSelectionsHydrated, mainModelSelection]);

  useEffect(() => {
    // Sortformer is Metal/MLX-only; on any non-Metal runtime fall back to the
    // pyannote default. Gated on hydration to match the other
    // selection-mutating effects in this file (avoids pre-hydration churn).
    // Persisting the corrected value is intentional — Sortformer is unusable off-Metal.
    if (
      localSelectionsHydrated &&
      !isMetal &&
      diarizationModelSelection === DIARIZATION_SORTFORMER_OPTION
    ) {
      setDiarizationModelSelection(DIARIZATION_DEFAULT_MODEL);
    }
  }, [localSelectionsHydrated, isMetal, diarizationModelSelection]);

  useEffect(() => {
    // CAM++ is SenseVoice-only; if the main transcriber is not a SenseVoice
    // model, fall back to the pyannote default. Mirrors the Sortformer reset
    // above. Gated on hydration to avoid pre-hydration churn.
    //
    // Guard: until adminStatus lands, configuredMainModel is DISABLED_MODEL_SENTINEL,
    // so activeTranscriber resolves to that sentinel rather than the loading
    // placeholder. It is truthy, so a placeholder-only check lets the reset through
    // and CLOBBERS a legitimately stored CAM++ pick. Require adminStatus (matching
    // the sibling seed effects) and reject both transient values explicitly.
    if (!adminStatus) return;
    if (
      localSelectionsHydrated &&
      activeTranscriber &&
      activeTranscriber !== MODEL_DEFAULT_LOADING_PLACEHOLDER &&
      activeTranscriber !== DISABLED_MODEL_SENTINEL &&
      !isSenseVoiceMain &&
      diarizationModelSelection === DIARIZATION_CAMPP_OPTION
    ) {
      setDiarizationModelSelection(DIARIZATION_DEFAULT_MODEL);
    }
  }, [
    adminStatus,
    localSelectionsHydrated,
    activeTranscriber,
    isSenseVoiceMain,
    diarizationModelSelection,
  ]);

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
    void api.config.set('server.liveModelSelection', liveModelSelection).catch(() => {});
  }, [localSelectionsHydrated, liveModelSelection]);

  useEffect(() => {
    if (!localSelectionsHydrated) return;
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    // Persist the merged control under the NEW key so the one-shot migration in
    // the hydration effect can never re-fire and clobber a later user choice.
    void api.config
      .set('server.diarizationModelSelection', diarizationModelSelection)
      .catch(() => {});
  }, [localSelectionsHydrated, diarizationModelSelection]);

  // Check model download cache whenever the active model names or container state
  // change. GH-213: covers every option the selectors can show (not just the 3
  // active ids), and keeps working while the container is STOPPED, exactly when
  // the selectors are editable, via the offline volume check. Metal has no
  // container at all, so it routes through the MLX host-filesystem checker.
  useEffect(() => {
    // Every model id the Main picker rows and the Live dropdown can currently
    // offer, mirroring the option builders in InstanceSettingsSelectors, so
    // each entry can show its own downloaded state (GH-213).
    const familyForMain = familyChoiceForModel(activeTranscriber);
    const optionIds = [
      ...(familyForMain ? modelsForFamilyChoice(familyForMain).map((m) => m.id) : []),
      ...liveModelsFor(isWhisperCppModel(activeLiveModel) ? 'vulkan' : 'gpu').map((m) => m.id),
    ];
    const modelIds = [
      ...new Set([activeTranscriber, normalizedLiveModel, diarizationStatusModelId, ...optionIds]),
    ].filter(
      (id) => id && id !== MODEL_DEFAULT_LOADING_PLACEHOLDER && id !== DISABLED_MODEL_SENTINEL,
    );
    if (modelIds.length === 0) return;

    // Debounce the check
    if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    modelCacheCheckRef.current = setTimeout(() => {
      refreshCacheStatus(modelIds);
    }, 500);

    return () => {
      if (modelCacheCheckRef.current) clearTimeout(modelCacheCheckRef.current);
    };
  }, [
    activeTranscriber,
    activeLiveModel,
    normalizedLiveModel,
    diarizationStatusModelId,
    refreshCacheStatus,
  ]);

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
    wslSupport?: { available: boolean; gpuPassthroughDetected: boolean; reason?: string };
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
  const { gpuError, gpuErrorRecoveryHint, details, reachable } = useServerStatus();
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

  // CPU-fallback mismatch: GPU (CUDA) is the selected runtime, the server is up
  // and reachable, but the running container reports CUDA is NOT available
  // inside it (started without GPU passthrough → silently transcribing on CPU).
  // `=== false` (not falsy) so older servers / pre-init responses that omit the
  // field do not trip a false warning. Surfaced by the GpuHealthCard.
  const cpuFallbackActive =
    runtimeProfile === 'gpu' && reachable && details?.gpu_available === false;

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
        .then(
          (info: {
            gpu: boolean;
            toolkit: boolean;
            vulkan: boolean;
            wslSupport?: { available: boolean; gpuPassthroughDetected: boolean; reason?: string };
          }) => {
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
                      }
                    })
                    .catch(() => {});
                }
                // Mark auto-detection as done so it never re-runs
                api.config?.set('server.gpuAutoDetectDone', true);
              })
              .catch(() => {});
          },
        )
        .catch(() => {
          cachedGpuInfo = null;
          setGpuInfo(null);
        });
    }
  }, []);

  // ─── Manual GPU re-detection ───────────────────────────────────────────────
  // GH-101 follow-up: lets the user recover after toggling Docker Desktop's
  // WSL2 ↔ Hyper-V backend (or installing nvidia-container-toolkit) without
  // restarting Electron. Calls the IPC to clear the main-process caches
  // (wslDetect single-flight + detectedGpuMode), then re-runs checkGpu() and
  // updates state. Does NOT re-run the first-run auto-profile pick — that's
  // a one-shot decision the user has already made by the time this is shown.
  const [gpuRedetecting, setGpuRedetecting] = useState(false);
  const handleRedetectGpu = useCallback((): void => {
    if (gpuRedetecting) return;
    const api = (window as any).electronAPI;
    if (!api?.docker?.checkGpu) return;
    setGpuRedetecting(true);
    const resetPromise: Promise<void> = api.docker.resetGpuCache
      ? api.docker.resetGpuCache().catch(() => {})
      : Promise.resolve();
    resetPromise
      .then(() => {
        cachedGpuInfo = undefined;
        return api.docker.checkGpu();
      })
      .then(
        (info: {
          gpu: boolean;
          toolkit: boolean;
          vulkan: boolean;
          wslSupport?: { available: boolean; gpuPassthroughDetected: boolean; reason?: string };
        }) => {
          cachedGpuInfo = info;
          setGpuInfo(info);
        },
      )
      .catch(() => {
        cachedGpuInfo = null;
        setGpuInfo(null);
      })
      .finally(() => {
        setGpuRedetecting(false);
      });
  }, [gpuRedetecting]);

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
  // failure. The notification entry tracks the same dlId for both paths.
  // (Avoid issue-number references with a leading hash in scanned files —
  //  the UI-contract color regex matches 3-digit hex shorthand and would
  //  pollute the literal palette.)
  const handleFetchFreshImage = useCallback(async (): Promise<void> => {
    if (!selectedTagForActions) return;
    const dlId = `docker-image-${selectedTagForActions}`;
    useNotificationsStore.getState().notify({
      id: dlId,
      category: 'download',
      title: `Server Image (${selectedTagForActions})`,
      detail: 'Pulling container image',
      status: 'active',
    });
    // withOperation never throws - it resolves with the error message (or
    // null on success), so branch on the return value instead of try/catch.
    const pullError = await docker.pullImage(selectedTagForActions);
    const store = useNotificationsStore.getState();
    const newest = [...store.notifications].reverse().find((n) => n.id === dlId);
    // A user cancel already closed the record - leave it alone.
    if (newest?.status !== 'active') return;
    if (pullError === null) {
      store.notify({
        id: dlId,
        category: 'download',
        title: `Server Image (${selectedTagForActions}) downloaded`,
        status: 'complete',
      });
    } else {
      store.updateNotification(dlId, { status: 'error', error: pullError });
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
              cpuFallbackActive={cpuFallbackActive}
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
                      className="h-9 px-4 whitespace-nowrap"
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
                      className="h-9 px-4 whitespace-nowrap"
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
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <StatusLight status={hasImages ? 'active' : 'inactive'} />
                      <span
                        className={`font-mono text-sm whitespace-nowrap transition-colors ${hasImages ? 'text-slate-300' : 'text-slate-500'}`}
                      >
                        {hasImages
                          ? `${docker.images.length} image${docker.images.length > 1 ? 's' : ''} available`
                          : 'No images'}
                      </span>

                      {hasImages && docker.images[0] && (
                        <div className="flex shrink-0 gap-2 transition-opacity duration-300">
                          <span className="rounded bg-white/10 px-2 py-0.5 text-xs whitespace-nowrap text-slate-400">
                            {formatDateDMY(docker.images[0].created) ??
                              docker.images[0].created.split(' ')[0]}
                          </span>
                          <span className="rounded bg-white/10 px-2 py-0.5 text-xs whitespace-nowrap text-slate-400">
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
                  <div className="flex flex-col justify-end">
                    {/*
                      Give "Fetch Fresh Image" and "Remove Image" a shared width
                      (the wider of the two labels) and right-align the pair so
                      they no longer smoosh against the version-tag chips at
                      narrower window widths. w-max sizes the group to its widest
                      child; w-full makes both buttons fill that shared width.
                    */}
                    <div className="ml-auto flex w-max flex-col gap-2">
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
                            useNotificationsStore.getState().updateNotification(dlId, {
                              status: 'complete',
                              detail: 'Cancelled by user',
                            });
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
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        className="h-9 px-4 whitespace-nowrap"
                        onClick={() =>
                          onStartServer('local', runtimeProfile, selectedTagForStart, {
                            mainTranscriberModel: sanitizeModelName(activeTranscriber),
                            liveTranscriberModel: sanitizeModelName(normalizedLiveModel),
                            diarizationModel: sanitizeModelName(activeDiarizationModel),
                            sensevoiceDiarizationEngine: sensevoiceEngineValue,
                            ...(isVulkan ? { whispercppModel: vulkanSidecarModelPath } : {}),
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
                        className="h-9 px-4 whitespace-nowrap"
                        onClick={() =>
                          onStartServer('remote', runtimeProfile, selectedTagForStart, {
                            mainTranscriberModel: sanitizeModelName(activeTranscriber),
                            liveTranscriberModel: sanitizeModelName(normalizedLiveModel),
                            diarizationModel: sanitizeModelName(activeDiarizationModel),
                            sensevoiceDiarizationEngine: sensevoiceEngineValue,
                            ...(isVulkan ? { whispercppModel: vulkanSidecarModelPath } : {}),
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
                        className="h-9 px-4 whitespace-nowrap"
                        onClick={() => docker.stopContainer()}
                        disabled={docker.operating || !isRunning}
                      >
                        Stop
                      </Button>
                    </div>
                    <Button
                      variant="danger"
                      className="h-9 px-4 whitespace-nowrap"
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
                {/* Active model downloads while the server is starting (GH-207) */}
                {isRunning && !isRunningAndHealthy && <StartupActivityInline />}
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
              <SlidersHorizontal size={16} />
            </div>
            <GlassCard
              title="2. Instance Settings"
              className={`transition-all duration-500 ease-in-out ${isRunningAndHealthy || mlxStatus === 'running' ? ACTIVE_CARD_ACCENT_CLASS : ''}`}
            >
              <div className="space-y-6">
                {/* Runtime selector — tiles gated per host platform. hostPlatform
                    stays 'unknown' in jsdom/test mounts, which keeps every tile
                    enabled there (gating only engages on a known platform). */}
                <div className="border-b border-white/5 pb-4">
                  <SelectorGroup
                    icon={<Zap size={16} className="text-accent-cyan" />}
                    title="Runtime"
                    hint="Which hardware runs the inference server"
                    action={
                      /* GH-101 follow-up: re-run GPU detection without restarting
                         Electron. Hidden until initial detection completes
                         (gpuInfo !== null) so it never appears in the loading flicker. */
                      gpuInfo !== null ? (
                        <button
                          type="button"
                          onClick={handleRedetectGpu}
                          disabled={gpuRedetecting || isRunning}
                          title="Re-run GPU detection (use after toggling Docker Desktop's WSL2/Hyper-V backend)"
                          className={`text-xs whitespace-nowrap underline ${
                            gpuRedetecting || isRunning
                              ? 'cursor-not-allowed text-slate-600'
                              : 'cursor-pointer text-slate-500 hover:text-slate-200'
                          }`}
                        >
                          {gpuRedetecting ? 'Detecting...' : 'Re-detect'}
                        </button>
                      ) : undefined
                    }
                  >
                    <SelectorTile
                      icon={<NvidiaIcon size={16} />}
                      label="GPU (CUDA)"
                      sublabel="NVIDIA"
                      accent="green"
                      selected={runtimeProfile === 'gpu'}
                      disabled={isRunning || hostPlatform === 'darwin'}
                      badge={hostPlatform === 'darwin' ? 'Requires NVIDIA' : undefined}
                      onSelect={() => handleRuntimeProfileChange('gpu')}
                    />
                    <SelectorTile
                      icon={
                        <span className="flex h-5 w-10 flex-col items-center justify-center -space-y-1">
                          <AmdIcon size={30} />
                          <IntelIcon size={30} />
                        </span>
                      }
                      label="GPU (Vulkan Linux)"
                      sublabel="AMD / Intel"
                      accent="red"
                      selected={runtimeProfile === 'vulkan'}
                      disabled={isRunning || hostPlatform === 'win32' || hostPlatform === 'darwin'}
                      badge={
                        hostPlatform === 'win32' || hostPlatform === 'darwin'
                          ? 'Linux only'
                          : undefined
                      }
                      hint="Experimental"
                      onSelect={() => handleRuntimeProfileChange('vulkan')}
                    />
                    {/* Experimental Vulkan-WSL2 tile (GH-101 follow-up) — only
                        rendered when the main-process probe confirms Docker
                        Desktop runs on the WSL2 backend AND a tiny container
                        could see /dev/dxg. */}
                    {gpuInfo?.wslSupport?.gpuPassthroughDetected && hostPlatform === 'win32' && (
                      <SelectorTile
                        icon={
                          <span className="flex h-5 w-10 flex-col items-center justify-center -space-y-1">
                            <AmdIcon size={30} />
                            <IntelIcon size={30} />
                          </span>
                        }
                        label="GPU (Vulkan Windows)"
                        sublabel="AMD / Intel · WSL2"
                        accent="red"
                        selected={runtimeProfile === 'vulkan-wsl2'}
                        disabled={isRunning}
                        hint="Experimental"
                        onSelect={() => handleRuntimeProfileChange('vulkan-wsl2')}
                      />
                    )}
                    <SelectorTile
                      icon={<AppleIcon size={16} />}
                      label="GPU (Metal)"
                      sublabel="Apple Silicon"
                      accent="purple"
                      selected={runtimeProfile === 'metal'}
                      disabled={
                        isRunning || (hostPlatform !== 'unknown' && hostPlatform !== 'darwin')
                      }
                      badge={
                        hostPlatform !== 'unknown' && hostPlatform !== 'darwin'
                          ? 'Requires Apple Silicon'
                          : undefined
                      }
                      onSelect={() => handleRuntimeProfileChange('metal')}
                    />
                    <SelectorTile
                      icon={<Cpu size={16} />}
                      label="CPU Only"
                      sublabel="Universal"
                      accent="orange"
                      selected={runtimeProfile === 'cpu'}
                      disabled={isRunning}
                      onSelect={() => handleRuntimeProfileChange('cpu')}
                    />
                  </SelectorGroup>
                  {runtimeProfile === 'vulkan' && !isRunning && (
                    <p className="mt-2 text-xs text-slate-500 italic">
                      AMD/Intel GPU via whisper.cpp — no diarization; live mode via GGML models
                    </p>
                  )}
                  {runtimeProfile === 'vulkan-wsl2' && !isRunning && (
                    <p className="text-accent-orange mt-2 text-xs italic">
                      Experimental: AMD/Intel GPU via WSL2 + Mesa dzn — see README §2.5.2
                    </p>
                  )}
                  {runtimeProfile === 'cpu' && !isRunning && (
                    <p className="mt-2 text-xs text-slate-500 italic">
                      Slower transcription, no NVIDIA GPU required
                    </p>
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
                  <div className="border-b border-white/5 pb-4">
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
                      label="Legacy GPU image"
                      description={
                        containerStatus.exists && !isRunning
                          ? 'Remove the existing container to switch image variants'
                          : 'Installs cu126 wheels for GTX 10-series / 900-series and older NVIDIA cards (Pascal / Maxwell, Tesla and Quadro P/M)'
                      }
                    />
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
                            useNotificationsStore.getState().updateNotification('sidecar-vulkan', {
                              status: 'complete',
                              detail: 'Cancelled by user',
                            });
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
                            useNotificationsStore.getState().notify({
                              id: dlId,
                              category: 'download',
                              title: 'Vulkan Sidecar (whisper.cpp)',
                              detail: 'Pulling sidecar image',
                              status: 'active',
                            });
                            // withOperation resolves with the error message (or
                            // null on success) rather than throwing.
                            const pullError = await docker.pullSidecarImage();
                            const store = useNotificationsStore.getState();
                            const newest = [...store.notifications]
                              .reverse()
                              .find((n) => n.id === dlId);
                            // A user cancel already closed the record - leave it.
                            if (newest?.status === 'active') {
                              if (pullError === null) {
                                store.notify({
                                  id: dlId,
                                  category: 'download',
                                  title: 'Vulkan Sidecar (whisper.cpp) downloaded',
                                  status: 'complete',
                                });
                              } else {
                                store.updateNotification(dlId, {
                                  status: 'error',
                                  error: pullError,
                                });
                              }
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

                {/* Model / live / diarization selectors — all valid combinations
                    come from src/services/instanceMatrix.ts */}
                <InstanceSettingsSelectors
                  runtimeProfile={runtimeProfile}
                  isRunning={isRunning}
                  mainModelSelection={mainModelSelection}
                  onMainModelSelectionChange={setMainModelSelection}
                  liveModelSelection={liveModelSelection}
                  onLiveModelSelectionChange={setLiveModelSelection}
                  diarizationModelSelection={diarizationModelSelection}
                  onDiarizationModelSelectionChange={setDiarizationModelSelection}
                  activeTranscriber={activeTranscriber}
                  activeLiveModel={activeLiveModel}
                  diarizationStatusModelId={diarizationStatusModelId}
                  modelCacheStatus={effectiveModelCacheStatus}
                  liveModelWhisperOnlyCompatible={liveModelWhisperOnlyCompatible}
                  liveModeModelConstraintMessage={liveModeModelConstraintMessage}
                  modelsLoaded={adminStatus?.models_loaded}
                  modelsLoading={modelsLoading}
                  onLoadModels={handleLoadModels}
                  onUnloadModels={handleUnloadModels}
                  canManage={isMetal || isRunning}
                  downloadingIds={downloadingIds}
                  onDownloadModel={downloadModel}
                  onRemoveModel={removeModel}
                />
              </div>
            </GlassCard>
          </div>

          {/* 3. Remote Connection Card */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-8 pl-8 last:border-0 last:pb-0">
            <div
              className={`absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 transition-colors duration-300 ${isRunningAndHealthy && serverMode === 'remote' ? 'bg-accent-magenta text-slate-900 shadow-[0_0_15px_rgba(232,121,249,0.5)]' : 'bg-slate-800 text-slate-300'}`}
            >
              <Globe size={14} />
            </div>
            <RemoteConnectionCard
              title="3. Remote Connection"
              isRunningAndHealthy={isRunningAndHealthy}
            />
          </div>

          {/* 4. Volumes Card */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-2 pl-8 last:border-0 last:pb-0">
            <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
              <HardDrive size={14} />
            </div>
            <GlassCard
              title="4. Persistent Volumes"
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
                      <div key={label} className="py-1 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-3">
                            <div className={`h-2 w-2 rounded-full ${color}`} />
                            <span className="text-slate-300">{label}</span>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <button
                              onClick={() => handleOpenNativePath(dir)}
                              disabled={!dir}
                              className="rounded p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                              title="Open in file manager"
                            >
                              <FolderOpen size={14} />
                            </button>
                            <button
                              onClick={() => handleCopyNativePath(dir, label)}
                              disabled={!dir}
                              className="rounded p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                              title="Copy path"
                            >
                              {copiedPath === label ? (
                                <Check size={14} className="text-green-400" />
                              ) : (
                                <Copy size={14} />
                              )}
                            </button>
                          </div>
                        </div>
                        <div className="mt-1 pl-5 font-mono text-xs break-all text-slate-400">
                          {dir ?? '…'}
                        </div>
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

          {/* 5. Clean Up */}
          <div className="relative shrink-0 border-l-2 border-white/10 pb-2 pl-8 last:border-0 last:pb-0">
            <div className="absolute top-0 -left-4.25 z-10 flex h-8 w-8 items-center justify-center rounded-full border-4 border-slate-900 bg-slate-800 text-slate-300">
              <AlertTriangle size={14} />
            </div>
            <GlassCard title="5. Clean Up">
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
          <DialogPanel className="blur-panel w-full max-w-lg overflow-hidden rounded-3xl border border-red-500/25 bg-black/75 shadow-2xl backdrop-blur-xl">
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
          <DialogPanel className="border-accent-orange/25 blur-panel w-full max-w-lg overflow-hidden rounded-3xl border bg-black/75 shadow-2xl backdrop-blur-xl">
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
