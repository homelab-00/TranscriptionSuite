/**
 * useLanguages — loading-state semantics regression (gh-102)
 *
 * Verifies the hook reports `loading=true` while the actual /transcribe/languages
 * fetch is in flight, both on first mount and on cache-miss key swap. The earlier
 * implementation used a static `placeholderData`, which made react-query report
 * `isLoading=false` immediately — letting SessionView's snap-to-valid effect
 * run against placeholder data and silently overwrite a user's persisted
 * Spanish selection on Canary models.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';

import { useLanguages } from '../useLanguages';
import { apiClient } from '../../api/client';

vi.mock('../../api/client', () => ({
  apiClient: {
    getLanguages: vi.fn(),
  },
}));

const mockedGetLanguages = apiClient.getLanguages as unknown as ReturnType<typeof vi.fn>;

function makeWrapper() {
  // Fresh QueryClient per test to keep cache state isolated.
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useLanguages — loading state (gh-102)', () => {
  beforeEach(() => {
    mockedGetLanguages.mockReset();
  });

  it('returns loading=true on first mount until the fetch resolves', async () => {
    let resolveFetch!: (value: unknown) => void;
    mockedGetLanguages.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const { result } = renderHook(() => useLanguages('nvidia/canary-1b-v2'), {
      wrapper: makeWrapper(),
    });

    expect(result.current.loading).toBe(true);
    // Fallback list still surfaces the synthetic "Auto Detect" entry so
    // consumers don't render "no languages" briefly.
    expect(result.current.languages.map((l) => l.name)).toContain('Auto Detect');

    resolveFetch({
      languages: { en: 'English', es: 'Spanish' },
      backend_type: 'canary',
      auto_detect: false,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.languages.map((l) => l.name)).toContain('Spanish');
  });

  it('returns loading=true after the first fetch errors before any data has loaded', async () => {
    // Regression: react-query's `isLoading` and `isPending` both go false
    // after an error with no prior data, but `data` stays undefined. If
    // `loading` were derived from those flags alone, SessionView's snap
    // effect would run against PLACEHOLDER_LANGUAGES on a network blip and
    // silently rewrite a persisted Canary language. Anchor `loading` to
    // `data === undefined` instead.
    mockedGetLanguages.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useLanguages('nvidia/canary-1b-v2'), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());

    expect(result.current.loading).toBe(true);
    // Fallback list still surfaces the synthetic "Auto Detect" entry.
    expect(result.current.languages.map((l) => l.name)).toEqual(['Auto Detect']);
  });

  it('returns loading=true on cache-miss key swap (model change to a new backend family)', async () => {
    // First fetch: whisper. Resolve immediately.
    mockedGetLanguages.mockResolvedValueOnce({
      languages: { en: 'English' },
      backend_type: 'whisper',
      auto_detect: true,
    });

    const { result, rerender } = renderHook(
      ({ model }: { model: string | null }) => useLanguages(model),
      {
        wrapper: makeWrapper(),
        initialProps: { model: 'openai/whisper-large-v3' },
      },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.languages.map((l) => l.name)).toContain('English');

    // Second fetch: canary. Hold it in flight to observe loading=true.
    let resolveSecond!: (value: unknown) => void;
    mockedGetLanguages.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
    );

    rerender({ model: 'nvidia/canary-1b-v2' });

    // The cache for the canary backend key has no real data yet.
    expect(result.current.loading).toBe(true);

    resolveSecond({
      languages: { en: 'English', es: 'Spanish' },
      backend_type: 'canary',
      auto_detect: false,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.languages.map((l) => l.name)).toContain('Spanish');
  });
});
