import { describe, it, expect } from 'vitest';
import {
  isParakeetModel,
  isCanaryModel,
  isNemoModel,
  isWhisperModel,
  isVibeVoiceASRModel,
  filterLanguagesForModel,
  supportsTranslation,
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

  it('returns false for null/undefined/empty', () => {
    expect(isVibeVoiceASRModel(null)).toBe(false);
    expect(isVibeVoiceASRModel(undefined)).toBe(false);
    expect(isVibeVoiceASRModel('')).toBe(false);
  });
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

  it('filters to NeMo languages + Auto Detect for canary', () => {
    const result = filterLanguagesForModel(allLanguages, 'nvidia/canary-1b-v2');

    expect(result).toContain('Auto Detect');
    expect(result).not.toContain('Japanese');
  });

  it('returns only Auto Detect for vibevoice', () => {
    const result = filterLanguagesForModel(allLanguages, 'microsoft/VibeVoice-ASR');

    expect(result).toEqual(['Auto Detect']);
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

  it('returns true for standard whisper model', () => {
    expect(supportsTranslation('Systran/faster-whisper-large-v3')).toBe(true);
  });

  it('returns false for turbo models', () => {
    expect(supportsTranslation('Systran/faster-whisper-large-v3-turbo')).toBe(false);
  });

  it('returns false for .en models', () => {
    expect(supportsTranslation('Systran/faster-whisper-medium.en')).toBe(false);
  });

  it('returns false for distil-large-v3', () => {
    expect(supportsTranslation('Systran/faster-distil-large-v3')).toBe(false);
  });

  it('returns true for unknown/empty (permissive default)', () => {
    expect(supportsTranslation(null)).toBe(true);
    expect(supportsTranslation(undefined)).toBe(true);
    expect(supportsTranslation('')).toBe(true);
  });
});
