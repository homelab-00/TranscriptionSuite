// @vitest-environment node

/**
 * Portal signal wiring for push-to-talk (subscribeToSignals).
 *
 * Drives Activated/Deactivated pairs through a fake portal proxy and a send
 * spy - the same fake-object pattern the registerHostAppId tests use - and
 * asserts the push-to-talk invariants end to end: tap keeps toggle behavior,
 * a hold sends ptt-stop-recording exactly once, auto-repeat does not reset
 * the held-duration clock, the KDE empty-options dict is harmless, and
 * teardown clears the pending press.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { subscribeToSignals, destroyWaylandShortcuts } from '../waylandShortcuts.js';
import { PUSH_TO_TALK_HOLD_MS } from '../pushToTalk.js';

const SESSION = '/org/freedesktop/portal/desktop/session/1_23/s';
const START_ID = 'start-recording';
const STOP_ID = 'stop-transcribe';

class FakePortalProxy {
  handlers = new Map<string, (...args: unknown[]) => void>();
  removedListeners: string[] = [];

  on(signalName: string, handler: (...args: unknown[]) => void): void {
    this.handlers.set(signalName, handler);
  }

  removeListener(signalName: string): void {
    this.removedListeners.push(signalName);
    this.handlers.delete(signalName);
  }

  emit(signalName: string, ...args: unknown[]): void {
    this.handlers.get(signalName)?.(...args);
  }
}

function setup() {
  const proxy = new FakePortalProxy();
  const send = vi.fn();
  subscribeToSignals(proxy, send);
  return { proxy, send };
}

function pttActions(send: ReturnType<typeof vi.fn>): number {
  return send.mock.calls.filter((c) => c[0] === 'tray:action' && c[1] === 'ptt-stop-recording')
    .length;
}

const savedToken = process.env.XDG_ACTIVATION_TOKEN;

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  delete process.env.XDG_ACTIVATION_TOKEN;
});

afterEach(() => {
  // Resets pendingStartPress and the unsubscribe closures between tests.
  destroyWaylandShortcuts();
  vi.restoreAllMocks();
  if (savedToken === undefined) delete process.env.XDG_ACTIVATION_TOKEN;
  else process.env.XDG_ACTIVATION_TOKEN = savedToken;
});

describe('[P2] subscribeToSignals push-to-talk wiring', () => {
  it('forwards Activated to the tray action for both shortcuts', () => {
    const { proxy, send } = setup();

    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    proxy.emit('Activated', SESSION, STOP_ID, 2000n, {});

    expect(send).toHaveBeenCalledWith('tray:action', 'start-recording');
    expect(send).toHaveBeenCalledWith('tray:action', 'stop-recording');
  });

  it('treats a short tap as a toggle: release sends no ptt action', () => {
    const { proxy, send } = setup();

    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    proxy.emit('Deactivated', SESSION, START_ID, 1000n + BigInt(PUSH_TO_TALK_HOLD_MS - 1), {});

    expect(pttActions(send)).toBe(0);
  });

  it('sends ptt-stop-recording exactly once for a qualifying hold', () => {
    const { proxy, send } = setup();

    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    proxy.emit('Deactivated', SESSION, START_ID, 1000n + BigInt(PUSH_TO_TALK_HOLD_MS + 200), {});
    // A duplicate release must not fire again (pending press was consumed).
    proxy.emit('Deactivated', SESSION, START_ID, 9000n, {});

    expect(pttActions(send)).toBe(1);
  });

  it('does NOT reset the held-duration clock on key auto-repeat', () => {
    // KDE bug 484525: Plasma can stream Activated signals while a shortcut is
    // held. Only the repeat 100ms before the release would be counted without
    // first-press-wins merging, misclassifying the hold as a tap.
    const now = vi.spyOn(Date, 'now');
    const { proxy, send } = setup();

    now.mockReturnValue(10_000);
    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    now.mockReturnValue(10_600);
    proxy.emit('Activated', SESSION, START_ID, 1600n, {});
    now.mockReturnValue(10_700);
    proxy.emit('Deactivated', SESSION, START_ID, 1700n, {});

    expect(pttActions(send)).toBe(1);
  });

  it('starts a fresh press after the repeat window (missed release)', () => {
    const now = vi.spyOn(Date, 'now');
    const { proxy, send } = setup();

    // First press whose release was never delivered (e.g. portal hiccup).
    now.mockReturnValue(10_000);
    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    // A real tap 10 seconds later must not inherit the stale press, or the
    // release would misread as a 10-second hold and stop the new recording.
    now.mockReturnValue(20_000);
    proxy.emit('Activated', SESSION, START_ID, 11_000n, {});
    now.mockReturnValue(20_100);
    proxy.emit('Deactivated', SESSION, START_ID, 11_100n, {});

    expect(pttActions(send)).toBe(0);
  });

  it('ignores Deactivated for the stop shortcut and unknown ids', () => {
    const { proxy, send } = setup();

    proxy.emit('Activated', SESSION, STOP_ID, 1000n, {});
    proxy.emit('Deactivated', SESSION, STOP_ID, 5000n, {});
    proxy.emit('Deactivated', SESSION, 'bogus-id', 5000n, {});
    proxy.emit('Activated', SESSION, 'bogus-id', 5000n, {});

    expect(pttActions(send)).toBe(0);
    expect(send).toHaveBeenCalledTimes(1); // only the stop Activated
  });

  it('handles the KDE empty-options dict without stashing a token', () => {
    const { proxy } = setup();

    proxy.emit('Activated', SESSION, START_ID, 1000n, {});
    proxy.emit('Deactivated', SESSION, START_ID, 2000n, {});

    expect(process.env.XDG_ACTIVATION_TOKEN).toBeUndefined();
  });

  it('stashes a portal-supplied activation token into the environment', () => {
    const { proxy } = setup();

    proxy.emit('Activated', SESSION, START_ID, 1000n, {
      activation_token: { signature: 's', value: 'tok-789' },
    });

    expect(process.env.XDG_ACTIVATION_TOKEN).toBe('tok-789');
  });

  it('drops the pending press on teardown so it cannot leak into a new session', () => {
    const first = setup();
    first.proxy.emit('Activated', SESSION, START_ID, 1000n, {});

    destroyWaylandShortcuts();

    // New portal session after re-registration: a release with hold-length
    // timestamps must find no pending press and stay silent.
    const second = setup();
    second.proxy.emit('Deactivated', SESSION, START_ID, 9000n, {});

    expect(pttActions(second.send)).toBe(0);
  });

  it('unsubscribes all three signals on teardown', () => {
    const { proxy } = setup();

    destroyWaylandShortcuts();

    expect(proxy.removedListeners.sort()).toEqual(['Activated', 'Deactivated', 'ShortcutsChanged']);
  });
});
