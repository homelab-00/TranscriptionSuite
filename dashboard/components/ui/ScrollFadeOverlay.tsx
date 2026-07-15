import React from 'react';

type ScrollFadeEdge = 'top' | 'bottom';

interface ScrollFadeOverlayProps {
  /** Which edge of the scroll container this bar sits on. */
  edge: ScrollFadeEdge;
  /** True when the container is clipping content past this edge. */
  visible: boolean;
  /** Extra classes, e.g. a container-query variant that disables the bar in a layout. */
  className?: string;
}

// The corners are rounded to the same 1rem radius as the rounded-2xl cards the bar
// washes over, so the bar hugs the card silhouette instead of drawing a square band.
const EDGE_ANCHOR: Record<ScrollFadeEdge, string> = {
  top: 'top-0 rounded-t-2xl',
  bottom: 'bottom-0 rounded-b-2xl',
};

// The gradient and the mask both point away from the edge, so the bar is densest where
// content is being cut off and dissolves into the content below or above it.
const EDGE_GRADIENT: Record<ScrollFadeEdge, string> = {
  top: 'bg-linear-to-b',
  bottom: 'bg-linear-to-t',
};

const EDGE_MASK: Record<ScrollFadeEdge, string> = {
  top: 'linear-gradient(to bottom, black 50%, transparent 100%)',
  bottom: 'linear-gradient(to top, black 50%, transparent 100%)',
};

/**
 * A fading blur bar pinned to the top or bottom edge of a scroll container, shown when
 * that container is clipping content.
 *
 * Must be rendered as a sibling of the scroll container inside a non-scrolling
 * `relative` wrapper. Placing it inside the scroller would make it scroll away with the
 * content, since an absolutely positioned child is laid out against the scrolled box.
 *
 * The right inset clears the 8px `.custom-scrollbar` track so the bar does not wash over
 * the scrollbar thumb.
 */
export const ScrollFadeOverlay: React.FC<ScrollFadeOverlayProps> = ({
  edge,
  visible,
  className = '',
}) => (
  <div
    className={`pointer-events-none absolute right-3 left-0 z-20 h-6 overflow-hidden transition-opacity duration-300 ${EDGE_ANCHOR[edge]} ${visible ? 'opacity-100' : 'opacity-0'} ${className}`}
  >
    <div
      className={`h-full w-full from-white/10 to-transparent backdrop-blur-sm ${EDGE_GRADIENT[edge]}`}
      style={{ maskImage: EDGE_MASK[edge], WebkitMaskImage: EDGE_MASK[edge] }}
    />
  </div>
);
