import { describe, it, expect } from 'vitest';
import {
  isParakeetModel,
  isCanaryModel,
  isNemoModel,
  isWhisperModel,
  isWhisperCppModel,
  isVibeVoiceASRModel,
  isEnglishOnlyWhisperModel,
  filterLanguagesForModel,
  pickDefaultLanguage,
  supportsAutoDetect,
  supportsTranslation,
  supportsDiarization,
  NEMO_LANGUAGES,
  CANARY_TRANSLATION_TARGETS,
} from './modelCapabilities';

// ---------------------------------------------------------------------------
// isParakeetModel
// ---------------------------------------------------------------------------
describe('isParakeetModel', () => {
  it('matches nvidia/parakeet-tdt-0.6b-v3', () => {
    expect(isParakeetModel('nvidia/parakeet-tdt-0.6b-v3')).toBe(true);
  });

  it('matches nvidia/nemotron-speech variants', () => {
    expect(isParakeetModel('nvidia/nemotron-speech-large')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(isParakeetModel('NVIDIA/Parakeet-TDT-0.6b-v3')).toBe(true);
  });

  it('rejects canary', () => {
    expect(isParakeetModel('nvidia/canary-1b-v2')).toBe(false);
  });

  it('rejects whisper', () => {
    expect(isParakeetModel('Systran/faster-whisper-large-v3')).toBe(false);
  });

  it('returns false for null/undefined/empty', () => {
    expect(isParakeetModel(null)).toBe(false);
    expect(isParakeetModel(undefined)).toBe(false);
    expect(isParakeetModel('')).toBe(false);
    expect(isParakeetModel('  ')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isCanaryModel
// ---------------------------------------------------------------------------
describe('isCanaryModel', () => {
  it('matches nvidia/canary-1b-v2', () => {
    expect(isCanaryModel('nvidia/canary-1b-v2')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(isCanaryModel('NVIDIA/Canary-1b-v2')).toBe(true);
  });

  it('rejects parakeet', () => {
    expect(isCanaryModel('nvidia/parakeet-tdt-0.6b-v3')).toBe(false);
  });

  it('returns false for null/undefined/empty', () => {
    expect(isCanaryModel(null)).toBe(false);
    expect(isCanaryModel(undefined)).toBe(false);
    expect(isCanaryModel('')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isNemoModel
// ---------------------------------------------------------------------------
describe('isNemoModel', () => {
  it('returns true for parakeet', () => {
    expect(isNemoModel('nvidia/parakeet-tdt-0.6b-v3')).toBe(true);
  });

  it('returns true for canary', () => {
    expect(isNemoModel('nvidia/canary-1b-v2')).toBe(true);
  });

  it('returns false for whisper', () => {
    expect(isNemoModel('Systran/faster-whisper-large-v3')).toBe(false);
  });

  it('returns false for vibevoice', () => {
    expect(isNemoModel('microsoft/VibeVoice-ASR')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isWhisperModel
// ---------------------------------------------------------------------------
describe('isWhisperModel', () => {
  it('returns true for faster-whisper models', () => {
    expect(isWhisperModel('Systran/faster-whisper-large-v3')).toBe(true);
    expect(isWhisperModel('Systran/faster-whisper-medium')).toBe(true);
    expect(isWhisperModel('Systran/faster-whisper-small')).toBe(true);
  });

  it('returns true for new distil/turbo/.en whisper variants', () => {
    expect(isWhisperModel('Systran/faster-distil-whisper-large-v3')).toBe(true);
    expect(isWhisperModel('deepdml/faster-whisper-large-v3-turbo-ct2')).toBe(true);
    expect(isWhisperModel('Systran/faster-whisper-medium.en')).toBe(true);
    expect(isWhisperModel('Systran/faster-whisper-small.en')).toBe(true);
    expect(isWhisperModel('Systran/faster-distil-whisper-medium.en')).toBe(true);
    expect(isWhisperModel('Systran/faster-distil-whisper-small.en')).toBe(true);
  });

  it('returns true for unknown/empty (default backend)', () => {
    expect(isWhisperModel(null)).toBe(true);
    expect(isWhisperModel(undefined)).toBe(true);
    expect(isWhisperModel('')).toBe(true);
  });

  it('returns false for nemo models', () => {
    expect(isWhisperModel('nvidia/parakeet-tdt-0.6b-v3')).toBe(false);
    expect(isWhisperModel('nvidia/canary-1b-v2')).toBe(false);
  });

  it('returns false for vibevoice', () => {
    expect(isWhisperModel('microsoft/VibeVoice-ASR')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isEnglishOnlyWhisperModel
// ---------------------------------------------------------------------------
describe('isEnglishOnlyWhisperModel', () => {
  it('returns true for .en suffixed models', () => {
    expect(isEnglishOnlyWhisperModel('Systran/faster-whisper-medium.en')).toBe(true);
    expect(isEnglishOnlyWhisperModel('Systran/faster-whisper-small.en')).toBe(true);
    expect(isEnglishOnlyWhisperModel('Systran/faster-distil-whisper-medium.en')).toBe(true);
    expect(isEnglishOnlyWhisperModel('Systran/faster-distil-whisper-small.en')).toBe(true);
  });

  it('returns false for multilingual models', () => {
    expect(isEnglishOnlyWhisperModel('Systran/faster-whisper-large-v3')).toBe(false);
    expect(isEnglishOnlyWhisperModel('Systran/faster-whisper-medium')).toBe(false);
    expect(isEnglishOnlyWhisperModel('Systran/faster-distil-whisper-large-v3')).toBe(false);
  });

  it('returns false for null/undefined/empty', () => {
    expect(isEnglishOnlyWhisperModel(null)).toBe(false);
    expect(isEnglishOnlyWhisperModel(undefined)).toBe(false);
    expect(isEnglishOnlyWhisperModel('')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isVibeVoiceASRModel
// ---------------------------------------------------------------------------
describe('isVibeVoiceASRModel', () => {
  it('matches microsoft/VibeVoice-ASR', () => {
    expect(isVibeVoiceASRModel('microsoft/VibeVoice-ASR')).toBe(true);
  });

  it('matches quantised variants', () => {
    expect(isVibeVoiceASRModel('scerz/VibeVoice-ASR-4bit')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(isVibeVoiceASRModel('MICROSOFT/VIBEVOICE-ASR')).toBe(true);
  });

  it('rejects models without owner prefix', () => {
    expect(isVibeVoiceASRModel('VibeVoice-ASR')).toBe(false);
  });

  it('matches MLX VibeVoice-ASR variant', () => {
    expect(isVibeVoiceASRModel('mlx-community/VibeVoice-ASR-bf16')).toBe(true);
  });

  it('returns false for null/undefined/empty', () => {});
});

// ---------------------------------------------------------------------------
// NEMO_LANGUAGES
// ---------------------------------------------------------------------------
describe('NEMO_LANGUAGES', () => {
  it('contains 25 languages', () => {
    expect(NEMO_LANGUAGES.size).toBe(25);
  });

  it('includes English', () => {
    expect(NEMO_LANGUAGES.has('English')).toBe(true);
  });

  it('includes representative European languages', () => {
    for (const lang of ['French', 'German', 'Spanish', 'Italian', 'Polish', 'Ukrainian']) {
      expect(NEMO_LANGUAGES.has(lang)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// CANARY_TRANSLATION_TARGETS
// ---------------------------------------------------------------------------
describe('CANARY_TRANSLATION_TARGETS', () => {
  it('contains 24 languages (NeMo minus English)', () => {
    expect(CANARY_TRANSLATION_TARGETS).toHaveLength(24);
  });

  it('does not include English', () => {
    expect(CANARY_TRANSLATION_TARGETS).not.toContain('English');
  });

  it('every target is a NeMo language', () => {
    for (const lang of CANARY_TRANSLATION_TARGETS) {
      expect(NEMO_LANGUAGES.has(lang)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// filterLanguagesForModel
// ---------------------------------------------------------------------------
describe('filterLanguagesForModel', () => {
  const allLanguages = ['Auto Detect', 'English', 'French', 'Japanese', 'Chinese'];

  it('returns all languages for whisper models', () => {
    expect(filterLanguagesForModel(allLanguages, 'Systran/faster-whisper-large-v3')).toEqual(
      allLanguages,
    );
  });

  it('filters to NeMo languages + Auto Detect for parakeet', () => {
    const result = filterLanguagesForModel(allLanguages, 'nvidia/parakeet-tdt-0.6b-v3');

    expect(result).toContain('Auto Detect');
    expect(result).toContain('English');
    expect(result).toContain('French');
    expect(result).not.toContain('Japanese');
    expect(result).not.toContain('Chinese');
  });

  it('filters to NeMo languages and drops Auto Detect for canary (gh-81)', () => {
    const result = filterLanguagesForModel(allLanguages, 'nvidia/canary-1b-v2');

    expect(result).not.toContain('Auto Detect');
    expect(result).toContain('English');
    expect(result).toContain('French');
    expect(result).not.toContain('Japanese');
  });

  it('returns only Auto Detect for vibevoice', () => {
    const result = filterLanguagesForModel(allLanguages, 'microsoft/VibeVoice-ASR');

    expect(result).toEqual(['Auto Detect']);
  });

  it('returns only Auto Detect for mlx parakeet (no language-hint API)', () => {
    const result = filterLanguagesForModel(allLanguages, 'mlx-community/parakeet-tdt-0.6b-v3');

    expect(result).toEqual(['Auto Detect']);
  });

  it('filters to NeMo languages and drops Auto Detect for mlx canary (gh-81)', () => {
    const result = filterLanguagesForModel(allLanguages, 'eelcor/canary-1b-v2-mlx');

    expect(result).not.toContain('Auto Detect');
    expect(result).toContain('English');
    expect(result).toContain('French');
    expect(result).not.toContain('Japanese');
    expect(result).not.toContain('Chinese');
  });

  it('returns only English for .en whisper models', () => {
    expect(filterLanguagesForModel(allLanguages, 'Systran/faster-whisper-medium.en')).toEqual([
      'English',
    ]);
    expect(filterLanguagesForModel(allLanguages, 'Systran/faster-whisper-small.en')).toEqual([
      'English',
    ]);
    expect(
      filterLanguagesForModel(allLanguages, 'Systran/faster-distil-whisper-medium.en'),
    ).toEqual(['English']);
    expect(filterLanguagesForModel(allLanguages, 'Systran/faster-distil-whisper-small.en')).toEqual(
      ['English'],
    );
  });
});

// ---------------------------------------------------------------------------
// supportsTranslation
// ---------------------------------------------------------------------------
describe('supportsTranslation', () => {
  it('returns false for parakeet (ASR-only)', () => {
    expect(supportsTranslation('nvidia/parakeet-tdt-0.6b-v3')).toBe(false);
  });

  it('returns true for canary', () => {
    expect(supportsTranslation('nvidia/canary-1b-v2')).toBe(true);
  });

  it('returns false for vibevoice', () => {
    expect(supportsTranslation('microsoft/VibeVoice-ASR')).toBe(false);
  });

  it('returns false for mlx parakeet (ASR-only, no translation task)', () => {
    expect(supportsTranslation('mlx-community/parakeet-tdt-0.6b-v3')).toBe(false);
  });

  it('returns false for mlx canary (ASR-only in MLX port)', () => {
    expect(supportsTranslation('eelcor/canary-1b-v2-mlx')).toBe(false);
    expect(supportsTranslation('Mediform/canary-1b-v2-mlx-q8')).toBe(false);
  });

  it('returns true for standard whisper model', () => {
    expect(supportsTranslation('Systran/faster-whisper-large-v3')).toBe(true);
  });

  it('returns false for turbo models', () => {
    expect(supportsTranslation('Systran/faster-whisper-large-v3-turbo')).toBe(false);
  });

  it('returns false for .en models', () => {
    expect(supportsTranslation('Systran/faster-whisper-medium.en')).toBe(false);
  });

  it('returns true for distil-large-v3 (multilingual, supports translation)', () => {
    expect(supportsTranslation('Systran/faster-distil-large-v3')).toBe(true);
    expect(supportsTranslation('Systran/faster-distil-whisper-large-v3')).toBe(true);
  });

  it('returns false for turbo ct2 model', () => {
    expect(supportsTranslation('deepdml/faster-whisper-large-v3-turbo-ct2')).toBe(false);
  });

  it('returns false for .en distil models', () => {
    expect(supportsTranslation('Systran/faster-distil-whisper-medium.en')).toBe(false);
    expect(supportsTranslation('Systran/faster-distil-whisper-small.en')).toBe(false);
  });

  it('returns true for unknown/empty (permissive default)', () => {
    expect(supportsTranslation(null)).toBe(true);
    expect(supportsTranslation(undefined)).toBe(true);
    expect(supportsTranslation('')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// isWhisperCppModel (GGML model detection)
// ---------------------------------------------------------------------------
describe('isWhisperCppModel', () => {
  it('matches ggml- prefixed .bin models', () => {
    expect(isWhisperCppModel('ggml-large-v3.bin')).toBe(true);
    expect(isWhisperCppModel('ggml-base.en.bin')).toBe(true);
    expect(isWhisperCppModel('ggml-medium.bin')).toBe(true);
    expect(isWhisperCppModel('ggml-tiny.bin')).toBe(true);
  });

  it('matches .gguf models', () => {
    expect(isWhisperCppModel('large-v3-turbo.gguf')).toBe(true);
    expect(isWhisperCppModel('whisper-large-v3.gguf')).toBe(true);
  });

  it('matches paths with ggml- prefix', () => {
    expect(isWhisperCppModel('/models/ggml-small.bin')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(isWhisperCppModel('GGML-LARGE-V3.BIN')).toBe(true);
    expect(isWhisperCppModel('model.GGUF')).toBe(true);
  });

  it('rejects HuggingFace-style whisper model names', () => {
    expect(isWhisperCppModel('openai/whisper-large-v3')).toBe(false);
    expect(isWhisperCppModel('Systran/faster-whisper-large-v3')).toBe(false);
  });

  it('rejects NeMo and VibeVoice models', () => {
    expect(isWhisperCppModel('nvidia/parakeet-ctc-1.1b')).toBe(false);
    expect(isWhisperCppModel('nvidia/canary-1b')).toBe(false);
    expect(isWhisperCppModel('microsoft/VibeVoice-ASR')).toBe(false);
  });

  it('returns false for null/undefined/empty', () => {
    expect(isWhisperCppModel(null)).toBe(false);
    expect(isWhisperCppModel(undefined)).toBe(false);
    expect(isWhisperCppModel('')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isWhisperModel excludes whisper.cpp models
// ---------------------------------------------------------------------------
describe('isWhisperModel with GGML models', () => {
  it('returns false for GGML models (they use whispercpp backend)', () => {
    expect(isWhisperModel('ggml-large-v3.bin')).toBe(false);
    expect(isWhisperModel('large-v3.gguf')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// supportsDiarization
// ---------------------------------------------------------------------------
describe('supportsDiarization', () => {
  it('returns false for whisper.cpp models (no pyannote)', () => {
    expect(supportsDiarization('ggml-large-v3.bin')).toBe(false);
    expect(supportsDiarization('large-v3.gguf')).toBe(false);
  });

  it('returns true for whisper models', () => {
    expect(supportsDiarization('Systran/faster-whisper-large-v3')).toBe(true);
  });

  it('returns false for VibeVoice models (uses built-in diarization, not pyannote)', () => {
    expect(supportsDiarization('microsoft/VibeVoice-ASR')).toBe(false);
    expect(supportsDiarization('scerz/VibeVoice-ASR-4bit')).toBe(false);
    expect(supportsDiarization('mlx-community/VibeVoice-ASR-bf16')).toBe(false);
  });

  it('returns true for NeMo models', () => {
    expect(supportsDiarization('nvidia/parakeet-tdt-0.6b-v3')).toBe(true);
  });

  it('returns true for null/undefined', () => {
    expect(supportsDiarization(null)).toBe(true);
    expect(supportsDiarization(undefined)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// supportsTranslation with GGML models
// ---------------------------------------------------------------------------
describe('supportsTranslation with GGML models', () => {
  it('returns true for standard GGML models (whisper translate task)', () => {
    expect(supportsTranslation('ggml-large-v3.bin')).toBe(true);
    expect(supportsTranslation('large-v3.gguf')).toBe(true);
  });

  it('returns false for GGML turbo models', () => {
    expect(supportsTranslation('ggml-large-v3-turbo.bin')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// pickDefaultLanguage (gh-81 snap-to-English fallback)
// ---------------------------------------------------------------------------
describe('pickDefaultLanguage', () => {
  it('prefers English when present', () => {
    expect(pickDefaultLanguage(['Bulgarian', 'English', 'Greek'])).toBe('English');
  });

  it('falls back to first option when English is missing', () => {
    expect(pickDefaultLanguage(['French', 'German'])).toBe('French');
  });

  it('returns "Auto Detect" for an empty list (defensive default)', () => {
    expect(pickDefaultLanguage([])).toBe('Auto Detect');
  });

  it('picks English over Auto Detect when both are options', () => {
    expect(pickDefaultLanguage(['Auto Detect', 'English', 'French'])).toBe('English');
  });
});

// ---------------------------------------------------------------------------
// supportsAutoDetect (gh-81)
// ---------------------------------------------------------------------------
describe('supportsAutoDetect', () => {
  it.each([
    'Systran/faster-whisper-large-v3',
    'nvidia/parakeet-tdt-0.6b-v3',
    'mlx-community/parakeet-tdt-0.6b-v3',
    'microsoft/VibeVoice-ASR',
    'ggml-large-v3.bin',
    'Systran/faster-whisper-small.en',
  ])('returns true for auto-detect-capable model: %s', (model) => {
    expect(supportsAutoDetect(model)).toBe(true);
  });

  it.each([
    'nvidia/canary-1b-v2',
    'nvidia/canary-180m-flash',
    'eelcor/canary-1b-v2-mlx',
    'Mediform/canary-1b-v2-mlx-q8',
  ])('returns false for canary model (requires explicit source_lang): %s', (model) => {
    expect(supportsAutoDetect(model)).toBe(false);
  });

  it('returns true for null/undefined/empty (permissive default)', () => {
    expect(supportsAutoDetect(null)).toBe(true);
    expect(supportsAutoDetect(undefined)).toBe(true);
    expect(supportsAutoDetect('')).toBe(true);
  });
});
