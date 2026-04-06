import { describe, it, expect } from 'vitest';
import {
  detectTranscriptionBackendType,
  supportsExplicitWordTimestampToggle,
} from './transcriptionBackend';

// ---------------------------------------------------------------------------
// detectTranscriptionBackendType
// ---------------------------------------------------------------------------
describe('detectTranscriptionBackendType', () => {
  it('returns parakeet for nvidia/parakeet models', () => {
    expect(detectTranscriptionBackendType('nvidia/parakeet-tdt-0.6b-v3')).toBe('parakeet');
  });

  it('returns parakeet for nvidia/nemotron-speech models', () => {
    expect(detectTranscriptionBackendType('nvidia/nemotron-speech-large')).toBe('parakeet');
  });

  it('returns canary for nvidia/canary models', () => {
    expect(detectTranscriptionBackendType('nvidia/canary-1b-v2')).toBe('canary');
  });

  it('returns vibevoice_asr for VibeVoice-ASR models', () => {
    expect(detectTranscriptionBackendType('microsoft/VibeVoice-ASR')).toBe('vibevoice_asr');
    expect(detectTranscriptionBackendType('scerz/VibeVoice-ASR-4bit')).toBe('vibevoice_asr');
  });

  it('returns whisper for faster-whisper models', () => {
    expect(detectTranscriptionBackendType('Systran/faster-whisper-large-v3')).toBe('whisper');
    expect(detectTranscriptionBackendType('Systran/faster-whisper-medium')).toBe('whisper');
  });

  it('returns whisper for null/undefined/empty (default)', () => {
    expect(detectTranscriptionBackendType(null)).toBe('whisper');
    expect(detectTranscriptionBackendType(undefined)).toBe('whisper');
    expect(detectTranscriptionBackendType('')).toBe('whisper');
  });

  it('returns whisper for unknown model names', () => {
    expect(detectTranscriptionBackendType('some/unknown-model')).toBe('whisper');
  });

  it('returns mlx_parakeet for mlx-community/parakeet models', () => {
    expect(detectTranscriptionBackendType('mlx-community/parakeet-tdt-0.6b-v3')).toBe(
      'mlx_parakeet',
    );
    expect(detectTranscriptionBackendType('mlx-community/parakeet-tdt-1.1b')).toBe('mlx_parakeet');
  });

  it('returns mlx_canary for community Canary MLX ports', () => {
    expect(detectTranscriptionBackendType('eelcor/canary-1b-v2-mlx')).toBe('mlx_canary');
    expect(detectTranscriptionBackendType('Mediform/canary-1b-v2-mlx-q8')).toBe('mlx_canary');
    expect(detectTranscriptionBackendType('qfuxa/canary-mlx')).toBe('mlx_canary');
  });

  it('returns mlx_whisper for generic mlx-community models', () => {
    expect(detectTranscriptionBackendType('mlx-community/whisper-large-v3-mlx')).toBe(
      'mlx_whisper',
    );
    expect(detectTranscriptionBackendType('mlx-community/distil-whisper-large-v3')).toBe(
      'mlx_whisper',
    );
  });

  it('returns mlx_vibevoice for mlx-community/vibevoice-asr, not generic vibevoice_asr', () => {
    expect(detectTranscriptionBackendType('mlx-community/vibevoice-asr')).toBe('mlx_vibevoice');
    expect(detectTranscriptionBackendType('mlx-community/vibevoice-asr-4bit')).toBe(
      'mlx_vibevoice',
    );
  });
});

// ---------------------------------------------------------------------------
// supportsExplicitWordTimestampToggle
// ---------------------------------------------------------------------------
describe('supportsExplicitWordTimestampToggle', () => {
  it('returns true for whisper models', () => {
    expect(supportsExplicitWordTimestampToggle('Systran/faster-whisper-large-v3')).toBe(true);
  });

  it('returns true for parakeet models', () => {
    expect(supportsExplicitWordTimestampToggle('nvidia/parakeet-tdt-0.6b-v3')).toBe(true);
  });

  it('returns true for canary models', () => {
    expect(supportsExplicitWordTimestampToggle('nvidia/canary-1b-v2')).toBe(true);
  });

  it('returns false for vibevoice models', () => {
    expect(supportsExplicitWordTimestampToggle('microsoft/VibeVoice-ASR')).toBe(false);
  });
});
