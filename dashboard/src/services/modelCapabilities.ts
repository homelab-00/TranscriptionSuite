/**
 * Client-side model capability checks.
 * Mirrors server/backend/core/stt/capabilities.py logic.
 */

const PARAKEET_PATTERN = /^nvidia\/(parakeet|nemotron-speech)/i;

/**
 * The 25 languages supported by nvidia/parakeet-tdt-0.6b-v3.
 * Source: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
 */
const PARAKEET_LANGUAGES: ReadonlySet<string> = new Set([
  'Bulgarian',
  'Croatian',
  'Czech',
  'Danish',
  'Dutch',
  'English',
  'Estonian',
  'Finnish',
  'French',
  'German',
  'Greek',
  'Hungarian',
  'Italian',
  'Latvian',
  'Lithuanian',
  'Maltese',
  'Polish',
  'Portuguese',
  'Romanian',
  'Russian',
  'Slovak',
  'Slovenian',
  'Spanish',
  'Swedish',
  'Ukrainian',
]);

/**
 * Returns true if the model is an NVIDIA Parakeet / NeMo ASR model.
 */
export function isParakeetModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return PARAKEET_PATTERN.test(name);
}

/**
 * Filter a language list to only those supported by the given model.
 * Whisper models support everything; Parakeet models support 25 languages.
 * The "Auto Detect" entry is always preserved.
 */
export function filterLanguagesForModel(
  languages: string[],
  modelName: string | null | undefined,
): string[] {
  if (!isParakeetModel(modelName)) return languages;
  return languages.filter((l) => l === 'Auto Detect' || PARAKEET_LANGUAGES.has(l));
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
