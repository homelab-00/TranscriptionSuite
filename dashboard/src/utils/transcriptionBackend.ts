export type TranscriptionBackendType =
  | 'whisper'
  | 'parakeet'
  | 'canary'
  | 'vibevoice_asr'
  | 'mlx_parakeet'
  | 'mlx_canary'
  | 'mlx_whisper'
  | 'mlx_vibevoice';

function normalizeModelName(modelName: string | null | undefined): string {
  return (modelName ?? '').trim().toLowerCase();
}

// These mirror the patterns in server/backend/core/stt/backends/factory.py
const MLX_PARAKEET_PATTERN = /^mlx-community\/parakeet/i;
// Matches community Canary MLX ports: eelcor/canary-1b-v2-mlx, Mediform/canary-1b-v2-mlx-q8, etc.
const MLX_CANARY_PATTERN = /^[^/]+\/canary[^/]*-mlx/i;
// MLX VibeVoice must be checked before the generic VibeVoice pattern.
const MLX_VIBEVOICE_PATTERN = /^mlx-community\/vibevoice-asr/i;
const MLX_PATTERN = /^mlx-community\//i;

export function detectTranscriptionBackendType(
  modelName: string | null | undefined,
): TranscriptionBackendType {
  const model = normalizeModelName(modelName);

  if (/^nvidia\/(parakeet|nemotron-speech)/.test(model)) return 'parakeet';
  if (/^nvidia\/canary/.test(model)) return 'canary';
  // MLX VibeVoice must be checked before the generic VibeVoice pattern.
  if (MLX_VIBEVOICE_PATTERN.test(model)) return 'mlx_vibevoice';
  if (/^[^/]+\/vibevoice-asr(?:-[^/]+)?$/.test(model)) return 'vibevoice_asr';
  if (MLX_PARAKEET_PATTERN.test(model)) return 'mlx_parakeet';
  if (MLX_CANARY_PATTERN.test(model)) return 'mlx_canary';
  if (MLX_PATTERN.test(model)) return 'mlx_whisper';
  return 'whisper';
}

export function supportsExplicitWordTimestampToggle(modelName: string | null | undefined): boolean {
  return detectTranscriptionBackendType(modelName) !== 'vibevoice_asr';
}
