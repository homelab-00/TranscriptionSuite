/**
 * Client-side model capability checks.
 * Mirrors server/backend/core/stt/capabilities.py logic.
 */

const PARAKEET_PATTERN = /^nvidia\/(parakeet|nemotron-speech)/i;
const CANARY_PATTERN = /^nvidia\/canary/i;
const VIBEVOICE_ASR_PATTERN = /^[^/]+\/vibevoice-asr(?:-[^/]+)?$/i;
const MLX_PATTERN = /^mlx-community\//i;

/**
 * The 25 European languages supported by NeMo ASR models
 * (nvidia/parakeet-tdt-0.6b-v3 and nvidia/canary-1b-v2).
 */
export const NEMO_LANGUAGES: ReadonlySet<string> = new Set([
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
 * The 24 EU languages available as Canary translation targets (all NeMo languages except English).
 * Shown as a dropdown when Canary is selected with English as the source language.
 */
export const CANARY_TRANSLATION_TARGETS: readonly string[] = [
  'Bulgarian',
  'Croatian',
  'Czech',
  'Danish',
  'Dutch',
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
];

/**
 * Returns true if the model is an NVIDIA Parakeet / NeMo ASR-only model.
 */
export function isParakeetModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return PARAKEET_PATTERN.test(name);
}

/**
 * Returns true if the model is an NVIDIA Canary multitask ASR+translation model.
 */
export function isCanaryModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return CANARY_PATTERN.test(name);
}

/**
 * Returns true if the model is any NVIDIA NeMo model (Parakeet or Canary).
 */
export function isNemoModel(modelName: string | null | undefined): boolean {
  return isParakeetModel(modelName) || isCanaryModel(modelName);
}

/**
 * Returns true if the model runs on the MLX Whisper backend (Apple Silicon).
 * Model IDs in the mlx-community namespace on HuggingFace.
 */
export function isMLXModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return MLX_PATTERN.test(name);
}

/**
 * Returns true if the model should run on the faster-whisper/Whisper backend.
 * Unknown or empty values are treated as Whisper-compatible defaults.
 */
export function isWhisperModel(modelName: string | null | undefined): boolean {
  return !isNemoModel(modelName) && !isVibeVoiceASRModel(modelName) && !isMLXModel(modelName);
}

/**
 * Returns true if the model is a VibeVoice-ASR backend variant.
 */
export function isVibeVoiceASRModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return VIBEVOICE_ASR_PATTERN.test(name);
}

/**
 * Returns true if the model is an English-only Whisper variant (name ends with `.en`).
 */
export function isEnglishOnlyWhisperModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim().toLowerCase();
  return name.endsWith('.en');
}

/**
 * Filter a language list to only those supported by the given model.
 * Whisper models support everything; NeMo models (Parakeet, Canary) support 25 languages.
 * English-only (.en) Whisper models restrict to English only.
 * The "Auto Detect" entry is always preserved for applicable models.
 */
export function filterLanguagesForModel(
  languages: string[],
  modelName: string | null | undefined,
): string[] {
  if (isVibeVoiceASRModel(modelName)) {
    return languages.filter((l) => l === 'Auto Detect');
  }
  if (isEnglishOnlyWhisperModel(modelName)) {
    return languages.filter((l) => l === 'English');
  }
  if (!isNemoModel(modelName)) return languages;
  return languages.filter((l) => l === 'Auto Detect' || NEMO_LANGUAGES.has(l));
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

  // Parakeet models are ASR-only (no translation)
  if (isParakeetModel(modelName)) return false;
  // Canary models support translation (X↔English)
  if (isCanaryModel(modelName)) return true;
  // VibeVoice-ASR (v1 integration) is ASR+diarization only.
  if (isVibeVoiceASRModel(modelName)) return false;
  if (name.includes('turbo')) return false;
  if (name.endsWith('.en')) return false;

  return true;
}
