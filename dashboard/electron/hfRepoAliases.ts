/**
 * Some models are configured under their ModelScope id but are downloaded from
 * HuggingFace under a different org. The HF cache dir is derived from the HF repo
 * id, so any cache-path computation must resolve the alias first.
 *
 * Mirrors _MODELSCOPE_TO_HF_REPO in
 * server/backend/core/stt/backends/sensevoice_backend.py — keep the two in sync.
 */
export const MODELSCOPE_TO_HF_REPO: Readonly<Record<string, string>> = Object.freeze({
  'iic/SenseVoiceSmall': 'FunAudioLLM/SenseVoiceSmall',
});

/**
 * Resolve a configured model id to the HuggingFace repo id it is cached under.
 *
 * HuggingFace repo ids are case-sensitive (the cache dir mirrors the exact repo
 * id), so this uses an exact-match lookup — it deliberately does NOT lowercase
 * the id. Unknown ids pass through unchanged.
 */
export function resolveHfRepoId(modelId: string): string {
  const trimmed = modelId.trim();
  return MODELSCOPE_TO_HF_REPO[trimmed] ?? trimmed;
}

/**
 * HuggingFace cache-dir name for a configured model id:
 * "org/name" -> "models--org--name". Resolves the ModelScope->HF alias first so
 * the derived directory matches what huggingface_hub actually writes on disk.
 */
export function hfCacheDirName(modelId: string): string {
  const repoId = resolveHfRepoId(modelId);
  return `models--${repoId.replace(/\//g, '--')}`;
}
