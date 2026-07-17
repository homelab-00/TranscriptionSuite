import { useCallback, useEffect, useState, type RefObject } from 'react';

export interface ScrollFadeState {
  top: boolean;
  bottom: boolean;
}

const HIDDEN: ScrollFadeState = { top: false, bottom: false };

/**
 * Reports whether a scroll container is clipping content above or below its
 * viewport, so a caller can fade in an edge affordance.
 *
 * Observes the container and its direct children, not just scroll events, so the
 * bottom edge still updates when content grows or collapses under a stationary
 * scroll position.
 */
export function useScrollFade(
  ref: RefObject<HTMLElement | null>,
  deps: readonly unknown[] = [],
): ScrollFadeState {
  const [state, setState] = useState<ScrollFadeState>(HIDDEN);

  const recalc = useCallback(() => {
    const el = ref.current;
    const next: ScrollFadeState = el
      ? {
          top: el.scrollTop > 0,
          bottom: Math.ceil(el.scrollTop + el.clientHeight) < el.scrollHeight,
        }
      : HIDDEN;
    // Keep the previous object when nothing changed, so a scroll frame that does not
    // cross an edge boundary does not re-render the consumer.
    setState((prev) => (prev.top === next.top && prev.bottom === next.bottom ? prev : next));
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.addEventListener('scroll', recalc, { passive: true });
    window.addEventListener('resize', recalc);

    // jsdom does not implement ResizeObserver; the view unit tests throw without this guard.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(recalc);
    observer?.observe(el);
    Array.from(el.children).forEach((child) => observer?.observe(child));

    recalc();
    const raf = requestAnimationFrame(recalc);
    // Late pass: the stacked-layout reflow animation runs for 300ms, and the column
    // heights are only final once it settles.
    const settle = setTimeout(recalc, 575);

    return () => {
      el.removeEventListener('scroll', recalc);
      window.removeEventListener('resize', recalc);
      observer?.disconnect();
      cancelAnimationFrame(raf);
      clearTimeout(settle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, recalc, ...deps]);

  return state;
}
