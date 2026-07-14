/**
 * Single source of truth for the Instance Settings compatibility matrix:
 * which model families, live-mode options and diarization engines are valid
 * for each runtime profile. The Server tab selectors render from this module
 * and instanceMatrix.test.ts verifies the full cross-product against the
 * design spec (docs/superpowers/specs/2026-07-11-server-tab-matrix-redesign-design.md).
 *
 * Backend gates mirrored here:
 * - live.py: only whisper / whispercpp backends may serve Live Mode
 * - dockerManager applyCpuModelDefaults: NeMo mains are substituted on cpu
 * - config.py resolve_sensevoice_diarization_engine: CAM++ is SenseVoice-only
 * - diarization_engine.py create_diarization_engine: Sortformer needs mlx-audio (Metal)
 * - base.py use_integrated_diarization_for: VibeVoice always diarizes natively
 */
import type { RuntimeProfile } from '../types/runtime';
import {
  isMLXCanaryModel,
  isMLXModel,
  isMLXParakeetModel,
  isNemoModel,
  isSenseVoiceModel,
  isVibeVoiceASRModel,
  isWhisperCppModel,
} from './modelCapabilities';
import { MODEL_REGISTRY, type ModelInfo } from './modelRegistry';
import {
  DISABLED_MODEL_SENTINEL,
  MAIN_RECOMMENDED_MODEL,
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MODEL_DISABLED_OPTION,
  VULKAN_RECOMMENDED_MODEL,
  WHISPER_MEDIUM,
} from './modelSelection';

// Persisted option strings — stored verbatim in electron-store
// (server.diarizationModelSelection); values must never change.
export const DIARIZATION_SORTFORMER_OPTION = 'Sortformer (Metal; ≤ 4 speakers)';
export const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';
export const DIARIZATION_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
export const DIARIZATION_CAMPP_OPTION = 'CAM++ (fast, built-in)';
export const DIARIZATION_BUILTIN_LABEL = 'Built-in';

export const MLX_DEFAULT_MODEL = 'mlx-community/parakeet-tdt-0.6b-v3';

export const FAMILY_CHOICE_IDS = [
  'whisper',
  'nemo',
  'sensevoice',
  'vibevoice',
  'whispercpp',
  'mlx-whisper',
  'mlx-nemo',
  'mlx-vibevoice',
] as const;
export type FamilyChoiceId = (typeof FAMILY_CHOICE_IDS)[number];

export type FamilyAccent = 'slate' | 'green' | 'yellow' | 'amber' | 'blue' | 'purple' | 'orange';

export interface FamilyCapabilities {
  /** Rough language count shown on the tile. */
  languages: string;
  translation: 'none' | 'english' | 'multilingual';
  live: boolean;
  diarization: 'pyannote' | 'campp' | 'sortformer' | 'builtin' | 'none';
  /** Whether the default diarization engine needs a HuggingFace token. */
  requiresToken: boolean;
}

export interface FamilyChoice {
  id: FamilyChoiceId;
  label: string;
  sublabel: string;
  accent: FamilyAccent;
  enabled: boolean;
  reason?: string;
  hint?: string;
  capabilities: FamilyCapabilities;
}

interface FamilyMeta {
  label: string;
  sublabel: string;
  accent: FamilyAccent;
  capabilities: FamilyCapabilities;
}

const FAMILY_META: Record<FamilyChoiceId, FamilyMeta> = {
  whisper: {
    label: 'Whisper',
    sublabel: 'faster-whisper / WhisperX',
    accent: 'slate',
    capabilities: {
      languages: '90+',
      translation: 'english',
      live: true,
      diarization: 'pyannote',
      requiresToken: true,
    },
  },
  // One tile covers both Parakeet (ASR-only) and Canary (translating). The tile
  // advertises the family maximum, so it shows the translation badge; the model
  // rows below disambiguate which of the two the user actually has selected.
  nemo: {
    label: 'NeMo Models',
    sublabel: 'NVIDIA Parakeet / Canary',
    accent: 'green',
    capabilities: {
      languages: '25',
      translation: 'multilingual',
      live: false,
      diarization: 'pyannote',
      requiresToken: true,
    },
  },
  sensevoice: {
    label: 'SenseVoice',
    sublabel: 'FunASR',
    accent: 'amber',
    capabilities: {
      languages: '5',
      translation: 'none',
      live: false,
      diarization: 'campp',
      requiresToken: false,
    },
  },
  vibevoice: {
    label: 'VibeVoice',
    sublabel: 'Microsoft ASR',
    accent: 'blue',
    capabilities: {
      languages: '51',
      translation: 'none',
      live: false,
      diarization: 'builtin',
      requiresToken: false,
    },
  },
  whispercpp: {
    label: 'Whisper.cpp',
    sublabel: 'GGML via Vulkan',
    accent: 'purple',
    capabilities: {
      languages: '90+',
      translation: 'english',
      live: true,
      diarization: 'none',
      requiresToken: false,
    },
  },
  'mlx-whisper': {
    label: 'MLX Whisper',
    sublabel: 'Apple Silicon',
    accent: 'orange',
    capabilities: {
      languages: '90+',
      translation: 'english',
      live: false,
      diarization: 'sortformer',
      requiresToken: false,
    },
  },
  'mlx-nemo': {
    label: 'MLX NeMo',
    sublabel: 'Apple Silicon',
    accent: 'green',
    capabilities: {
      languages: '25',
      translation: 'multilingual',
      live: false,
      diarization: 'sortformer',
      requiresToken: false,
    },
  },
  'mlx-vibevoice': {
    label: 'MLX VibeVoice',
    sublabel: 'Apple Silicon',
    accent: 'blue',
    capabilities: {
      languages: '51',
      translation: 'none',
      live: false,
      diarization: 'builtin',
      requiresToken: false,
    },
  },
};

const REASON_REQUIRES_CUDA = 'Requires CUDA';
const REASON_REQUIRES_VULKAN = 'Requires Vulkan';
const REASON_REQUIRES_APPLE_SILICON = 'Requires Apple Silicon';
const REASON_REQUIRES_DOCKER = 'Requires Docker';
const REASON_REQUIRES_NVIDIA = 'Requires NVIDIA GPU';
const HINT_SLOW_ON_CPU = 'Slow on CPU';
const HINT_RUNS_ON_CPU = 'Runs on CPU';

const MLX_FAMILIES: readonly FamilyChoiceId[] = ['mlx-whisper', 'mlx-nemo', 'mlx-vibevoice'];

function isVulkanProfile(runtime: RuntimeProfile): boolean {
  return runtime === 'vulkan' || runtime === 'vulkan-wsl2';
}

/**
 * Availability + disabled-reason for one family on one runtime.
 * This is the single place the family × runtime truth table lives.
 */
function familyAvailability(
  id: FamilyChoiceId,
  runtime: RuntimeProfile,
): { enabled: boolean; reason?: string; hint?: string } {
  if (MLX_FAMILIES.includes(id)) {
    return runtime === 'metal'
      ? { enabled: true }
      : { enabled: false, reason: REASON_REQUIRES_APPLE_SILICON };
  }
  if (id === 'whispercpp') {
    return isVulkanProfile(runtime)
      ? { enabled: true }
      : { enabled: false, reason: REASON_REQUIRES_VULKAN };
  }
  // CUDA-stack families (run in the Docker torch image).
  if (runtime === 'metal') return { enabled: false, reason: REASON_REQUIRES_DOCKER };
  if (isVulkanProfile(runtime)) return { enabled: false, reason: REASON_REQUIRES_CUDA };
  if (runtime === 'cpu') {
    if (id === 'nemo') {
      // dockerManager substitutes NeMo mains with faster-whisper on cpu;
      // surface that as an explicit disable instead of a silent swap.
      return { enabled: false, reason: REASON_REQUIRES_NVIDIA };
    }
    if (id === 'sensevoice' || id === 'vibevoice') {
      return { enabled: true, hint: HINT_SLOW_ON_CPU };
    }
  }
  return { enabled: true };
}

export function familyChoicesFor(runtime: RuntimeProfile): FamilyChoice[] {
  return FAMILY_CHOICE_IDS.map((id) => {
    const meta = FAMILY_META[id];
    const availability = familyAvailability(id, runtime);
    return { id, ...meta, ...availability };
  });
}

export function isFamilyChoiceEnabledFor(id: FamilyChoiceId, runtime: RuntimeProfile): boolean {
  return familyAvailability(id, runtime).enabled;
}

/**
 * Classify a concrete model id (including custom HF repos) into a family
 * choice. MLX checks run first: mlx-community/VibeVoice-ASR-* also matches
 * the generic VibeVoice pattern (same ordering as backend factory.py).
 */
export function familyChoiceForModel(modelId: string | null | undefined): FamilyChoiceId | null {
  const name = (modelId ?? '').trim();
  if (
    !name ||
    name === DISABLED_MODEL_SENTINEL ||
    name === MODEL_DISABLED_OPTION ||
    name === MODEL_DEFAULT_LOADING_PLACEHOLDER
  ) {
    return null;
  }
  if (isMLXParakeetModel(name) || isMLXCanaryModel(name)) return 'mlx-nemo';
  if (isMLXModel(name)) {
    return /vibevoice/i.test(name) ? 'mlx-vibevoice' : 'mlx-whisper';
  }
  if (isNemoModel(name)) return 'nemo';
  if (isSenseVoiceModel(name)) return 'sensevoice';
  if (isVibeVoiceASRModel(name)) return 'vibevoice';
  if (isWhisperCppModel(name)) return 'whispercpp';
  return 'whisper';
}

export function modelsForFamilyChoice(choice: FamilyChoiceId): ModelInfo[] {
  return MODEL_REGISTRY.filter(
    (m) => m.roles.includes('main') && familyChoiceForModel(m.id) === choice,
  );
}

/**
 * The model a family tile selects when clicked: the curated recommendation
 * where one exists, else the family's first registry entry.
 */
export function defaultModelForFamilyChoice(choice: FamilyChoiceId): string {
  if (choice === 'whispercpp') return VULKAN_RECOMMENDED_MODEL;
  // Parakeet is the ASR-only workhorse and the right default; Canary is the
  // opt-in translation model, reachable from the model rows.
  if (choice === 'nemo') return MAIN_RECOMMENDED_MODEL;
  if (choice === 'mlx-nemo') return MLX_DEFAULT_MODEL;
  return modelsForFamilyChoice(choice)[0]?.id ?? '';
}

export function defaultMainModelFor(runtime: RuntimeProfile): string {
  switch (runtime) {
    case 'metal':
      return MLX_DEFAULT_MODEL;
    case 'vulkan':
    case 'vulkan-wsl2':
      return VULKAN_RECOMMENDED_MODEL;
    case 'cpu':
      // Matches dockerManager applyCpuModelDefaults' substitution target.
      return WHISPER_MEDIUM;
    default:
      return MAIN_RECOMMENDED_MODEL;
  }
}

export type LiveTileId = 'same-as-main' | 'whisper' | 'whispercpp' | 'disabled';

export interface LiveTile {
  id: LiveTileId;
  label: string;
  enabled: boolean;
  reason?: string;
  hint?: string;
}

/**
 * Live Mode options for a runtime + main model. Only whisper-family and
 * whisper.cpp backends may serve Live Mode (live.py gate); faster-whisper
 * decodes on CPU where CUDA is absent — the Metal venv ships it for exactly
 * this purpose.
 */
export function liveTilesFor(
  runtime: RuntimeProfile,
  mainModelId: string | null | undefined,
): LiveTile[] {
  const mainChoice = familyChoiceForModel(mainModelId);
  const mainIsLiveCapable = mainChoice === 'whisper' || mainChoice === 'whispercpp';
  const cpuDecode = runtime === 'metal' || isVulkanProfile(runtime);
  return [
    {
      id: 'same-as-main',
      label: 'Same as main',
      enabled: mainIsLiveCapable,
      reason: mainIsLiveCapable ? undefined : 'Main model has no Live Mode',
    },
    {
      id: 'whisper',
      label: 'Faster-Whisper',
      enabled: true,
      hint: cpuDecode ? HINT_RUNS_ON_CPU : undefined,
    },
    {
      id: 'whispercpp',
      label: 'Whisper.cpp',
      enabled: isVulkanProfile(runtime),
      reason: isVulkanProfile(runtime) ? undefined : REASON_REQUIRES_VULKAN,
    },
    {
      id: 'disabled',
      label: 'Disabled',
      enabled: true,
    },
  ];
}

export function liveModelsFor(runtime: RuntimeProfile): ModelInfo[] {
  const family: FamilyChoiceId = isVulkanProfile(runtime) ? 'whispercpp' : 'whisper';
  return MODEL_REGISTRY.filter(
    (m) => m.roles.includes('live') && familyChoiceForModel(m.id) === family,
  );
}

export type DiarizationTileId = 'pyannote' | 'campp' | 'sortformer' | 'builtin' | 'custom';

export interface DiarizationTile {
  id: DiarizationTileId;
  label: string;
  /** Value persisted to server.diarizationModelSelection. */
  storedValue: string;
  enabled: boolean;
  isDefault: boolean;
  reason?: string;
  hint?: string;
}

/**
 * Diarization engine options for a runtime + main model.
 * whisper.cpp mains → empty list (no diarization path exists);
 * VibeVoice mains → single locked "Built-in" tile (the backend always uses
 * its native diarization regardless of configuration).
 */
export function diarizationTilesFor(
  runtime: RuntimeProfile,
  mainModelId: string | null | undefined,
): DiarizationTile[] {
  const mainChoice = familyChoiceForModel(mainModelId);
  if (mainChoice === 'whispercpp') return [];
  if (mainChoice === 'vibevoice' || mainChoice === 'mlx-vibevoice') {
    return [
      {
        id: 'builtin',
        label: DIARIZATION_BUILTIN_LABEL,
        storedValue: '',
        enabled: true,
        isDefault: true,
        hint: 'VibeVoice identifies speakers natively',
      },
    ];
  }

  const isSenseVoiceMain = mainChoice === 'sensevoice';
  const isMetal = runtime === 'metal';
  const defaultId: DiarizationTileId = isSenseVoiceMain
    ? 'campp'
    : isMetal
      ? 'sortformer'
      : 'pyannote';

  return [
    {
      id: 'campp',
      label: 'CAM++',
      storedValue: DIARIZATION_CAMPP_OPTION,
      enabled: isSenseVoiceMain,
      isDefault: defaultId === 'campp',
      reason: isSenseVoiceMain ? undefined : 'SenseVoice only',
      hint: isSenseVoiceMain ? 'No token needed' : undefined,
    },
    {
      id: 'sortformer',
      label: 'Sortformer',
      storedValue: DIARIZATION_SORTFORMER_OPTION,
      enabled: isMetal,
      isDefault: defaultId === 'sortformer',
      reason: isMetal ? undefined : 'Requires Metal',
      hint: isMetal ? 'No token · up to 4 speakers' : undefined,
    },
    {
      id: 'pyannote',
      label: 'PyAnnote',
      storedValue: DIARIZATION_DEFAULT_MODEL,
      enabled: true,
      isDefault: defaultId === 'pyannote',
      hint: 'HuggingFace token required',
    },
    {
      id: 'custom',
      label: 'Custom',
      storedValue: DIARIZATION_MODEL_CUSTOM_OPTION,
      enabled: true,
      isDefault: false,
      hint: 'HuggingFace repo',
    },
  ];
}
