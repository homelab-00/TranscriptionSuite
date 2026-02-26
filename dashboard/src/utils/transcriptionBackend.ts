export type TranscriptionBackendType = 'whisper' | 'parakeet' | 'canary' | 'vibevoice_asr';

function normalizeModelName(modelName: string | null | undefined): string {
  return (modelName ?? '').trim().toLowerCase();
}

export function detectTranscriptionBackendType(
  modelName: string | null | undefined,
): TranscriptionBackendType {
  const model = normalizeModelName(modelName);

  if (/^nvidia\/(parakeet|nemotron-speech)/.test(model)) return 'parakeet';
  if (/^nvidia\/canary/.test(model)) return 'canary';
  if (/^[^/]+\/vibevoice-asr(?:-[^/]+)?$/.test(model)) return 'vibevoice_asr';
  return 'whisper';
}

export function supportsExplicitWordTimestampToggle(modelName: string | null | undefined): boolean {
  return detectTranscriptionBackendType(modelName) !== 'vibevoice_asr';
}
