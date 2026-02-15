/**
 * useSearch — performs unified search against the server.
 * Only triggers when the query is non-empty and changes.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { SearchResult } from '../api/types';

export interface SearchOptions {
  fuzzy?: boolean;
  startDate?: string;
  endDate?: string;
  limit?: number;
}

export interface SearchState {
  results: SearchResult[];
  count: number;
  loading: boolean;
  error: string | null;
  /** Manually trigger the search (e.g. on enter key) */
  search: (query: string, options?: SearchOptions) => void;
}

export function useSearch(debounceMs = 400): SearchState {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const search = useCallback(
    (query: string, options?: SearchOptions) => {
      // Clear any pending debounce
      if (timerRef.current) clearTimeout(timerRef.current);

      if (!query.trim()) {
        setResults([]);
        setCount(0);
        setLoading(false);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);

      timerRef.current = setTimeout(async () => {
        // Abort previous in-flight request
        if (abortRef.current) abortRef.current.abort();
        abortRef.current = new AbortController();

        try {
          const data = await apiClient.search(query, options);
          setResults(data.results);
          setCount(data.count);
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          setError(err instanceof Error ? err.message : 'Search failed');
          setResults([]);
          setCount(0);
        } finally {
          setLoading(false);
        }
      }, debounceMs);
    },
    [debounceMs],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  return { results, count, loading, error, search };
}
