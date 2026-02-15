/**
 * Client-side model capability checks.
 * Mirrors server/backend/core/stt/capabilities.py logic.
 */

/**
 * Returns true if the given model name supports Whisper's translate task
 * (translate any language → English).
 *
 * Conservative guard: rejects turbo, .en, and distil-large-v3 models.
 */
export function supportsTranslation(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim().toLowerCase();
  if (!name) return true; // unknown model → allow

  if (name.includes('turbo')) return false;
  if (name.endsWith('.en')) return false;
  if (name.includes('distil-large-v3')) return false;

  return true;
}
