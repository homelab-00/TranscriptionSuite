/**
 * useScrollFade — edge-clipping detection for scroll containers.
 *
 * Covers the case that motivated the hook: when the Session/Notebook grids collapse to a
 * single column, the scroll container migrates from the individual columns to the grid
 * itself, so the fade state has to be derived from whichever element is actually
 * scrolling.
 *
 * jsdom performs no layout, so scrollHeight/clientHeight are always 0. Every test below
 * stubs those three metrics explicitly to describe the scroll geometry under test.
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useRef } from 'react';
import { useScrollFade } from '../useScrollFade';

interface Geometry {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
}

/** Build a detached div whose scroll metrics report the supplied geometry. */
function makeScroller({ scrollTop, clientHeight, scrollHeight }: Geometry): HTMLDivElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true });
  Object.defineProperty(el, 'clientHeight', { value: clientHeight, configurable: true });
  Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true });
  document.body.appendChild(el);
  return el;
}

/** Render the hook against a ref already pointing at `el`. */
function renderWithElement(el: HTMLDivElement | null) {
  return renderHook(() => {
    const ref = useRef<HTMLDivElement | null>(el);
    return useScrollFade(ref);
  });
}

describe('useScrollFade', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('reports no fades when the content fits the container', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500, scrollHeight: 500 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: false, bottom: false });
  });

  it('reports only the bottom fade when parked at the top of overflowing content', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500, scrollHeight: 1200 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: false, bottom: true });
  });

  it('reports both fades when scrolled to the middle of overflowing content', () => {
    const el = makeScroller({ scrollTop: 300, clientHeight: 500, scrollHeight: 1200 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: true, bottom: true });
  });

  it('reports only the top fade when scrolled to the very bottom', () => {
    const el = makeScroller({ scrollTop: 700, clientHeight: 500, scrollHeight: 1200 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: true, bottom: false });
  });

  it('recomputes on scroll, so the top fade appears once the user leaves the top', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500, scrollHeight: 1200 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: false, bottom: true });

    act(() => {
      el.scrollTop = 40;
      el.dispatchEvent(new Event('scroll'));
    });

    expect(result.current).toEqual({ top: true, bottom: true });
  });

  it('clears the bottom fade when content shrinks to fit under a stationary scroll position', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500, scrollHeight: 1200 });
    const { result } = renderWithElement(el);
    expect(result.current.bottom).toBe(true);

    // A collapsing card shrinks the content without emitting a scroll event. The late
    // settle pass is what catches this in browsers that lack ResizeObserver.
    act(() => {
      Object.defineProperty(el, 'scrollHeight', { value: 400, configurable: true });
      vi.advanceTimersByTime(600);
    });

    expect(result.current.bottom).toBe(false);
  });

  it('treats a sub-pixel overflow as fitting, so the bar does not flicker on fractional heights', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500.4, scrollHeight: 500.6 });
    const { result } = renderWithElement(el);

    expect(result.current).toEqual({ top: false, bottom: false });
  });

  it('stays hidden when the ref is empty', () => {
    const { result } = renderWithElement(null);

    expect(result.current).toEqual({ top: false, bottom: false });
  });

  it('detaches its listeners on unmount', () => {
    const el = makeScroller({ scrollTop: 0, clientHeight: 500, scrollHeight: 1200 });
    const removeSpy = vi.spyOn(el, 'removeEventListener');
    const { unmount } = renderWithElement(el);

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function));
  });
});
