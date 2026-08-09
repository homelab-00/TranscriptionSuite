/**
 * Push-to-talk decision logic for the XDG GlobalShortcuts portal.
 *
 * The portal emits Activated on shortcut press and Deactivated on release
 * (interface version 2). Holding the start-recording shortcut past the
 * threshold turns the release into "stop and transcribe" (push-to-talk),
 * while a short tap keeps the existing edge-triggered toggle behavior.
 *
 * Pure functions only - the D-Bus signal wiring lives in waylandShortcuts.ts.
 */

/** Minimum held duration for a press/release pair to count as push-to-talk. */
export const PUSH_TO_TALK_HOLD_MS = 500;

/**
 * Max gap between Activated edges that still counts as key auto-repeat of the
 * SAME physical hold. KDE bug 484525: some Plasma versions stream repeated
 * Activated signals while a portal shortcut is held. KDE repeat delay
 * defaults to ~600ms, so 1500ms comfortably covers repeats while a fresh
 * press after a missed release (human timescale, seconds apart) starts over.
 */
export const PRESS_REPEAT_WINDOW_MS = 1500;

/** Snapshot of a shortcut press, kept until the matching release arrives. */
export interface ShortcutPress {
  /**
   * Portal-supplied timestamp in ms. The spec leaves the clock base
   * undefined, but press and release share it, so deltas are meaningful.
   * 0 when the portal sent none.
   */
  portalTimestamp: number;
  /** Wall-clock ms captured when the signal arrived - the fallback clock. */
  wallClock: number;
}

/** A press awaiting its release, tracking auto-repeat refreshes. */
export interface PendingPress {
  /** The FIRST press edge of the current physical hold. */
  press: ShortcutPress;
  /** Wall-clock ms of the latest Activated edge (first press or a repeat). */
  lastSeen: number;
}

/**
 * Fold an incoming Activated edge into the pending-press state.
 * An edge arriving within repeatWindowMs of the last one is key auto-repeat
 * of the same hold: the original press is kept so held duration is measured
 * from the true press start. A later edge starts a new press (covers a
 * missed Deactivated, e.g. after a portal restart).
 */
export function mergePress(
  pending: PendingPress | null,
  incoming: ShortcutPress,
  repeatWindowMs: number = PRESS_REPEAT_WINDOW_MS,
): PendingPress {
  if (pending && incoming.wallClock - pending.lastSeen <= repeatWindowMs) {
    return { press: pending.press, lastSeen: incoming.wallClock };
  }
  return { press: incoming, lastSeen: incoming.wallClock };
}

/**
 * Normalize a D-Bus timestamp to a number of milliseconds.
 * dbus-next delivers the spec's `t` (uint64) type as BigInt; other portals
 * may omit the value entirely. Anything unusable maps to 0, which
 * heldDurationMs treats as "no portal timestamp".
 */
export function toMillis(timestamp: unknown): number {
  if (typeof timestamp === 'bigint') return Number(timestamp);
  if (typeof timestamp === 'number' && Number.isFinite(timestamp)) return timestamp;
  return 0;
}

/**
 * Held duration between press and release. Prefers the portal clock (both
 * edges share its base); falls back to wall clock when either edge lacks a
 * portal timestamp or the delta is negative (e.g. a compositor restart
 * reset the clock base mid-hold).
 */
export function heldDurationMs(press: ShortcutPress, release: ShortcutPress): number {
  const portalDelta = release.portalTimestamp - press.portalTimestamp;
  if (press.portalTimestamp > 0 && release.portalTimestamp > 0 && portalDelta >= 0) {
    return portalDelta;
  }
  return Math.max(0, release.wallClock - press.wallClock);
}

/** Whether a press/release pair counts as a push-to-talk hold. */
export function isPushToTalkHold(
  press: ShortcutPress,
  release: ShortcutPress,
  thresholdMs: number = PUSH_TO_TALK_HOLD_MS,
): boolean {
  return heldDurationMs(press, release) >= thresholdMs;
}

/**
 * Extract the optional `activation_token` from a portal signal options
 * vardict. dbus-next wraps vardict values in Variant objects
 * ({ signature, value }); plain strings are tolerated too. Returns null when
 * absent, empty, or not a string. xdg-desktop-portal-kde currently emits an
 * empty options dict (the C++ parameter is literally named `unused`), so on
 * Plasma this stays null until KDE starts minting tokens.
 */
export function extractActivationToken(options: unknown): string | null {
  if (options == null || typeof options !== 'object') return null;
  const raw = (options as Record<string, unknown>)['activation_token'];
  const value =
    raw != null && typeof raw === 'object' && 'value' in raw
      ? (raw as { value: unknown }).value
      : raw;
  return typeof value === 'string' && value.length > 0 ? value : null;
}
