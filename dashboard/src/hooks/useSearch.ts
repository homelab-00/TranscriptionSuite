/**
 * useSearch — performs unified search against the server.
 * Only triggers when the query is non-empty and changes.
 */

import { useState, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
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
  const [params, setParams] = useState<{ query: string; options?: SearchOptions } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', params],
    queryFn: () => apiClient.search(params!.query, params!.options),
    enabled: !!params?.query.trim(),
  });

  const search = useCallback(
    (query: string, options?: SearchOptions) => {
      if (timerRef.current) clearTimeout(timerRef.current);

      if (!query.trim()) {
        setParams(null);
        return;
      }

      timerRef.current = setTimeout(() => {
        setParams({ query, options });
      }, debounceMs);
    },
    [debounceMs],
  );

  return {
    results: data?.results ?? [],
    count: data?.count ?? 0,
    loading: isLoading && !!params?.query.trim(),
    error: error instanceof Error ? error.message : error ? 'Search failed' : null,
    search,
  };
}
