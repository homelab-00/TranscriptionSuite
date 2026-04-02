import { describe, it, expect } from 'vitest';
import {
  normalizeForModelFamily,
  isModelDisabled,
  modelFamilyFromName,
  familyDisplayName,
  toBackendModelEnvValue,
  resolveMainModelSelectionValue,
  resolveLiveModelSelectionValue,
  computeRequiredModelFamilies,
  computeMissingModelFamilies,
  toInstallFlagPatch,
  normalizeOnboardingModelSelection,
  mapBackendModelToUiSelection,
  DISABLED_MODEL_SENTINEL,
  MODEL_DISABLED_OPTION,
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MAIN_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  MAIN_RECOMMENDED_MODEL,
  VULKAN_RECOMMENDED_MODEL,
  GGML_LARGE_V3,
  GGML_LARGE_V3_Q5_0,
  GGML_LARGE_V3_TURBO,
  GGML_LARGE_V3_TURBO_Q5_0,
  GGML_LARGE_V3_TURBO_Q8_0,
  GGML_MEDIUM,
  GGML_MEDIUM_Q5_0,
  GGML_MEDIUM_EN,
  GGML_SMALL,
  GGML_SMALL_Q5_1,
  GGML_SMALL_EN,
} from './modelSelection';

// ---------------------------------------------------------------------------
// normalizeForModelFamily
// ---------------------------------------------------------------------------
describe('normalizeForModelFamily', () => {
  it('trims whitespace', () => {
    expect(normalizeForModelFamily('  nvidia/canary-1b-v2  ')).toBe('nvidia/canary-1b-v2');
  });

  it('returns empty string for null/undefined/empty', () => {
    expect(normalizeForModelFamily(null)).toBe('');
    expect(normalizeForModelFamily(undefined)).toBe('');
    expect(normalizeForModelFamily('')).toBe('');
  });

  it('returns empty string for the disabled sentinel', () => {
    expect(normalizeForModelFamily(DISABLED_MODEL_SENTINEL)).toBe('');
  });

  it('returns empty string for the disabled display option', () => {
    expect(normalizeForModelFamily(MODEL_DISABLED_OPTION)).toBe('');
  });
});

// ---------------------------------------------------------------------------
// isModelDisabled
// ---------------------------------------------------------------------------
describe('isModelDisabled', () => {
  it('returns true for sentinel value', () => {
    expect(isModelDisabled(DISABLED_MODEL_SENTINEL)).toBe(true);
  });

  it('returns true for display option', () => {
    expect(isModelDisabled(MODEL_DISABLED_OPTION)).toBe(true);
  });

  it('returns true for null/undefined/empty', () => {
    expect(isModelDisabled(null)).toBe(true);
    expect(isModelDisabled(undefined)).toBe(true);
    expect(isModelDisabled('')).toBe(true);
  });

  it('returns false for a real model name', () => {
    expect(isModelDisabled('nvidia/parakeet-tdt-0.6b-v3')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// modelFamilyFromName
// ---------------------------------------------------------------------------
describe('modelFamilyFromName', () => {
  it('returns nemo for parakeet', () => {
    expect(modelFamilyFromName('nvidia/parakeet-tdt-0.6b-v3')).toBe('nemo');
  });

  it('returns nemo for canary', () => {
    expect(modelFamilyFromName('nvidia/canary-1b-v2')).toBe('nemo');
  });

  it('returns vibevoice for VibeVoice-ASR', () => {
    expect(modelFamilyFromName('microsoft/VibeVoice-ASR')).toBe('vibevoice');
  });

  it('returns whisper for faster-whisper models', () => {
    expect(modelFamilyFromName('Systran/faster-whisper-large-v3')).toBe('whisper');
  });

  it('returns mlx for MLX VibeVoice-ASR (not vibevoice)', () => {
    expect(modelFamilyFromName('mlx-community/VibeVoice-ASR-bf16')).toBe('mlx');
  });

  it('returns mlx for MLX whisper models', () => {
    expect(modelFamilyFromName('mlx-community/whisper-large-v3-mlx')).toBe('mlx');
    expect(modelFamilyFromName('mlx-community/whisper-large-v3-turbo-asr-fp16')).toBe('mlx');
  });

  it('returns none for disabled/empty', () => {
    expect(modelFamilyFromName(null)).toBe('none');
    expect(modelFamilyFromName(DISABLED_MODEL_SENTINEL)).toBe('none');
    expect(modelFamilyFromName('')).toBe('none');
  });
});

// ---------------------------------------------------------------------------
// familyDisplayName
// ---------------------------------------------------------------------------
describe('familyDisplayName', () => {
  it('returns faster-whisper for whisper', () => {
    expect(familyDisplayName('whisper')).toBe('faster-whisper');
  });

  it('returns NeMo for nemo', () => {
    expect(familyDisplayName('nemo')).toBe('NeMo');
  });

  it('returns VibeVoice-ASR for vibevoice', () => {
    expect(familyDisplayName('vibevoice')).toBe('VibeVoice-ASR');
  });
});

// ---------------------------------------------------------------------------
// toBackendModelEnvValue
// ---------------------------------------------------------------------------
describe('toBackendModelEnvValue', () => {
  it('returns model name as-is for real models', () => {
    expect(toBackendModelEnvValue('nvidia/canary-1b-v2')).toBe('nvidia/canary-1b-v2');
  });

  it('returns sentinel for disabled option', () => {
    expect(toBackendModelEnvValue(MODEL_DISABLED_OPTION)).toBe(DISABLED_MODEL_SENTINEL);
  });

  it('returns sentinel for raw sentinel input', () => {
    expect(toBackendModelEnvValue(DISABLED_MODEL_SENTINEL)).toBe(DISABLED_MODEL_SENTINEL);
  });

  it('returns empty string for placeholder/custom options', () => {
    expect(toBackendModelEnvValue(MODEL_DEFAULT_LOADING_PLACEHOLDER)).toBe('');
    expect(toBackendModelEnvValue(MAIN_MODEL_CUSTOM_OPTION)).toBe('');
    expect(toBackendModelEnvValue(LIVE_MODEL_CUSTOM_OPTION)).toBe('');
  });

  it('returns empty string for null/undefined/empty', () => {
    expect(toBackendModelEnvValue(null)).toBe('');
    expect(toBackendModelEnvValue(undefined)).toBe('');
    expect(toBackendModelEnvValue('')).toBe('');
  });
});

// ---------------------------------------------------------------------------
// resolveMainModelSelectionValue
// ---------------------------------------------------------------------------
describe('resolveMainModelSelectionValue', () => {
  it('returns sentinel when disabled', () => {
    expect(resolveMainModelSelectionValue(MODEL_DISABLED_OPTION, '', '')).toBe(
      DISABLED_MODEL_SENTINEL,
    );
  });

  it('returns custom model when custom option selected', () => {
    expect(resolveMainModelSelectionValue(MAIN_MODEL_CUSTOM_OPTION, ' my/model ', 'fallback')).toBe(
      'my/model',
    );
  });

  it('falls back to configured model when custom is empty', () => {
    expect(resolveMainModelSelectionValue(MAIN_MODEL_CUSTOM_OPTION, '', 'server-default')).toBe(
      'server-default',
    );
  });

  it('returns configured model for loading placeholder', () => {
    expect(
      resolveMainModelSelectionValue(MODEL_DEFAULT_LOADING_PLACEHOLDER, '', 'server-model'),
    ).toBe('server-model');
  });

  it('returns selection as-is for preset models', () => {
    expect(resolveMainModelSelectionValue(MAIN_RECOMMENDED_MODEL, '', '')).toBe(
      MAIN_RECOMMENDED_MODEL,
    );
  });
});

// ---------------------------------------------------------------------------
// resolveLiveModelSelectionValue
// ---------------------------------------------------------------------------
describe('resolveLiveModelSelectionValue', () => {
  it('returns sentinel when disabled', () => {
    expect(resolveLiveModelSelectionValue(MODEL_DISABLED_OPTION, '', '', '')).toBe(
      DISABLED_MODEL_SENTINEL,
    );
  });

  it('returns resolved main model for same-as-main option', () => {
    expect(
      resolveLiveModelSelectionValue(LIVE_MODEL_SAME_AS_MAIN_OPTION, '', 'main-model', ''),
    ).toBe('main-model');
  });

  it('returns custom model when custom option selected', () => {
    expect(
      resolveLiveModelSelectionValue(LIVE_MODEL_CUSTOM_OPTION, ' custom/live ', 'main', 'cfg'),
    ).toBe('custom/live');
  });

  it('falls back through configured then main when custom is empty', () => {
    expect(resolveLiveModelSelectionValue(LIVE_MODEL_CUSTOM_OPTION, '', 'main', 'cfg-live')).toBe(
      'cfg-live',
    );
    expect(resolveLiveModelSelectionValue(LIVE_MODEL_CUSTOM_OPTION, '', 'main', '')).toBe('main');
  });
});

// ---------------------------------------------------------------------------
// computeRequiredModelFamilies
// ---------------------------------------------------------------------------
describe('computeRequiredModelFamilies', () => {
  it('returns empty for null input', () => {
    expect(computeRequiredModelFamilies(null)).toEqual([]);
  });

  it('returns unique families for both models', () => {
    const result = computeRequiredModelFamilies({
      mainModel: 'nvidia/parakeet-tdt-0.6b-v3',
      liveModel: 'Systran/faster-whisper-medium',
    });

    expect(result).toContain('nemo');
    expect(result).toContain('whisper');
    expect(result).toHaveLength(2);
  });

  it('deduplicates when both models use same family', () => {
    const result = computeRequiredModelFamilies({
      mainModel: 'Systran/faster-whisper-large-v3',
      liveModel: 'Systran/faster-whisper-small',
    });

    expect(result).toEqual(['whisper']);
  });

  it('excludes disabled models', () => {
    const result = computeRequiredModelFamilies({
      mainModel: 'nvidia/canary-1b-v2',
      liveModel: DISABLED_MODEL_SENTINEL,
    });

    expect(result).toEqual(['nemo']);
  });
});

// ---------------------------------------------------------------------------
// computeMissingModelFamilies
// ---------------------------------------------------------------------------
describe('computeMissingModelFamilies', () => {
  it('returns empty when no model is selected', () => {
    expect(
      computeMissingModelFamilies({
        composeInstallWhisperEnabled: false,
        composeInstallNemoEnabled: false,
        composeInstallVibeVoiceAsrEnabled: false,
        bootstrapStatus: null,
      }),
    ).toEqual([]);
  });

  it('returns missing family when compose flag not set', () => {
    const result = computeMissingModelFamilies({
      mainModel: 'nvidia/parakeet-tdt-0.6b-v3',
      composeInstallWhisperEnabled: false,
      composeInstallNemoEnabled: false,
      composeInstallVibeVoiceAsrEnabled: false,
      bootstrapStatus: null,
    });

    expect(result).toEqual(['nemo']);
  });

  it('returns empty when compose flag covers the family', () => {
    const result = computeMissingModelFamilies({
      mainModel: 'nvidia/parakeet-tdt-0.6b-v3',
      composeInstallWhisperEnabled: false,
      composeInstallNemoEnabled: true,
      composeInstallVibeVoiceAsrEnabled: false,
      bootstrapStatus: null,
    });

    expect(result).toEqual([]);
  });

  it('returns empty when bootstrap status covers the family', () => {
    const result = computeMissingModelFamilies({
      mainModel: 'Systran/faster-whisper-medium',
      composeInstallWhisperEnabled: false,
      composeInstallNemoEnabled: false,
      composeInstallVibeVoiceAsrEnabled: false,
      bootstrapStatus: {
        source: 'runtime-volume-bootstrap-status',
        whisper: { available: true },
      },
    });

    expect(result).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// toInstallFlagPatch
// ---------------------------------------------------------------------------
describe('toInstallFlagPatch', () => {
  it('returns empty object for empty input', () => {
    expect(toInstallFlagPatch([])).toEqual({});
  });

  it('sets installWhisper for whisper family', () => {
    expect(toInstallFlagPatch(['whisper'])).toEqual({ installWhisper: true });
  });

  it('sets installNemo for nemo family', () => {
    expect(toInstallFlagPatch(['nemo'])).toEqual({ installNemo: true });
  });

  it('sets installVibeVoiceAsr for vibevoice family', () => {
    expect(toInstallFlagPatch(['vibevoice'])).toEqual({ installVibeVoiceAsr: true });
  });

  it('sets all flags for all families', () => {
    expect(toInstallFlagPatch(['whisper', 'nemo', 'vibevoice'])).toEqual({
      installWhisper: true,
      installNemo: true,
      installVibeVoiceAsr: true,
    });
  });
});

// ---------------------------------------------------------------------------
// normalizeOnboardingModelSelection
// ---------------------------------------------------------------------------
describe('normalizeOnboardingModelSelection', () => {
  it('returns trimmed value when non-empty', () => {
    expect(normalizeOnboardingModelSelection(' nvidia/canary-1b-v2 ', 'fallback')).toBe(
      'nvidia/canary-1b-v2',
    );
  });

  it('returns fallback for empty value', () => {
    expect(normalizeOnboardingModelSelection('', 'fallback')).toBe('fallback');
  });
});

// ---------------------------------------------------------------------------
// mapBackendModelToUiSelection
// ---------------------------------------------------------------------------
describe('mapBackendModelToUiSelection', () => {
  it('returns disabled option for sentinel', () => {
    expect(mapBackendModelToUiSelection(DISABLED_MODEL_SENTINEL)).toBe(MODEL_DISABLED_OPTION);
  });

  it('returns disabled option for null/undefined/empty', () => {
    expect(mapBackendModelToUiSelection(null)).toBe(MODEL_DISABLED_OPTION);
    expect(mapBackendModelToUiSelection(undefined)).toBe(MODEL_DISABLED_OPTION);
    expect(mapBackendModelToUiSelection('')).toBe(MODEL_DISABLED_OPTION);
  });

  it('returns the model name for real models', () => {
    expect(mapBackendModelToUiSelection('nvidia/canary-1b-v2')).toBe('nvidia/canary-1b-v2');
  });
});

// ---------------------------------------------------------------------------
// GGML constants
// ---------------------------------------------------------------------------
describe('GGML constants', () => {
  it('GGML_LARGE_V3 is defined', () => {
    expect(GGML_LARGE_V3).toBe('ggml-large-v3.bin');
  });

  it('GGML_LARGE_V3_Q5_0 is defined', () => {
    expect(GGML_LARGE_V3_Q5_0).toBe('ggml-large-v3-q5_0.bin');
  });

  it('GGML_LARGE_V3_TURBO is defined', () => {
    expect(GGML_LARGE_V3_TURBO).toBe('ggml-large-v3-turbo.bin');
  });

  it('GGML_LARGE_V3_TURBO_Q5_0 is defined', () => {
    expect(GGML_LARGE_V3_TURBO_Q5_0).toBe('ggml-large-v3-turbo-q5_0.bin');
  });

  it('GGML_LARGE_V3_TURBO_Q8_0 is defined', () => {
    expect(GGML_LARGE_V3_TURBO_Q8_0).toBe('ggml-large-v3-turbo-q8_0.bin');
  });

  it('GGML_MEDIUM is defined', () => {
    expect(GGML_MEDIUM).toBe('ggml-medium.bin');
  });

  it('GGML_MEDIUM_Q5_0 is defined', () => {
    expect(GGML_MEDIUM_Q5_0).toBe('ggml-medium-q5_0.bin');
  });

  it('GGML_MEDIUM_EN is defined', () => {
    expect(GGML_MEDIUM_EN).toBe('ggml-medium.en.bin');
  });

  it('GGML_SMALL is defined', () => {
    expect(GGML_SMALL).toBe('ggml-small.bin');
  });

  it('GGML_SMALL_Q5_1 is defined', () => {
    expect(GGML_SMALL_Q5_1).toBe('ggml-small-q5_1.bin');
  });

  it('GGML_SMALL_EN is defined', () => {
    expect(GGML_SMALL_EN).toBe('ggml-small.en.bin');
  });

  it('VULKAN_RECOMMENDED_MODEL points to turbo q8_0', () => {
    expect(VULKAN_RECOMMENDED_MODEL).toBe('ggml-large-v3-turbo-q8_0.bin');
  });
});

// ---------------------------------------------------------------------------
// modelFamilyFromName — whispercpp
// ---------------------------------------------------------------------------
describe('modelFamilyFromName — whispercpp', () => {
  it('returns whispercpp for ggml-large-v3-turbo-q8_0.bin', () => {
    expect(modelFamilyFromName('ggml-large-v3-turbo-q8_0.bin')).toBe('whispercpp');
  });

  it('returns whispercpp for any ggml-*.bin pattern', () => {
    expect(modelFamilyFromName('ggml-small.en.bin')).toBe('whispercpp');
  });

  it('returns whispercpp for *.gguf files', () => {
    expect(modelFamilyFromName('model.gguf')).toBe('whispercpp');
  });

  it('still returns whisper for faster-whisper models (no regression)', () => {
    expect(modelFamilyFromName('Systran/faster-whisper-large-v3')).toBe('whisper');
  });
});

// ---------------------------------------------------------------------------
// familyDisplayName — whispercpp
// ---------------------------------------------------------------------------
describe('familyDisplayName — whispercpp', () => {
  it('returns whisper.cpp for whispercpp family', () => {
    expect(familyDisplayName('whispercpp')).toBe('whisper.cpp');
  });
});

// ---------------------------------------------------------------------------
// computeMissingModelFamilies — whispercpp never missing
// ---------------------------------------------------------------------------
describe('computeMissingModelFamilies — whispercpp never missing', () => {
  it('does not report whispercpp as missing when no compose flags set', () => {
    const result = computeMissingModelFamilies({
      mainModel: 'ggml-large-v3-turbo-q8_0.bin',
      composeInstallWhisperEnabled: false,
      composeInstallNemoEnabled: false,
      composeInstallVibeVoiceAsrEnabled: false,
      bootstrapStatus: null,
    });
    expect(result).not.toContain('whispercpp');
    expect(result).toEqual([]);
  });

  it('does not report whispercpp when used as live model', () => {
    const result = computeMissingModelFamilies({
      liveModel: 'ggml-small.bin',
      composeInstallWhisperEnabled: false,
      composeInstallNemoEnabled: false,
      composeInstallVibeVoiceAsrEnabled: false,
      bootstrapStatus: null,
    });
    expect(result).not.toContain('whispercpp');
  });
});

// ---------------------------------------------------------------------------
// toInstallFlagPatch — whispercpp is no-op
// ---------------------------------------------------------------------------
describe('toInstallFlagPatch — whispercpp no-op', () => {
  it('returns empty object for whispercpp family', () => {
    expect(toInstallFlagPatch(['whispercpp'])).toEqual({});
  });

  it('whispercpp alongside other families does not add an extra flag', () => {
    const result = toInstallFlagPatch(['whispercpp', 'whisper']);
    expect(result).toEqual({ installWhisper: true });
    expect(Object.keys(result)).not.toContain('installWhisperCpp');
  });
});
