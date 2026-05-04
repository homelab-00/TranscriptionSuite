/**
 * useRecordingAliases — fetch + mutate per-recording speaker aliases.
 *
 * Issue #104, Stories 4.3 / 4.4. Follows the same hand-rolled state
 * pattern as `useRecording` (no @tanstack/react-query for symmetry).
 *
 * Single-source-of-truth invariant (FR22, R-EL3):
 *   - The hook is the SINGLE owner of the alias map for a recording.
 *   - All consumers (transcript view, downloads, etc.) read from this
 *     hook's `aliasMap` so renaming `spk_0` → "Elena" updates ALL 30
 *     turns in the same render pass.
 *   - The stored transcript (`segments.speaker` raw values) is never
 *     mutated — alias substitution happens at render time only.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import type { AliasMap } from '../utils/aliasSubstitution';

export interface AliasEntry {
  speaker_id: string;
  alias_name: string;
}

export interface RecordingAliasesState {
  aliases: AliasEntry[];
  /** speaker_id → alias_name (convenience for buildSpeakerLabelMap consumers). */
  aliasMap: AliasMap;
  loading: boolean;
  error: string | null;
  /** Refetch from the server. */
  refresh: () => void;
  /**
   * Full-replace upsert. Aliases NOT in `next` are deleted server-side.
   * Empty alias_name strings (after trim) clear the alias for that
   * speaker_id. Resolves with the new state once committed.
   */
  setAliases: (next: AliasEntry[]) => Promise<AliasEntry[]>;
}

function toMap(aliases: AliasEntry[]): AliasMap {
  const m: AliasMap = {};
  for (const a of aliases) m[a.speaker_id] = a.alias_name;
  return m;
}

export function useRecordingAliases(recordingId: number | null): RecordingAliasesState {
  const [aliases, setAliasesState] = useState<AliasEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (recordingId === null || !Number.isFinite(recordingId) || recordingId <= 0) {
      setAliasesState([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.getRecordingAliases(recordingId);
      setAliasesState(resp.aliases ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load aliases');
      setAliasesState([]);
    } finally {
      setLoading(false);
    }
  }, [recordingId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const setAliases = useCallback(
    async (next: AliasEntry[]): Promise<AliasEntry[]> => {
      if (recordingId === null) return [];
      // Optimistic update — reverted on error
      const previous = aliases;
      setAliasesState(next);
      try {
        const resp = await apiClient.setRecordingAliases(
          recordingId,
          // Trim whitespace; preserve everything else verbatim (R-EL3)
          next.map((a) => ({ speaker_id: a.speaker_id, alias_name: a.alias_name.trim() })),
        );
        setAliasesState(resp.aliases ?? []);
        return resp.aliases ?? [];
      } catch (err) {
        setAliasesState(previous);
        setError(err instanceof Error ? err.message : 'Failed to update aliases');
        throw err;
      }
    },
    [aliases, recordingId],
  );

  return {
    aliases,
    aliasMap: toMap(aliases),
    loading,
    error,
    refresh: fetch,
    setAliases,
  };
}
