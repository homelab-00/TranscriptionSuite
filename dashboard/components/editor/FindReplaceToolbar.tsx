/**
 * FindReplaceToolbar — floating control for FindReplaceTextEditor.
 *
 * Collapsed: a single search-icon button (top-right). Open: a compact find bar
 * (query input + n/total counter + prev/next + case toggle + close); a chevron
 * expands the replace row (replacement input + Replace + Replace all). Driven
 * entirely by a useFindReplace state object owned by the parent editor.
 */

import { useEffect, useRef, type KeyboardEvent } from 'react';
import { Search, X, ArrowUp, ArrowDown, ChevronDown, ChevronUp } from 'lucide-react';
import type { UseFindReplaceState } from '../../src/hooks/useFindReplace';

interface FindReplaceToolbarProps {
  state: UseFindReplaceState;
}

const ICON_BTN =
  'flex h-6 w-6 items-center justify-center rounded text-slate-300 transition hover:bg-white/10 hover:text-white disabled:opacity-40';
const INPUT =
  'h-6 rounded border border-white/10 bg-black/40 px-2 text-xs text-slate-100 placeholder-slate-500 outline-none focus:border-sky-400/60';

export function FindReplaceToolbar({ state }: FindReplaceToolbarProps) {
  const queryInputRef = useRef<HTMLInputElement>(null);

  // Focus the query field whenever the bar opens (Ctrl+F / Ctrl+H / icon click).
  useEffect(() => {
    if (state.isOpen) queryInputRef.current?.focus();
  }, [state.isOpen]);

  if (!state.isOpen) {
    return (
      <button
        type="button"
        onClick={() => state.open('find')}
        className="absolute top-2 right-2 z-10 flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-black/50 text-slate-300 backdrop-blur transition hover:bg-white/10 hover:text-white"
        aria-label="Find and replace"
        title="Find (Ctrl+F)"
      >
        <Search className="h-4 w-4" />
      </button>
    );
  }

  const counter = state.matchCount > 0 ? `${state.currentIndex + 1}/${state.matchCount}` : '0/0';

  const onFindKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      if (e.shiftKey) state.prev();
      else state.next();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      state.close();
    }
  };

  const onReplaceKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      state.replaceCurrentMatch();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      state.close();
    }
  };

  return (
    <div
      role="search"
      className="absolute top-2 right-2 z-10 flex flex-col gap-1 rounded-lg border border-white/10 bg-black/70 p-1.5 shadow-lg backdrop-blur"
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => state.open(state.mode === 'replace' ? 'find' : 'replace')}
          className={ICON_BTN}
          aria-label={state.mode === 'replace' ? 'Hide replace' : 'Show replace'}
          aria-expanded={state.mode === 'replace'}
          title="Toggle replace (Ctrl+H)"
        >
          {state.mode === 'replace' ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>
        <input
          ref={queryInputRef}
          type="text"
          value={state.query}
          onChange={(e) => state.setQuery(e.target.value)}
          onKeyDown={onFindKeyDown}
          placeholder="Find"
          aria-label="Find"
          className={`${INPUT} w-32`}
        />
        <span className="min-w-[2.5rem] text-center text-[11px] text-slate-400 tabular-nums">
          {counter}
        </span>
        <button
          type="button"
          onClick={state.prev}
          disabled={state.matchCount === 0}
          className={ICON_BTN}
          aria-label="Previous match"
          title="Previous (Shift+Enter)"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={state.next}
          disabled={state.matchCount === 0}
          className={ICON_BTN}
          aria-label="Next match"
          title="Next (Enter)"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={state.toggleCaseSensitive}
          aria-pressed={state.caseSensitive}
          className={`flex h-6 w-6 items-center justify-center rounded text-xs font-semibold transition ${
            state.caseSensitive
              ? 'bg-sky-500/30 text-sky-200'
              : 'text-slate-400 hover:bg-white/10 hover:text-white'
          }`}
          aria-label="Match case"
          title="Match case"
        >
          Aa
        </button>
        <button
          type="button"
          onClick={state.close}
          className={ICON_BTN}
          aria-label="Close find"
          title="Close (Esc)"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {state.mode === 'replace' && (
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={state.replacement}
            onChange={(e) => state.setReplacement(e.target.value)}
            onKeyDown={onReplaceKeyDown}
            placeholder="Replace"
            aria-label="Replace"
            className={`${INPUT} w-32`}
          />
          <button
            type="button"
            onClick={state.replaceCurrentMatch}
            disabled={state.matchCount === 0}
            className="h-6 rounded bg-white/10 px-2 text-[11px] text-slate-200 transition hover:bg-white/20 disabled:opacity-40"
            aria-label="Replace match"
            title="Replace (Enter)"
          >
            Replace
          </button>
          <button
            type="button"
            onClick={state.replaceAllMatches}
            disabled={state.matchCount === 0}
            className="h-6 rounded bg-white/10 px-2 text-[11px] text-slate-200 transition hover:bg-white/20 disabled:opacity-40"
            aria-label="Replace all"
            title="Replace all"
          >
            All
          </button>
        </div>
      )}
    </div>
  );
}
