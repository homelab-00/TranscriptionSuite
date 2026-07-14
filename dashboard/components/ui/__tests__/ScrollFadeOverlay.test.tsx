/**
 * ScrollFadeOverlay — the fading blur bar pinned to a scroll container edge.
 *
 * The bar is always mounted and toggles opacity, rather than mounting and unmounting, so
 * that it can transition rather than pop. These tests pin that down along with the
 * per-edge anchoring and gradient direction.
 */

import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ScrollFadeOverlay } from '../ScrollFadeOverlay';

/** The outer positioned bar is the only child the component renders at the root. */
function renderBar(ui: React.ReactElement): HTMLElement {
  const { container } = render(ui);
  return container.firstElementChild as HTMLElement;
}

describe('ScrollFadeOverlay', () => {
  it('stays mounted but transparent when the edge is not clipping', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="top" visible={false} />);

    expect(bar).toBeTruthy();
    expect(bar.className).toContain('opacity-0');
    expect(bar.className).not.toContain('opacity-100');
    expect(bar.className).toContain('transition-opacity');
  });

  it('becomes opaque when the edge is clipping', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="top" visible={true} />);

    expect(bar.className).toContain('opacity-100');
  });

  // `to bottom` is the CSS default gradient direction, so jsdom serializes it away and
  // reports a bare `linear-gradient(black 50%, ...)`. `to top` is non-default and
  // survives. The assertions below are written to survive that normalization.
  it('anchors to the top and fades downward on the top edge', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="top" visible={true} />);
    const gradient = bar.firstElementChild as HTMLElement;

    expect(bar.className).toContain('top-0');
    expect(bar.className).not.toContain('bottom-0');
    expect(gradient.className).toContain('bg-linear-to-b');
    expect(gradient.style.maskImage).toContain('black 50%');
    expect(gradient.style.maskImage).toContain('transparent 100%');
    expect(gradient.style.maskImage).not.toContain('to top');
  });

  it('anchors to the bottom and fades upward on the bottom edge', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="bottom" visible={true} />);
    const gradient = bar.firstElementChild as HTMLElement;

    expect(bar.className).toContain('bottom-0');
    expect(bar.className).not.toContain('top-0');
    expect(gradient.className).toContain('bg-linear-to-t');
    expect(gradient.style.maskImage).toContain('to top');
    expect(gradient.style.maskImage).toContain('transparent 100%');
  });

  it('never intercepts pointer events, so it cannot block the content beneath it', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="bottom" visible={true} />);

    expect(bar.className).toContain('pointer-events-none');
  });

  it('rounds its corners to hug the rounded-2xl card silhouette on each edge', () => {
    const top = renderBar(<ScrollFadeOverlay edge="top" visible={true} />);
    const bottom = renderBar(<ScrollFadeOverlay edge="bottom" visible={true} />);

    expect(top.className).toContain('rounded-t-2xl');
    expect(top.className).not.toContain('rounded-b-2xl');
    expect(bottom.className).toContain('rounded-b-2xl');
    expect(bottom.className).not.toContain('rounded-t-2xl');
  });

  it('insets from the right by default so it does not wash over the scrollbar track', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="top" visible={true} />);

    expect(bar.className).toContain('right-3');
    expect(bar.className).not.toContain('right-0');
  });

  it('runs flush to the frame edge when the scrollbar sits outside the frame', () => {
    const bar = renderBar(<ScrollFadeOverlay edge="top" visible={true} rightInset="flush" />);

    expect(bar.className).toContain('right-0');
    expect(bar.className).not.toContain('right-3');
  });

  it('forwards a caller className, which is how each view disables the bar in its wide layout', () => {
    const bar = renderBar(
      <ScrollFadeOverlay edge="top" visible={true} className="@min-[840px]:hidden" />,
    );

    expect(bar.className).toContain('@min-[840px]:hidden');
  });
});
