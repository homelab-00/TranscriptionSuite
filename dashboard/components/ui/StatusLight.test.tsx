/**
 * StatusLight — pulse synchronization tests.
 *
 * Every pulsing StatusLight must anchor its `animate-ping` ring to the SAME
 * point on the document timeline so that all status dots across the app blink
 * in phase, regardless of when each one mounted. The component guarantees this
 * by pinning each ring animation's `startTime` to a single shared anchor (the
 * timeline origin, 0).
 *
 * jsdom does not implement the Web Animations API, so we install a minimal
 * `getAnimations()` mock that records the `startTime` the component assigns.
 */
import { render, cleanup, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StatusLight } from './StatusLight';

interface FakeAnimation {
  startTime: number | null;
}

// Must match PULSE_TIMELINE_ANCHOR_MS in StatusLight.tsx.
const SHARED_ANCHOR = 0;

type ElementWithFakeAnim = HTMLElement & { __fakeAnim?: FakeAnimation };

let originalGetAnimations: unknown;

beforeEach(() => {
  originalGetAnimations = (HTMLElement.prototype as unknown as Record<string, unknown>)
    .getAnimations;
  (HTMLElement.prototype as unknown as Record<string, unknown>).getAnimations = function (
    this: ElementWithFakeAnim,
  ): FakeAnimation[] {
    // Lazily attach one fake animation per element, initialised to a
    // deliberately out-of-phase startTime so the test proves the component
    // overrides it to the shared anchor.
    if (!this.__fakeAnim) {
      this.__fakeAnim = { startTime: 987 };
    }
    return [this.__fakeAnim];
  };
});

afterEach(() => {
  cleanup();
  (HTMLElement.prototype as unknown as Record<string, unknown>).getAnimations =
    originalGetAnimations;
});

function pingAnimation(container: HTMLElement): FakeAnimation | undefined {
  const ping = container.querySelector('.animate-ping') as ElementWithFakeAnim | null;
  return ping?.__fakeAnim;
}

describe('StatusLight pulse synchronization', () => {
  it('pins an active dot ping animation to the shared timeline anchor', () => {
    const { container } = render(<StatusLight status="active" />);
    expect(pingAnimation(container)?.startTime).toBe(SHARED_ANCHOR);
  });

  it('pins independently-mounted dots to the SAME anchor so they blink in phase', () => {
    const a = render(<StatusLight status="active" />);
    const b = render(<StatusLight status="warning" />);
    expect(pingAnimation(a.container)?.startTime).toBe(SHARED_ANCHOR);
    expect(pingAnimation(b.container)?.startTime).toBe(SHARED_ANCHOR);
  });

  it('syncs via the rAF retry when the animation is not yet registered at layout-effect time', () => {
    // Mimic real Chromium: the CSSAnimation is not registered during the
    // layout-effect (style recalc has not run), so the first getAnimations()
    // returns []. The component must pin it on the next frame instead.
    let calls = 0;
    (HTMLElement.prototype as unknown as Record<string, unknown>).getAnimations = function (
      this: ElementWithFakeAnim,
    ): FakeAnimation[] {
      calls += 1;
      if (calls === 1) return [];
      if (!this.__fakeAnim) {
        this.__fakeAnim = { startTime: 987 };
      }
      return [this.__fakeAnim];
    };

    const rafCallbacks: FrameRequestCallback[] = [];
    const realRaf = globalThis.requestAnimationFrame;
    const realCancel = globalThis.cancelAnimationFrame;
    globalThis.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    }) as typeof requestAnimationFrame;
    globalThis.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame;

    try {
      const { container } = render(<StatusLight status="active" />);
      // Synchronous pin saw an empty list: not synced yet.
      expect(pingAnimation(container)?.startTime).toBeUndefined();
      // Flush the queued frame: the animation now exists and gets pinned.
      act(() => {
        rafCallbacks.forEach((cb) => cb(0));
      });
      expect(pingAnimation(container)?.startTime).toBe(SHARED_ANCHOR);
    } finally {
      globalThis.requestAnimationFrame = realRaf;
      globalThis.cancelAnimationFrame = realCancel;
    }
  });

  it('renders no ping ring (nothing to sync) for an inactive dot', () => {
    const { container } = render(<StatusLight status="inactive" />);
    expect(container.querySelector('.animate-ping')).toBeNull();
  });

  it('renders no ping ring when animation is disabled', () => {
    const { container } = render(<StatusLight status="active" animate={false} />);
    expect(container.querySelector('.animate-ping')).toBeNull();
  });
});
