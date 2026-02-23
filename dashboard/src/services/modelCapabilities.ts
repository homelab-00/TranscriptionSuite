/**
 * Client-side model capability checks.
 * Mirrors server/backend/core/stt/capabilities.py logic.
 */

const PARAKEET_PATTERN = /^nvidia\/(parakeet|nemotron-speech)/i;

/**
 * Returns true if the model is an NVIDIA Parakeet / NeMo ASR model.
 */
export function isParakeetModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return PARAKEET_PATTERN.test(name);
}

/**
 * Returns true if the given model name supports Whisper's translate task
 * (translate any language → English).
 *
 * Conservative guard: rejects Parakeet, turbo, .en, and distil-large-v3 models.
 */
export function supportsTranslation(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim().toLowerCase();
  if (!name) return true; // unknown model → allow

  if (isParakeetModel(modelName)) return false;
  if (name.includes('turbo')) return false;
  if (name.endsWith('.en')) return false;
  if (name.includes('distil-large-v3')) return false;

  return true;
}
