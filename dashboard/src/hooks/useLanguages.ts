/**
 * useLanguages — fetches the supported transcription languages from the server.
 *
 * The server returns different language sets depending on the active model
 * backend (whisper / parakeet / canary).  Accepts the current model name so
 * it can re-fetch when the model changes.
 */

import { useState, useEffect, useRef } from 'react';
import { apiClient } from '../api/client';

export interface LanguagesState {
  /** Array of {code, name} pairs, with "auto" prepended */
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
  error: string | null;
}

/** Per-backend cache so we don't re-fetch after a model round-trip. */
const cache = new Map<string, Array<{ code: string; name: string }>>();

/** Derive a stable cache key from the model name (backend type). */
function cacheKey(model: string | null | undefined): string {
  const m = (model ?? '').trim().toLowerCase();
  if (/^nvidia\/(parakeet|nemotron-speech)/.test(m)) return 'parakeet';
  if (/^nvidia\/canary/.test(m)) return 'canary';
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
  const cached = cache.get(key) ?? null;

  const [languages, setLanguages] = useState<Array<{ code: string; name: string }>>(
    cached ?? [{ code: 'auto', name: 'Auto Detect' }],
  );
  const [loading, setLoading] = useState(cached === null);
  const [error, setError] = useState<string | null>(null);
  const prevKeyRef = useRef(key);

  useEffect(() => {
    // If backend type changed, reset to cached value (or placeholder)
    if (prevKeyRef.current !== key) {
      prevKeyRef.current = key;
      const hit = cache.get(key);
      if (hit) {
        setLanguages(hit);
        setLoading(false);
        return;
      }
      // Will fetch below
      setLoading(true);
    }

    // Already cached for this backend — nothing to do
    if (cache.has(key)) return;

    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.getLanguages();
        const list = buildList(data.languages);
        cache.set(key, list);
        if (!cancelled) {
          setLanguages(list);
          setLoading(false);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load languages');
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [key]);

  return { languages, loading, error };
}
