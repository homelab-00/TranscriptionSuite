// @vitest-environment node

/**
 * launchWatchdog — per-version counter tests per M6 I/O matrix.
 */

import { describe, it, expect, beforeEach } from 'vitest';

import {
  LaunchWatchdog,
  LAUNCH_ATTEMPTS_KEY,
  RESTORE_PROMPT_THRESHOLD,
} from '../launchWatchdog.js';
import type { CachedInstaller } from '../installerCache.js';

function makeFakeStore(): {
  get: (k: string) => unknown;
  set: (k: string, v: unknown) => void;
  data: Record<string, unknown>;
} {
  const data: Record<string, unknown> = {};
  return {
    data,
    get: (k: string) => data[k],
    set: (k: string, v: unknown) => {
      data[k] = v;
    },
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function watchdog(store: ReturnType<typeof makeFakeStore>): LaunchWatchdog {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return new LaunchWatchdog(store as any);
}

describe('LaunchWatchdog.recordLaunchAttempt', () => {
  let store: ReturnType<typeof makeFakeStore>;

  beforeEach(() => {
    store = makeFakeStore();
  });

  it('starts at count=1 on first launch of a fresh version', () => {
    const result = watchdog(store).recordLaunchAttempt('1.3.3', null);

    expect(result).toEqual({ count: 1, shouldPromptRestore: false });
    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toEqual({ version: '1.3.3', count: 1 });
  });

  it('increments count on subsequent launches of the same version', () => {
    const wd = watchdog(store);
    wd.recordLaunchAttempt('1.3.3', null);
    wd.recordLaunchAttempt('1.3.3', null);
    const third = wd.recordLaunchAttempt('1.3.3', null);

    expect(third.count).toBe(3);
    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toEqual({ version: '1.3.3', count: 3 });
  });

  it('resets count on a version change', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.2', count: 5 };

    const result = watchdog(store).recordLaunchAttempt('1.3.3', null);

    expect(result.count).toBe(1);
    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toEqual({ version: '1.3.3', count: 1 });
  });

  it('raises shouldPromptRestore=true when count hits threshold AND cache is older version', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: RESTORE_PROMPT_THRESHOLD - 1 };
    const cached: CachedInstaller = { path: '/tmp/prev.AppImage', version: '1.3.2' };

    const result = watchdog(store).recordLaunchAttempt('1.3.3', cached);

    expect(result.count).toBe(RESTORE_PROMPT_THRESHOLD);
    expect(result.shouldPromptRestore).toBe(true);
  });

  it('suppresses shouldPromptRestore when no cache exists', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: RESTORE_PROMPT_THRESHOLD - 1 };

    const result = watchdog(store).recordLaunchAttempt('1.3.3', null);

    expect(result.count).toBe(RESTORE_PROMPT_THRESHOLD);
    expect(result.shouldPromptRestore).toBe(false);
  });

  it('suppresses shouldPromptRestore when cache is the same version as running', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: RESTORE_PROMPT_THRESHOLD - 1 };
    const cached: CachedInstaller = { path: '/tmp/prev.AppImage', version: '1.3.3' };

    const result = watchdog(store).recordLaunchAttempt('1.3.3', cached);

    expect(result.shouldPromptRestore).toBe(false);
  });

  it('ignores malformed persisted records', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: 42, count: 'five' };

    const result = watchdog(store).recordLaunchAttempt('1.3.3', null);

    expect(result.count).toBe(1);
  });

  it('rejects pathological count values (Infinity / negative / non-integer / overflow)', () => {
    for (const bogus of [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, -1, 1.5, NaN, 9999]) {
      store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: bogus };
      const result = watchdog(store).recordLaunchAttempt('1.3.3', null);
      expect(result.count).toBe(1);
    }
  });
});

describe('LaunchWatchdog.confirmLaunchStable', () => {
  let store: ReturnType<typeof makeFakeStore>;

  beforeEach(() => {
    store = makeFakeStore();
  });

  it('resets count to 0 while preserving the version', () => {
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: 2 };

    watchdog(store).confirmLaunchStable();

    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toEqual({ version: '1.3.3', count: 0 });
  });

  it('is a no-op when there is no stored record', () => {
    watchdog(store).confirmLaunchStable();
    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toBeUndefined();
  });

  it('resets the counter ahead of the next failed launch', () => {
    const wd = watchdog(store);
    wd.recordLaunchAttempt('1.3.3', null);
    wd.recordLaunchAttempt('1.3.3', null);
    wd.confirmLaunchStable();
    const next = wd.recordLaunchAttempt('1.3.3', null);

    // After a stable launch reset, the next failed-launch increment is 1.
    expect(next.count).toBe(1);
  });
});

describe('LaunchWatchdog.destroy', () => {
  it('does not throw and leaves the store untouched', () => {
    const store = makeFakeStore();
    store.data[LAUNCH_ATTEMPTS_KEY] = { version: '1.3.3', count: 2 };

    watchdog(store).destroy();

    expect(store.data[LAUNCH_ATTEMPTS_KEY]).toEqual({ version: '1.3.3', count: 2 });
  });
});
