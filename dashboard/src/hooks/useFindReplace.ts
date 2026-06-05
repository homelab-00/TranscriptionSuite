/**
 * useFindReplace — find/replace state for a plain <textarea>.
 *
 * Wraps the pure findReplaceEngine and drives the textarea's native selection
 * to highlight the current match. Selection is only moved while focus is NOT in
 * the textarea (i.e. focus is in the find/replace inputs), so live navigation
 * never disturbs direct editing — the match shows in the browser's
 * inactive-selection color (design D6 caveat).
 */

import { useState, useCallback, useEffect, useMemo, useRef, type RefObject } from 'react';
import {
  computeMatches,
  replaceCurrent,
  replaceAll,
  type Match,
} from '../services/findReplaceEngine';

export type FindReplaceMode = 'find' | 'replace';

export interface UseFindReplaceArgs {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  /** Current editor text. */
  value: string;
  /** Commit a replace result back to the editor. */
  onChange: (next: string) => void;
}

export interface UseFindReplaceState {
  isOpen: boolean;
  mode: FindReplaceMode;
  query: string;
  replacement: string;
  caseSensitive: boolean;
  matchCount: number;
  /** 0-based index of the active match; UI shows `currentIndex + 1` / `matchCount`. */
  currentIndex: number;
  open: (mode: FindReplaceMode) => void;
  close: () => void;
  setQuery: (q: string) => void;
  setReplacement: (r: string) => void;
  toggleCaseSensitive: () => void;
  next: () => void;
  prev: () => void;
  replaceCurrentMatch: () => void;
  replaceAllMatches: () => void;
}

export function useFindReplace({
  textareaRef,
  value,
  onChange,
}: UseFindReplaceArgs): UseFindReplaceState {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<FindReplaceMode>('find');
  const [query, setQuery] = useState('');
  const [replacement, setReplacement] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const matches = useMemo<Match[]>(
    () => computeMatches(value, query, { caseSensitive }),
    [value, query, caseSensitive],
  );
  const matchCount = matches.length;

  // Always-current matches for stable callbacks that must read the latest set.
  const matchesRef = useRef<Match[]>(matches);
  matchesRef.current = matches;

  // Set by replaceCurrentMatch to the offset just past the inserted replacement;
  // consumed once matches recompute to advance to the next real match.
  const pendingAnchorRef = useRef<number | null>(null);

  const selectIndex = useCallback(
    (index: number) => {
      const ta = textareaRef.current;
      const match = matchesRef.current[index];
      if (!ta || !match) return;
      ta.setSelectionRange(match.start, match.end);
      // Best-effort scroll-into-view without stealing focus (proportional).
      const len = ta.value.length;
      if (len > 0 && ta.scrollHeight > ta.clientHeight) {
        const ratio = match.start / len;
        ta.scrollTop = Math.max(0, ratio * (ta.scrollHeight - ta.clientHeight));
      }
    },
    [textareaRef],
  );

  // Clamp the active index when the match set shrinks (e.g. text edited).
  useEffect(() => {
    if (currentIndex > matchCount - 1) {
      setCurrentIndex(matchCount > 0 ? matchCount - 1 : 0);
    }
  }, [matchCount, currentIndex]);

  // A new search (query or case toggle) restarts at the first match.
  useEffect(() => {
    setCurrentIndex(0);
  }, [query, caseSensitive]);

  // After a single replace, jump to the first match at/after the inserted
  // replacement so the just-inserted text is never re-matched — this guarantees
  // forward progress even when the replacement contains the query.
  useEffect(() => {
    if (pendingAnchorRef.current === null) return;
    const anchor = pendingAnchorRef.current;
    pendingAnchorRef.current = null;
    if (matches.length === 0) {
      setCurrentIndex(0);
      return;
    }
    const idx = matches.findIndex((m) => m.start >= anchor);
    setCurrentIndex(idx === -1 ? 0 : idx);
  }, [matches]);

  // Keep the textarea selection on the active match — but never while the user
  // is typing in the textarea itself (focus there → leave their caret alone).
  useEffect(() => {
    if (!isOpen) return;
    const ta = textareaRef.current;
    if (!ta || document.activeElement === ta) return;
    if (matchesRef.current.length === 0) return;
    selectIndex(currentIndex);
  }, [currentIndex, matches, isOpen, selectIndex, textareaRef]);

  const open = useCallback((nextMode: FindReplaceMode) => {
    setMode(nextMode);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    textareaRef.current?.focus();
  }, [textareaRef]);

  const toggleCaseSensitive = useCallback(() => setCaseSensitive((v) => !v), []);

  const next = useCallback(() => {
    const count = matchesRef.current.length;
    if (count === 0) return;
    setCurrentIndex((idx) => (idx + 1) % count);
  }, []);

  const prev = useCallback(() => {
    const count = matchesRef.current.length;
    if (count === 0) return;
    setCurrentIndex((idx) => (idx - 1 + count) % count);
  }, []);

  const replaceCurrentMatch = useCallback(() => {
    const match = matchesRef.current[currentIndex];
    if (!match) return;
    // Remember where to resume so the inserted replacement isn't re-matched.
    pendingAnchorRef.current = match.start + replacement.length;
    onChange(replaceCurrent(value, match, replacement));
  }, [currentIndex, value, replacement, onChange]);

  const replaceAllMatches = useCallback(() => {
    const result = replaceAll(value, query, replacement, { caseSensitive });
    if (result.count > 0) onChange(result.text);
  }, [value, query, replacement, caseSensitive, onChange]);

  return {
    isOpen,
    mode,
    query,
    replacement,
    caseSensitive,
    matchCount,
    currentIndex,
    open,
    close,
    setQuery,
    setReplacement,
    toggleCaseSensitive,
    next,
    prev,
    replaceCurrentMatch,
    replaceAllMatches,
  };
}
