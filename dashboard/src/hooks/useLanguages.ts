/**
 * useLanguages — fetches the supported transcription languages from the server.
 *
 * The server returns different language sets depending on the active model
 * backend (whisper / parakeet / canary / vibevoice_asr). Accepts the current model name so
 * it can re-fetch when the model changes.
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

export interface LanguagesState {
  /** Array of {code, name} pairs, with "auto" prepended */
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
  error: string | null;
}

const PLACEHOLDER: Array<{ code: string; name: string }> = [{ code: 'auto', name: 'Auto Detect' }];

/** Derive a stable cache key from the model name (backend type). */
function cacheKey(model: string | null | undefined): string {
  const m = (model ?? '').trim().toLowerCase();
  if (/^nvidia\/(parakeet|nemotron-speech)/.test(m)) return 'parakeet';
  if (/^nvidia\/canary/.test(m)) return 'canary';
  if (/^microsoft\/vibevoice-asr$/.test(m)) return 'vibevoice_asr';
  return 'whisper';
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

  const { data, isLoading, error } = useQuery({
    queryKey: ['languages', key],
    queryFn: async () => {
      const data = await apiClient.getLanguages();
      return buildList(data.languages);
    },
    staleTime: Infinity,
    placeholderData: PLACEHOLDER,
  });

  return {
    languages: data ?? PLACEHOLDER,
    loading: isLoading,
    error: error instanceof Error ? error.message : error ? 'Failed to load languages' : null,
  };
}
