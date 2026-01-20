import { useRef, useCallback, useMemo, useEffect } from 'react';
import { Word } from '../types';

/**
 * Word data with flattened index for efficient lookup
 */
export interface FlatWord extends Word {
  globalIndex: number;
  segmentIndex: number;
  wordIndex: number;
}

interface UseTranscriptHighlighterOptions {
  /** Container element ref where word spans are rendered */
  containerRef: React.RefObject<HTMLElement>;
}

interface UseTranscriptHighlighterReturn {
  /** Update the highlight to the word at the given time. Call this from animation loop. */
  updateHighlight: (currentTime: number) => void;
  /** Clear the current highlight */
  clearHighlight: () => void;
  /** Whether CSS Highlight API is supported */
  isHighlightAPISupported: boolean;
  /** Flattened words array with global indices, sorted by start time */
  flattenedWords: FlatWord[];
  /** Create flattened words from segments */
  createFlattenedWords: (segments: Array<{ words?: Word[]; text: string }>) => FlatWord[];
  /** Binary search to find word at time */
  findWordAtTime: (time: number) => number;
}

// Check for CSS Highlight API support
const isHighlightAPISupported =
  typeof CSS !== 'undefined' &&
  'highlights' in CSS &&
  typeof Highlight !== 'undefined';

/**
 * Binary search to find the index of the word active at a given time.
 * Returns -1 if no word is active at that time.
 *
 * @param words - Sorted array of words by start time
 * @param time - Current playback time in seconds
 * @returns Index of active word or -1
 */
function binarySearchWordAtTime(words: FlatWord[], time: number): number {
  if (words.length === 0) return -1;

  let left = 0;
  let right = words.length - 1;

  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    const word = words[mid];

    if (time >= word.start && time < word.end) {
      return mid; // Found exact match
    }

    if (time < word.start) {
      right = mid - 1;
    } else {
      // time >= word.end
      left = mid + 1;
    }
  }

  return -1; // No word active at this time
}

/**
 * Flatten segments into a single sorted array of words with global indices.
 */
function flattenSegments(segments: Array<{ words?: Word[]; text: string }>): FlatWord[] {
  const result: FlatWord[] = [];
  let globalIndex = 0;

  segments.forEach((segment, segmentIndex) => {
    if (segment.words) {
      segment.words.forEach((word, wordIndex) => {
        result.push({
          ...word,
          globalIndex,
          segmentIndex,
          wordIndex,
        });
        globalIndex++;
      });
    }
  });

  // Sort by start time to ensure binary search works correctly
  result.sort((a, b) => a.start - b.start);

  return result;
}

/**
 * High-performance transcript highlighting hook using CSS Highlight API.
 *
 * This hook provides 60fps word highlighting without React re-renders by:
 * 1. Using CSS Highlight API (when supported) to highlight text without DOM changes
 * 2. Using binary search O(log n) to find the active word by timestamp
 * 3. Bypassing React state entirely for time-based updates
 *
 * For browsers without CSS Highlight API support, falls back to direct DOM
 * class manipulation (still no React re-renders).
 */
export function useTranscriptHighlighter({
  containerRef,
}: UseTranscriptHighlighterOptions): UseTranscriptHighlighterReturn {
  // Track the last highlighted word index to avoid redundant updates
  const lastActiveIndexRef = useRef<number>(-1);
  // Store flattened words for binary search
  const flattenedWordsRef = useRef<FlatWord[]>([]);

  /**
   * Create flattened words array from segments
   */
  const createFlattenedWords = useCallback((segments: Array<{ words?: Word[]; text: string }>): FlatWord[] => {
    const flattened = flattenSegments(segments);
    flattenedWordsRef.current = flattened;
    return flattened;
  }, []);

  /**
   * Find word at given time using binary search
   */
  const findWordAtTime = useCallback((time: number): number => {
    return binarySearchWordAtTime(flattenedWordsRef.current, time);
  }, []);

  /**
   * Clear current highlight
   */
  const clearHighlight = useCallback(() => {
    if (isHighlightAPISupported) {
      CSS.highlights.delete('transcript-active');
    } else {
      // Fallback: remove class from previously highlighted element
      if (lastActiveIndexRef.current >= 0 && containerRef.current) {
        const oldElement = containerRef.current.querySelector(
          `[data-word-index="${lastActiveIndexRef.current}"]`
        );
        oldElement?.classList.remove('word-active');
      }
    }
    lastActiveIndexRef.current = -1;
  }, [containerRef]);

  /**
   * Update highlight using CSS Highlight API (modern browsers)
   */
  const updateHighlightModern = useCallback((activeIndex: number) => {
    if (!containerRef.current) return;

    // Clear previous highlight
    CSS.highlights.delete('transcript-active');

    if (activeIndex < 0) return;

    const wordElement = containerRef.current.querySelector(
      `[data-word-index="${activeIndex}"]`
    );

    if (wordElement?.firstChild) {
      try {
        const range = new Range();
        range.selectNodeContents(wordElement);
        const highlight = new Highlight(range);
        CSS.highlights.set('transcript-active', highlight);
      } catch {
        // Range creation can fail in edge cases, just skip
      }
    }
  }, [containerRef]);

  /**
   * Update highlight using direct DOM class manipulation (fallback)
   */
  const updateHighlightFallback = useCallback((activeIndex: number) => {
    if (!containerRef.current) return;

    const lastIndex = lastActiveIndexRef.current;

    // Remove old highlight
    if (lastIndex >= 0 && lastIndex !== activeIndex) {
      const oldElement = containerRef.current.querySelector(
        `[data-word-index="${lastIndex}"]`
      );
      oldElement?.classList.remove('word-active');
    }

    // Add new highlight
    if (activeIndex >= 0) {
      const newElement = containerRef.current.querySelector(
        `[data-word-index="${activeIndex}"]`
      );
      newElement?.classList.add('word-active');
    }
  }, [containerRef]);

  /**
   * Main update function - call this from animation loop
   */
  const updateHighlight = useCallback((currentTime: number) => {
    const activeIndex = binarySearchWordAtTime(flattenedWordsRef.current, currentTime);

    // Skip if no change
    if (activeIndex === lastActiveIndexRef.current) return;

    // Update using appropriate method
    if (isHighlightAPISupported) {
      updateHighlightModern(activeIndex);
    } else {
      updateHighlightFallback(activeIndex);
    }

    lastActiveIndexRef.current = activeIndex;
  }, [updateHighlightModern, updateHighlightFallback]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (isHighlightAPISupported) {
        CSS.highlights.delete('transcript-active');
      }
    };
  }, []);

  // Memoize the flattened words (empty initially, populated via createFlattenedWords)
  const flattenedWords = useMemo(() => flattenedWordsRef.current, []);

  return {
    updateHighlight,
    clearHighlight,
    isHighlightAPISupported,
    flattenedWords,
    createFlattenedWords,
    findWordAtTime,
  };
}

export default useTranscriptHighlighter;
