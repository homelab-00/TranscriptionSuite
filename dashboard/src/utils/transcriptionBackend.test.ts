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
