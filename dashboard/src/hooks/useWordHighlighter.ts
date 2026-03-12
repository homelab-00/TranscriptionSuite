import { useEffect, useRef, useMemo } from 'react';
import type { TranscriptionSegment, TranscriptionWord } from '../api/types';

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
 * Like findActiveWordIndex, but when time falls in a gap between words,
 * returns the most recently passed word (the "train" stays at the last stop).
 * Only returns -1 when there are no words at all.
 */
function findActiveOrNearestWordIndex(words: TranscriptionWord[], time: number): number {
  if (words.length === 0) return -1;

  const exact = findActiveWordIndex(words, time);
  if (exact >= 0) return exact;

  // Binary search to find gap position
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (time < words[mid].start) hi = mid - 1;
    else if (time >= words[mid].end) lo = mid + 1;
    else return mid;
  }

  // Before all words → snap to first word
  if (hi < 0) return 0;
  // After all words → snap to last word
  if (lo >= words.length) return words.length - 1;
  // In a gap → stay on the last word we passed
  return hi;
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

/** Get the position of `el` relative to an ancestor, accounting for scroll. */
function getRelativeRect(el: HTMLElement, ancestor: HTMLElement) {
  const elRect = el.getBoundingClientRect();
  const ancRect = ancestor.getBoundingClientRect();
  return {
    top: elRect.top - ancRect.top + ancestor.scrollTop,
    left: elRect.left - ancRect.left + ancestor.scrollLeft,
    width: elRect.width,
    height: elRect.height,
  };
}

interface UseWordHighlighterOptions {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  segments: TranscriptionSegment[];
  isPlaying: boolean;
  containerRef: React.RefObject<HTMLElement | null>;
  enabled?: boolean;
}

const PADDING_X = 2;
const PADDING_Y = 1;

/**
 * Smooth word-level highlighting driven by requestAnimationFrame (~60 fps).
 *
 * Uses a floating overlay div that glides between word positions with CSS
 * transitions, creating a "train on rails" effect — the highlight never
 * disappears, it just moves from word to word.
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
  const overlayRef = useRef<HTMLDivElement | null>(null);

  // Single effect: creates overlay on demand, runs animation loop
  useEffect(() => {
    const audio = audioRef.current;
    const container = containerRef.current;

    if (!container) return;

    // Lazily create the overlay if it doesn't exist yet (or was removed)
    if (!overlayRef.current || !container.contains(overlayRef.current)) {
      // Ensure container is a positioning context
      const computed = getComputedStyle(container);
      if (computed.position === 'static') {
        container.style.position = 'relative';
      }

      const overlay = document.createElement('div');
      overlay.style.cssText = [
        'position: absolute',
        'pointer-events: none',
        'background: rgba(34, 211, 238, 0.25)',
        'border-radius: 4px',
        'z-index: 1',
        'opacity: 0',
        'margin: 0',
        'transition: top 120ms ease-out, left 120ms ease-out, width 80ms ease-out, height 80ms ease-out, opacity 200ms ease',
      ].join(';');
      container.appendChild(overlay);
      overlayRef.current = overlay;
    }

    const overlay = overlayRef.current;

    if (!enabled || !isPlaying || flatWords.length === 0 || !audio) {
      cancelAnimationFrame(rafIdRef.current);
      // Fade out on pause/stop, keep position
      overlay.style.opacity = '0';
      prevIdxRef.current = -1;
      return;
    }

    function tick() {
      const time = audio!.currentTime;
      const idx = findActiveOrNearestWordIndex(flatWords, time);

      if (idx >= 0) {
        const wordEl = container!.querySelector(`[data-word-idx="${idx}"]`) as HTMLElement | null;

        if (wordEl) {
          overlay.style.opacity = '1';

          if (idx !== prevIdxRef.current) {
            const rect = getRelativeRect(wordEl, container!);
            overlay.style.top = `${rect.top - PADDING_Y}px`;
            overlay.style.left = `${rect.left - PADDING_X}px`;
            overlay.style.width = `${rect.width + PADDING_X * 2}px`;
            overlay.style.height = `${rect.height + PADDING_Y * 2}px`;

            scrollToWord(wordEl, container!);
          }
        }
      }

      prevIdxRef.current = idx;
      rafIdRef.current = requestAnimationFrame(tick);
    }

    rafIdRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafIdRef.current);
    };
  }, [isPlaying, enabled, flatWords, audioRef, containerRef]);

  // Cleanup overlay on unmount
  useEffect(() => {
    return () => {
      overlayRef.current?.remove();
      overlayRef.current = null;
    };
  }, []);
}
