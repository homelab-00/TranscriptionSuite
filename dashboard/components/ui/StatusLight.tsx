import React, { useLayoutEffect, useRef } from 'react';

interface StatusLightProps {
  status: 'active' | 'inactive' | 'warning' | 'error' | 'loading';
  className?: string;
  animate?: boolean;
}

// All pulsing status dots share this single point on the document timeline as
// their animation origin. Because every `animate-ping` ring is pinned to the
// same start time on the same (document) clock, every dot is at the identical
// phase at any instant, so they all blink in lockstep no matter when each one
// mounted. See StatusLight.test.tsx for the synchronization invariant.
const PULSE_TIMELINE_ANCHOR_MS = 0;

export const StatusLight: React.FC<StatusLightProps> = ({
  status,
  className = '',
  animate = true,
}) => {
  const colors = {
    active: 'bg-green-500 shadow-green-500/50',
    inactive: 'bg-slate-500 shadow-slate-500/50',
    warning: 'bg-accent-orange shadow-accent-orange/50',
    error: 'bg-red-500 shadow-red-500/50',
    loading: 'bg-blue-400 shadow-blue-400/50',
  };

  // Keep pulse behavior aligned with the original mockup:
  // any non-inactive status can pulse when animation is enabled.
  const shouldPulse = animate && status !== 'inactive';

  const pingRef = useRef<HTMLSpanElement>(null);

  // Synchronize every dot by pinning its ping ring to a single shared origin on
  // the document timeline. Unlike a mount-time negative `animation-delay`, this
  // does not depend on WHEN the browser assigned the animation start time
  // (which varies with main-thread load), so dots that mount in different
  // frames still blink in phase with one another.
  useLayoutEffect(() => {
    if (!shouldPulse) return;
    const el = pingRef.current;
    if (!el || typeof el.getAnimations !== 'function') return;

    const pin = (): void => {
      const animations = el.getAnimations();
      for (const animation of animations) {
        try {
          animation.startTime = PULSE_TIMELINE_ANCHOR_MS;
        } catch {
          // startTime can be transiently read-only (e.g. a pending animation);
          // the requestAnimationFrame retry below covers that case.
        }
      }
    };

    // In practice the CSS animation is usually not registered yet at
    // layout-effect time (it appears after the browser's style recalculation),
    // so this synchronous call is typically a no-op and the rAF retry below is
    // what actually pins it — before the first paint, so no unsynced frame is
    // ever shown.
    pin();
    const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(pin) : 0;
    return () => {
      if (raf && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(raf);
    };
    // `status` is a dependency so the pin is reasserted across status changes,
    // in case a transition ever reconstructs the underlying CSS animation.
  }, [shouldPulse, status]);

  return (
    <span className={`relative flex h-3 w-3 ${className}`}>
      {shouldPulse && (
        <span
          ref={pingRef}
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${colors[status].split(' ')[0]}`}
        ></span>
      )}
      <span
        className={`relative inline-flex h-3 w-3 rounded-full shadow-lg ${colors[status]}`}
      ></span>
    </span>
  );
};
