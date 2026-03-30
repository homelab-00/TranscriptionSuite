import { describe, it, expect } from 'vitest';
import {
  detectModelFamily,
  getModelById,
  getModelsByFamily,
  MODEL_REGISTRY,
} from './modelRegistry';

// ---------------------------------------------------------------------------
// detectModelFamily — GGML / whispercpp
// ---------------------------------------------------------------------------
describe('detectModelFamily — whispercpp', () => {
  it('returns whispercpp for ggml-large-v3-turbo-q8_0.bin', () => {
    expect(detectModelFamily('ggml-large-v3-turbo-q8_0.bin')).toBe('whispercpp');
  });

  it('returns whispercpp for ggml-large-v3.bin', () => {
    expect(detectModelFamily('ggml-large-v3.bin')).toBe('whispercpp');
  });

  it('returns whispercpp for ggml-small.en.bin', () => {
    expect(detectModelFamily('ggml-small.en.bin')).toBe('whispercpp');
  });

  it('returns whispercpp for *.gguf files', () => {
    expect(detectModelFamily('some-model.gguf')).toBe('whispercpp');
  });

  it('does NOT return whispercpp for faster-whisper models', () => {
    expect(detectModelFamily('Systran/faster-whisper-large-v3')).toBe('whisper');
  });

  it('does NOT return whispercpp for nemo models', () => {
    expect(detectModelFamily('nvidia/parakeet-tdt-0.6b-v3')).toBe('nemo');
  });
});

// ---------------------------------------------------------------------------
// detectModelFamily — existing families unchanged
// ---------------------------------------------------------------------------
describe('detectModelFamily — existing families', () => {
  it('returns nemo for parakeet', () => {
    expect(detectModelFamily('nvidia/parakeet-tdt-0.6b-v3')).toBe('nemo');
  });

  it('returns nemo for canary', () => {
    expect(detectModelFamily('nvidia/canary-1b-v2')).toBe('nemo');
  });

  it('returns vibevoice for VibeVoice-ASR', () => {
    expect(detectModelFamily('microsoft/VibeVoice-ASR')).toBe('vibevoice');
  });

  it('returns whisper for faster-whisper models', () => {
    expect(detectModelFamily('Systran/faster-whisper-large-v3')).toBe('whisper');
  });
});

// ---------------------------------------------------------------------------
// MODEL_REGISTRY — GGML entries
// ---------------------------------------------------------------------------
describe('MODEL_REGISTRY GGML entries', () => {
  const ggmlModels = MODEL_REGISTRY.filter((m) => m.family === 'whispercpp');

  it('has 11 GGML entries', () => {
    expect(ggmlModels).toHaveLength(11);
  });

  it('all GGML entries have requiresRuntime: vulkan', () => {
    for (const m of ggmlModels) {
      expect(m.requiresRuntime).toBe('vulkan');
    }
  });

  it('all GGML entries have roles: [main] only', () => {
    for (const m of ggmlModels) {
      expect(m.roles).toEqual(['main']);
    }
  });

  it('all GGML entries have liveMode: false', () => {
    for (const m of ggmlModels) {
      expect(m.capabilities.liveMode).toBe(false);
    }
  });

  it('all GGML entries have diarization: false', () => {
    for (const m of ggmlModels) {
      expect(m.capabilities.diarization).toBe(false);
    }
  });

  it('all GGML entries have HuggingFace URL pointing to ggerganov/whisper.cpp', () => {
    for (const m of ggmlModels) {
      expect(m.huggingfaceUrl).toContain('ggerganov/whisper.cpp');
    }
  });

  it('includes the recommended ggml-large-v3-turbo-q8_0.bin entry', () => {
    const recommended = getModelById('ggml-large-v3-turbo-q8_0.bin');
    expect(recommended).toBeDefined();
    expect(recommended?.family).toBe('whispercpp');
  });
});

// ---------------------------------------------------------------------------
// MODEL_REGISTRY — requiresRuntime on existing models
// ---------------------------------------------------------------------------
describe('MODEL_REGISTRY requiresRuntime field', () => {
  it('faster-whisper models have requiresRuntime: cuda', () => {
    const whisperModels = MODEL_REGISTRY.filter((m) => m.family === 'whisper');
    expect(whisperModels.length).toBeGreaterThan(0);
    for (const m of whisperModels) {
      expect(m.requiresRuntime).toBe('cuda');
    }
  });

  it('nemo models have requiresRuntime: cuda', () => {
    const nemoModels = MODEL_REGISTRY.filter((m) => m.family === 'nemo');
    expect(nemoModels.length).toBeGreaterThan(0);
    for (const m of nemoModels) {
      expect(m.requiresRuntime).toBe('cuda');
    }
  });

  it('vibevoice models have requiresRuntime: cuda', () => {
    const vibevoiceModels = MODEL_REGISTRY.filter((m) => m.family === 'vibevoice');
    expect(vibevoiceModels.length).toBeGreaterThan(0);
    for (const m of vibevoiceModels) {
      expect(m.requiresRuntime).toBe('cuda');
    }
  });
});

// ---------------------------------------------------------------------------
// getModelsByFamily
// ---------------------------------------------------------------------------
describe('getModelsByFamily', () => {
  it('returns whispercpp models', () => {
    const result = getModelsByFamily('whispercpp');
    expect(result.length).toBe(11);
  });
});
