/**
 * useLanguages — fetches the supported transcription languages from the server.
 * Caches the result for the session (languages don't change at runtime).
 */

import { useState, useEffect } from 'react';
import { apiClient } from '../api/client';

export interface LanguagesState {
  /** Array of {code, name} pairs, with "auto" prepended */
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
  error: string | null;
}

let cachedLanguages: Array<{ code: string; name: string }> | null = null;

export function useLanguages(): LanguagesState {
  const [languages, setLanguages] = useState<Array<{ code: string; name: string }>>(
    cachedLanguages ?? [{ code: 'auto', name: 'Auto Detect' }],
  );
  const [loading, setLoading] = useState(cachedLanguages === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cachedLanguages) return; // Already fetched

    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.getLanguages();
        const list: Array<{ code: string; name: string }> = [
          { code: 'auto', name: 'Auto Detect' },
          ...Object.entries(data.languages).map(([code, name]) => ({ code, name })),
        ];
        cachedLanguages = list;
        if (!cancelled) {
          setLanguages(list);
          setLoading(false);
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
  }, []);

  return { languages, loading, error };
}
