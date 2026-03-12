import { useEffect, useRef, useMemo } from 'react';
import type { TranscriptionSegment, TranscriptionWord } from '../api/types';

/** Classes that constitute the "active word" highlight. */
const ACTIVE_CLASSES = ['bg-accent-cyan/30', 'text-accent-cyan', 'font-medium'] as const;

/**
 * Binary search for the word whose time range contains `time`.
 * Returns the flat index, or -1 if `time` falls in a gap / outside all words.
 */
export function findActiveWordIndex(words: TranscriptionWord[], time: number): number {
  if (words.length === 0) return -1;
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const w = words[mid];
    if (time < w.start) {
      hi = mid - 1;
    } else if (time >= w.end) {
      lo = mid + 1;
    } else {
      return mid; // time >= w.start && time < w.end
    }
  }
  return -1;
}

/**
 * Scroll the active word into the visible area of its scroll container,
 * but only when the word drifts outside a 30%-70% vertical dead zone.
 */
function scrollToWord(wordEl: HTMLElement, scrollContainer: HTMLElement): void {
  const containerRect = scrollContainer.getBoundingClientRect();
  const wordRect = wordEl.getBoundingClientRect();
  const cushionTop = containerRect.top + containerRect.height * 0.3;
  const cushionBottom = containerRect.top + containerRect.height * 0.7;
  if (wordRect.top < cushionTop || wordRect.bottom > cushionBottom) {
    wordEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

interface UseWordHighlighterOptions {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  segments: TranscriptionSegment[];
  isPlaying: boolean;
  containerRef: React.RefObject<HTMLElement | null>;
  enabled?: boolean;
}

/**
 * Smooth word-level highlighting driven by requestAnimationFrame (~60 fps).
 *
 * Operates entirely outside React's render cycle: finds the active word via
 * binary search then toggles CSS classes directly on the DOM element identified
 * by its `data-word-idx` attribute.
 */
export function useWordHighlighter({
  audioRef,
  segments,
  isPlaying,
  containerRef,
  enabled = true,
}: UseWordHighlighterOptions): void {
  const flatWords = useMemo(() => {
    const words: TranscriptionWord[] = [];
    for (const seg of segments) {
      if (seg.words) {
        for (const w of seg.words) {
          words.push(w);
        }
      }
    }
    return words;
  }, [segments]);

  const prevIdxRef = useRef<number>(-1);
  const rafIdRef = useRef<number>(0);

  useEffect(() => {
    const audio = audioRef.current;
    const container = containerRef.current;

    if (!enabled || !isPlaying || flatWords.length === 0 || !audio || !container) {
      cancelAnimationFrame(rafIdRef.current);
      // Remove lingering highlight
      if (container && prevIdxRef.current >= 0) {
        const prevEl = container.querySelector(
          `[data-word-idx="${prevIdxRef.current}"]`,
        ) as HTMLElement | null;
        if (prevEl) prevEl.classList.remove(...ACTIVE_CLASSES);
      }
      prevIdxRef.current = -1;
      return;
    }

    function tick() {
      const time = audio!.currentTime;
      const idx = findActiveWordIndex(flatWords, time);

      if (idx !== prevIdxRef.current) {
        // Remove highlight from previous word
        if (prevIdxRef.current >= 0) {
          const prevEl = container!.querySelector(
            `[data-word-idx="${prevIdxRef.current}"]`,
          ) as HTMLElement | null;
          if (prevEl) prevEl.classList.remove(...ACTIVE_CLASSES);
        }

        // Highlight new word
        if (idx >= 0) {
          const newEl = container!.querySelector(`[data-word-idx="${idx}"]`) as HTMLElement | null;
          if (newEl) {
            newEl.classList.add(...ACTIVE_CLASSES);
            scrollToWord(newEl, container!);
          }
        }

        prevIdxRef.current = idx;
      }

      rafIdRef.current = requestAnimationFrame(tick);
    }

    rafIdRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafIdRef.current);
    };
  }, [isPlaying, enabled, flatWords, audioRef, containerRef]);
}
