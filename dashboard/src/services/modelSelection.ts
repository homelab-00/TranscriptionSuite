import { isNemoModel, isVibeVoiceASRModel } from './modelCapabilities';
import type { ModelFamily, ModelRole } from './modelRegistry';

export type { ModelFamily, ModelRole };

export const MAIN_RECOMMENDED_MODEL = 'nvidia/parakeet-tdt-0.6b-v3';
export const LIVE_RECOMMENDED_MODEL = 'Systran/faster-whisper-medium';
export const DISABLED_MODEL_SENTINEL = '__none__';

export const MODEL_DEFAULT_LOADING_PLACEHOLDER = 'Loading server default...';
export const MAIN_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
export const LIVE_MODEL_SAME_AS_MAIN_OPTION = 'Same as Main Transcriber';
export const LIVE_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
export const MODEL_DISABLED_OPTION = 'None (Disabled)';

export const WHISPER_LARGE_V3 = 'Systran/faster-whisper-large-v3';
export const WHISPER_DISTIL_LARGE_V3 = 'Systran/faster-distil-whisper-large-v3';
export const WHISPER_LARGE_V3_TURBO = 'deepdml/faster-whisper-large-v3-turbo-ct2';
export const WHISPER_MEDIUM = 'Systran/faster-whisper-medium';
export const WHISPER_MEDIUM_EN = 'Systran/faster-whisper-medium.en';
export const WHISPER_DISTIL_MEDIUM_EN = 'Systran/faster-distil-whisper-medium.en';
export const WHISPER_SMALL = 'Systran/faster-whisper-small';
export const WHISPER_SMALL_EN = 'Systran/faster-whisper-small.en';
export const WHISPER_DISTIL_SMALL_EN = 'Systran/faster-distil-whisper-small.en';

export const CANARY_1B_V2 = 'nvidia/canary-1b-v2';
export const VIBEVOICE_ASR = 'microsoft/VibeVoice-ASR';
export const VIBEVOICE_ASR_4BIT = 'scerz/VibeVoice-ASR-4bit';

export const MAIN_MODEL_PRESETS = [
  MAIN_RECOMMENDED_MODEL,
  CANARY_1B_V2,
  WHISPER_LARGE_V3,
  WHISPER_DISTIL_LARGE_V3,
  WHISPER_LARGE_V3_TURBO,
  WHISPER_MEDIUM,
  WHISPER_MEDIUM_EN,
  WHISPER_DISTIL_MEDIUM_EN,
  WHISPER_SMALL,
  WHISPER_SMALL_EN,
  WHISPER_DISTIL_SMALL_EN,
  VIBEVOICE_ASR,
  VIBEVOICE_ASR_4BIT,
] as const;

export const LIVE_MODEL_PRESETS = [
  WHISPER_LARGE_V3,
  WHISPER_DISTIL_LARGE_V3,
  WHISPER_LARGE_V3_TURBO,
  WHISPER_MEDIUM,
  WHISPER_MEDIUM_EN,
  WHISPER_DISTIL_MEDIUM_EN,
  WHISPER_SMALL,
  WHISPER_SMALL_EN,
  WHISPER_DISTIL_SMALL_EN,
] as const;

export const ONBOARDING_MAIN_MODEL_OPTIONS = [
  ...MAIN_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
] as const;

export const ONBOARDING_LIVE_MODEL_OPTIONS = [
  ...LIVE_MODEL_PRESETS,
  MODEL_DISABLED_OPTION,
] as const;

export type OptionalDependencyBootstrapFeatureStatus = {
  available: boolean;
  reason?: string;
};

export type OptionalDependencyBootstrapStatus = {
  source: 'runtime-volume-bootstrap-status';
  whisper?: OptionalDependencyBootstrapFeatureStatus;
  nemo?: OptionalDependencyBootstrapFeatureStatus;
  vibevoiceAsr?: OptionalDependencyBootstrapFeatureStatus;
} | null;

export type InstallFlagPatch = {
  installWhisper?: true;
  installNemo?: true;
  installVibeVoiceAsr?: true;
};

function normalize(value: string | null | undefined): string {
  return (value ?? '').trim();
}

export function normalizeForModelFamily(value: string | null | undefined): string {
  const normalized = normalize(value);
  if (
    !normalized ||
    normalized === DISABLED_MODEL_SENTINEL ||
    normalized === MODEL_DISABLED_OPTION
  ) {
    return '';
  }
  return normalized;
}

export function isModelDisabled(value: string | null | undefined): boolean {
  return normalizeForModelFamily(value).length === 0;
}

export function modelFamilyFromName(value: string | null | undefined): ModelFamily {
  const modelName = normalizeForModelFamily(value);
  if (!modelName) return 'none';
  if (isNemoModel(modelName)) return 'nemo';
  if (isVibeVoiceASRModel(modelName)) return 'vibevoice';
  return 'whisper';
}

export function familyDisplayName(family: Exclude<ModelFamily, 'none'>): string {
  if (family === 'whisper') return 'faster-whisper';
  if (family === 'nemo') return 'NeMo';
  return 'VibeVoice-ASR';
}

export function toBackendModelEnvValue(value: string | null | undefined): string {
  const normalized = normalize(value);
  if (!normalized) return '';
  if (normalized === MODEL_DISABLED_OPTION || normalized === DISABLED_MODEL_SENTINEL) {
    return DISABLED_MODEL_SENTINEL;
  }
  if (
    normalized === MODEL_DEFAULT_LOADING_PLACEHOLDER ||
    normalized === MAIN_MODEL_CUSTOM_OPTION ||
    normalized === LIVE_MODEL_CUSTOM_OPTION
  ) {
    return '';
  }
  return normalized;
}

export function resolveMainModelSelectionValue(
  mainSelection: string,
  mainCustomModel: string,
  configuredMainModel: string,
): string {
  if (mainSelection === MODEL_DISABLED_OPTION) {
    return DISABLED_MODEL_SENTINEL;
  }
  if (mainSelection === MAIN_MODEL_CUSTOM_OPTION) {
    return mainCustomModel.trim() || configuredMainModel;
  }
  if (mainSelection === MODEL_DEFAULT_LOADING_PLACEHOLDER) {
    return configuredMainModel || mainSelection;
  }
  return mainSelection;
}

export function resolveLiveModelSelectionValue(
  liveSelection: string,
  liveCustomModel: string,
  resolvedMainModel: string,
  configuredLiveModel: string,
): string {
  if (liveSelection === MODEL_DISABLED_OPTION) {
    return DISABLED_MODEL_SENTINEL;
  }
  if (liveSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION) {
    return resolvedMainModel;
  }
  if (liveSelection === LIVE_MODEL_CUSTOM_OPTION) {
    return liveCustomModel.trim() || configuredLiveModel || resolvedMainModel;
  }
  return liveSelection;
}

export function computeRequiredModelFamilies(
  models: { mainModel?: string | null; liveModel?: string | null } | null | undefined,
): Exclude<ModelFamily, 'none'>[] {
  const required = new Set<Exclude<ModelFamily, 'none'>>();
  const mainFamily = modelFamilyFromName(models?.mainModel);
  const liveFamily = modelFamilyFromName(models?.liveModel);
  if (mainFamily !== 'none') required.add(mainFamily);
  if (liveFamily !== 'none') required.add(liveFamily);
  return Array.from(required);
}

export function computeMissingModelFamilies(options: {
  mainModel?: string | null;
  liveModel?: string | null;
  composeInstallWhisperEnabled: boolean;
  composeInstallNemoEnabled: boolean;
  composeInstallVibeVoiceAsrEnabled: boolean;
  bootstrapStatus: OptionalDependencyBootstrapStatus;
}): Exclude<ModelFamily, 'none'>[] {
  const requiredFamilies = computeRequiredModelFamilies({
    mainModel: options.mainModel,
    liveModel: options.liveModel,
  });
  if (requiredFamilies.length === 0) return [];

  const installedFamilies = new Set<Exclude<ModelFamily, 'none'>>();

  if (
    options.composeInstallWhisperEnabled ||
    options.bootstrapStatus?.whisper?.available === true
  ) {
    installedFamilies.add('whisper');
  }
  if (options.composeInstallNemoEnabled || options.bootstrapStatus?.nemo?.available === true) {
    installedFamilies.add('nemo');
  }
  if (
    options.composeInstallVibeVoiceAsrEnabled ||
    options.bootstrapStatus?.vibevoiceAsr?.available === true
  ) {
    installedFamilies.add('vibevoice');
  }

  return requiredFamilies.filter((family) => !installedFamilies.has(family));
}

export function toInstallFlagPatch(
  missingFamilies: readonly Exclude<ModelFamily, 'none'>[],
): InstallFlagPatch {
  const nextFlags: InstallFlagPatch = {};
  for (const family of missingFamilies) {
    if (family === 'whisper') {
      nextFlags.installWhisper = true;
      continue;
    }
    if (family === 'nemo') {
      nextFlags.installNemo = true;
      continue;
    }
    if (family === 'vibevoice') {
      nextFlags.installVibeVoiceAsr = true;
    }
  }
  return nextFlags;
}

export function normalizeOnboardingModelSelection(value: string, fallback: string): string {
  const normalized = normalize(value);
  if (!normalized) return fallback;
  return normalized;
}

export function mapBackendModelToUiSelection(value: string | null | undefined): string {
  const normalized = normalize(value);
  if (!normalized || normalized === DISABLED_MODEL_SENTINEL) {
    return MODEL_DISABLED_OPTION;
  }
  return normalized;
}
