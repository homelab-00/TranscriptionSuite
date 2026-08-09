// @vitest-environment node

/**
 * Push-to-talk decision logic for the XDG GlobalShortcuts portal.
 *
 * Tests the pure helpers in pushToTalk.ts: timestamp normalization,
 * held-duration resolution (portal clock vs wall clock), hold-vs-tap
 * classification, and activation_token extraction from signal options.
 *
 * D-Bus signal wiring is NOT tested here - see waylandShortcuts.signals.test.ts.
 */

import { describe, it, expect } from 'vitest';
import {
  PUSH_TO_TALK_HOLD_MS,
  PRESS_REPEAT_WINDOW_MS,
  toMillis,
  heldDurationMs,
  isPushToTalkHold,
  mergePress,
  extractActivationToken,
  type PendingPress,
  type ShortcutPress,
} from '../pushToTalk.js';

function press(portalTimestamp: number, wallClock: number): ShortcutPress {
  return { portalTimestamp, wallClock };
}

// ── toMillis ────────────────────────────────────────────────────────────────

describe('[P2] toMillis', () => {
  it('passes finite numbers through unchanged', () => {
    expect(toMillis(1234)).toBe(1234);
    expect(toMillis(0)).toBe(0);
  });

  it('converts BigInt to number (dbus-next delivers the t type as BigInt)', () => {
    expect(toMillis(98765n)).toBe(98765);
    expect(toMillis(0n)).toBe(0);
  });

  it('returns 0 for undefined, null, NaN, Infinity, and strings', () => {
    expect(toMillis(undefined)).toBe(0);
    expect(toMillis(null)).toBe(0);
    expect(toMillis(Number.NaN)).toBe(0);
    expect(toMillis(Number.POSITIVE_INFINITY)).toBe(0);
    expect(toMillis('1234')).toBe(0);
  });
});

// ── heldDurationMs ──────────────────────────────────────────────────────────

describe('[P2] heldDurationMs', () => {
  it('uses the portal timestamp delta when both edges carry timestamps', () => {
    // Wall clocks deliberately disagree - the portal clock must win because
    // both edges share the same (undefined) base.
    expect(heldDurationMs(press(1000, 50_000), press(1800, 99_000))).toBe(800);
  });

  it('falls back to wall clock when the press has no portal timestamp', () => {
    expect(heldDurationMs(press(0, 50_000), press(1800, 50_600))).toBe(600);
  });

  it('falls back to wall clock when the release has no portal timestamp', () => {
    expect(heldDurationMs(press(1000, 50_000), press(0, 50_300))).toBe(300);
  });

  it('falls back to wall clock when the portal delta is negative', () => {
    // A compositor restart can reset the portal clock base mid-hold.
    expect(heldDurationMs(press(9000, 50_000), press(100, 50_700))).toBe(700);
  });

  it('clamps a negative wall clock delta to 0', () => {
    expect(heldDurationMs(press(0, 50_000), press(0, 49_000))).toBe(0);
  });
});

// ── isPushToTalkHold ────────────────────────────────────────────────────────

describe('[P2] isPushToTalkHold', () => {
  it('classifies a short tap as NOT a hold', () => {
    const held = PUSH_TO_TALK_HOLD_MS - 1;
    expect(isPushToTalkHold(press(1000, 0), press(1000 + held, held))).toBe(false);
  });

  it('classifies exactly the threshold as a hold', () => {
    expect(
      isPushToTalkHold(press(1000, 0), press(1000 + PUSH_TO_TALK_HOLD_MS, PUSH_TO_TALK_HOLD_MS)),
    ).toBe(true);
  });

  it('classifies a long hold as a hold', () => {
    expect(isPushToTalkHold(press(1000, 0), press(4000, 3000))).toBe(true);
  });

  it('respects a custom threshold', () => {
    expect(isPushToTalkHold(press(1000, 0), press(1200, 200), 100)).toBe(true);
    expect(isPushToTalkHold(press(1000, 0), press(1200, 200), 300)).toBe(false);
  });
});

// ── mergePress ──────────────────────────────────────────────────────────────

describe('[P2] mergePress', () => {
  it('starts a new pending press when none is pending', () => {
    const incoming = press(1000, 50_000);
    expect(mergePress(null, incoming)).toEqual({ press: incoming, lastSeen: 50_000 });
  });

  it('keeps the FIRST press across auto-repeat within the window', () => {
    // KDE bug 484525: some Plasma versions stream Activated while held.
    const first = press(1000, 50_000);
    let pending: PendingPress = mergePress(null, first);
    pending = mergePress(pending, press(1600, 50_600));
    expect(pending.press).toEqual(first);
    expect(pending.lastSeen).toBe(50_600);
  });

  it('refreshes lastSeen on each repeat so long holds keep merging', () => {
    const first = press(1000, 50_000);
    let pending: PendingPress = mergePress(null, first);
    // Repeats every 600ms for 3 seconds: each is within the window of the
    // PREVIOUS repeat even though the total exceeds the window.
    for (let t = 600; t <= 3000; t += 600) {
      pending = mergePress(pending, press(1000 + t, 50_000 + t));
    }
    expect(pending.press).toEqual(first);
    expect(pending.lastSeen).toBe(53_000);
  });

  it('starts over when the gap exceeds the repeat window (missed release)', () => {
    const stale = mergePress(null, press(1000, 50_000));
    const fresh = press(9000, 50_000 + PRESS_REPEAT_WINDOW_MS + 1);
    expect(mergePress(stale, fresh)).toEqual({ press: fresh, lastSeen: fresh.wallClock });
  });

  it('respects a custom repeat window', () => {
    const pending = mergePress(null, press(1000, 50_000));
    expect(mergePress(pending, press(1200, 50_200), 100).press).toEqual(press(1200, 50_200));
    expect(mergePress(pending, press(1200, 50_200), 300).press).toEqual(press(1000, 50_000));
  });
});

// ── extractActivationToken ──────────────────────────────────────────────────

describe('[P2] extractActivationToken', () => {
  it('unwraps a dbus-next Variant-shaped value', () => {
    expect(extractActivationToken({ activation_token: { signature: 's', value: 'tok-123' } })).toBe(
      'tok-123',
    );
  });

  it('accepts a plain string value', () => {
    expect(extractActivationToken({ activation_token: 'tok-456' })).toBe('tok-456');
  });

  it('returns null for an empty token string', () => {
    expect(extractActivationToken({ activation_token: '' })).toBeNull();
    expect(extractActivationToken({ activation_token: { signature: 's', value: '' } })).toBeNull();
  });

  it('returns null when the key is missing or options is not an object', () => {
    // KDE currently emits an empty options dict, so this is the common case.
    expect(extractActivationToken({})).toBeNull();
    expect(extractActivationToken(undefined)).toBeNull();
    expect(extractActivationToken(null)).toBeNull();
    expect(extractActivationToken('tok')).toBeNull();
  });

  it('returns null for non-string token values', () => {
    expect(extractActivationToken({ activation_token: 42 })).toBeNull();
    expect(extractActivationToken({ activation_token: { signature: 'u', value: 42 } })).toBeNull();
  });
});
