/**
 * useLanguages — fetches the supported transcription languages from the server.
 *
 * The server returns different language sets depending on the active model
 * backend (whisper / parakeet / canary / vibevoice_asr). Accepts the current model name so
 * it can re-fetch when the model changes.
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import {
  detectTranscriptionBackendType,
  type TranscriptionBackendType,
} from '../utils/transcriptionBackend';

export interface LanguagesState {
  /** Array of {code, name} pairs, with "auto" prepended */
  languages: Array<{ code: string; name: string }>;
  /** Active backend family reported by the server (if available) */
  backendType: TranscriptionBackendType | null;
  loading: boolean;
  error: string | null;
}

interface LanguagesQueryData {
  languages: Array<{ code: string; name: string }>;
  backendType: TranscriptionBackendType | null;
}

const PLACEHOLDER_LANGUAGES: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
];

/** Derive a stable cache key from the model name (backend type). */
function cacheKey(model: string | null | undefined): string {
  return detectTranscriptionBackendType(model);
}

/**
 * Sort language entries: English first, then alphabetical by name.
 * Auto Detect is always prepended separately.
 */
function buildList(raw: Record<string, string>): Array<{ code: string; name: string }> {
  const entries = Object.entries(raw)
    .map(([code, name]) => ({ code, name }))
    .sort((a, b) => {
      if (a.name === 'English') return -1;
      if (b.name === 'English') return 1;
      return a.name.localeCompare(b.name);
    });
  return [{ code: 'auto', name: 'Auto Detect' }, ...entries];
}

export function useLanguages(modelName?: string | null): LanguagesState {
  const key = cacheKey(modelName);

  // No `placeholderData` (see GitHub issue 102). With a static placeholder,
  // React Query reports `isLoading=false` while the real fetch is still in
  // flight (placeholder is treated as resolved data). The SessionView snap
  // effect would then run against a one-element placeholder list and
  // silently rewrite a user's persisted Spanish to English on Canary. We
  // instead expose an honest `loading` flag and let callers fall back to
  // PLACEHOLDER_LANGUAGES via `data?.languages ?? ...` when they need a
  // non-empty list during the initial load.
  const { data, error } = useQuery({
    queryKey: ['languages', key],
    queryFn: async () => {
      const data = await apiClient.getLanguages();
      return {
        languages: buildList(data.languages),
        backendType: data.backend_type ?? null,
      } satisfies LanguagesQueryData;
    },
    staleTime: 60_000,
  });

  return {
    languages: data?.languages ?? PLACEHOLDER_LANGUAGES,
    backendType: data?.backendType ?? null,
    // `data === undefined` is the only honest "no real server data yet"
    // signal: it covers initial fetch, cache-miss key swap, and the
    // post-error-before-any-data state (where react-query sets
    // status='error' with isPending=false / isLoading=false). Earlier
    // versions OR'd `isLoading || isPending`, which still reported
    // `loading=false` after an error blip during the very first fetch and
    // let the SessionView snap effect run against `PLACEHOLDER_LANGUAGES`.
    loading: data === undefined,
    error: error instanceof Error ? error.message : error ? 'Failed to load languages' : null,
  };
}
