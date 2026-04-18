/**
 * Client-side model capability checks.
 * Mirrors server/backend/core/stt/capabilities.py logic.
 */

const PARAKEET_PATTERN = /^nvidia\/(parakeet|nemotron-speech)/i;
const CANARY_PATTERN = /^nvidia\/canary/i;
const VIBEVOICE_ASR_PATTERN = /^[^/]+\/vibevoice-asr(?:-[^/]+)?$/i;
const WHISPERCPP_PATTERN = /(?:(?:^|\/)ggml-.*\.bin$|\.gguf$)/i;
// MLX Parakeet must be checked before the general mlx-community prefix.
const MLX_PARAKEET_PATTERN = /^mlx-community\/parakeet/i;
// Matches community Canary MLX ports: eelcor/canary-1b-v2-mlx, Mediform/canary-1b-v2-mlx-q8, qfuxa/canary-mlx, etc.
const MLX_CANARY_PATTERN = /^[^/]+\/canary[^/]*-mlx/i;
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
  return MLX_PATTERN.test(name) || MLX_CANARY_PATTERN.test(name);
}

/**
 * Returns true if the model is an MLX-accelerated Parakeet-TDT model.
 * 25 EU languages (auto-detected from audio); no translation task; no live mode.
 */
export function isMLXParakeetModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return MLX_PARAKEET_PATTERN.test(name);
}

/**
 * Returns true if the model is an MLX-accelerated Canary model (community port).
 * 25 EU languages; native P&C; no translation; no live mode.
 */
export function isMLXCanaryModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return MLX_CANARY_PATTERN.test(name);
}

/**
 * Returns true if the model should run on the faster-whisper/Whisper backend.
 * Unknown or empty values are treated as Whisper-compatible defaults.
 */
export function isWhisperModel(modelName: string | null | undefined): boolean {
  return (
    !isNemoModel(modelName) &&
    !isVibeVoiceASRModel(modelName) &&
    !isWhisperCppModel(modelName) &&
    !isMLXModel(modelName)
  );
}

/**
 * Returns true if the model is a VibeVoice-ASR backend variant.
 */
export function isVibeVoiceASRModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return VIBEVOICE_ASR_PATTERN.test(name);
}

/**
 * Returns true if the model is a GGML model for the whisper.cpp sidecar backend.
 */
export function isWhisperCppModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return WHISPERCPP_PATTERN.test(name);
}

/**
 * Returns true if the model supports pyannote speaker diarization.
 * whisper.cpp models lack pyannote integration; VibeVoice uses its own
 * built-in diarization rather than pyannote.
 */
export function supportsDiarization(modelName: string | null | undefined): boolean {
  if (isWhisperCppModel(modelName)) return false;
  if (isVibeVoiceASRModel(modelName)) return false;
  return true;
}

/**
 * Returns true if the model is an English-only Whisper variant (name ends with `.en`).
 */
export function isEnglishOnlyWhisperModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim().toLowerCase();
  return name.endsWith('.en');
}

/**
 * Pick a sensible language when the current selection is no longer valid
 * (e.g. the user switched to a Canary model and the previous selection was
 * "Auto Detect"). Prefers "English" — every NeMo/Whisper model we ship with
 * has English — and falls back to the first option, or "Auto Detect" if the
 * options list is empty.
 */
export function pickDefaultLanguage(options: string[]): string {
  if (options.includes('English')) return 'English';
  return options[0] ?? 'Auto Detect';
}

/**
 * Returns true if the model actually supports "Auto Detect" for the source
 * language. Canary models require an explicit `source_lang` and have no
 * built-in language detection — giving them an "Auto Detect" option would
 * silently coerce to English and translate every non-English audio to English
 * (see GitHub issue #81).
 *
 * Mirrors `supports_auto_detect` in server/backend/core/stt/capabilities.py.
 */
export function supportsAutoDetect(modelName: string | null | undefined): boolean {
  if (isCanaryModel(modelName)) return false;
  if (isMLXCanaryModel(modelName)) return false;
  return true;
}

/**
 * Filter a language list to only those supported by the given model.
 * Whisper models support everything; NeMo models (Parakeet, Canary) support 25 languages.
 * English-only (.en) Whisper models restrict to English only.
 * "Auto Detect" is kept only for models that actually support auto-detection
 * (see `supportsAutoDetect`).
 */
export function filterLanguagesForModel(
  languages: string[],
  modelName: string | null | undefined,
): string[] {
  const keepAutoDetect = (l: string): boolean =>
    l !== 'Auto Detect' || supportsAutoDetect(modelName);

  if (isVibeVoiceASRModel(modelName)) {
    return languages.filter((l) => l === 'Auto Detect');
  }
  if (isMLXParakeetModel(modelName)) {
    // parakeet-mlx exposes no language-hint API; the model auto-detects language from audio
    return languages.filter((l) => l === 'Auto Detect');
  }
  if (isEnglishOnlyWhisperModel(modelName)) {
    return languages.filter((l) => l === 'English');
  }
  if (isMLXCanaryModel(modelName) || isNemoModel(modelName)) {
    // NVIDIA Canary and MLX Canary: 25 NeMo languages, no Auto Detect (see
    // supportsAutoDetect). NVIDIA Parakeet: 25 NeMo languages, keeps Auto Detect.
    return languages.filter(
      (l) => keepAutoDetect(l) && (l === 'Auto Detect' || NEMO_LANGUAGES.has(l)),
    );
  }
  return languages.filter(keepAutoDetect);
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
  // MLX Parakeet: ASR-only, no translation task
  if (isMLXParakeetModel(modelName)) return false;
  // Canary models support translation (X↔English)
  if (isCanaryModel(modelName)) return true;
  // MLX Canary: ASR-only in the MLX port, no translation task
  if (isMLXCanaryModel(modelName)) return false;
  // VibeVoice-ASR (v1 integration) is ASR+diarization only.
  if (isVibeVoiceASRModel(modelName)) return false;
  if (name.includes('turbo')) return false;
  if (name.endsWith('.en')) return false;

  return true;
}
