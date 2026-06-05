/**
 * migrateLegacyAppearanceConfig — unit tests for the GH-87 one-time migration
 * from the old combined `ui.lowIdleUsageEnabled` toggle to the independent
 * `ui.idleAnimationsEnabled` + `ui.blurEffectsEnabled` keys.
 *
 * Covers the migration rows of the spec I/O matrix: legacy-false → animations
 * ON (blur untouched), legacy-true → animations OFF + blur OFF, idempotency,
 * and the never-throw guarantee on the pre-React critical path.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { migrateLegacyAppearanceConfig } from '../migrateLegacyAppearanceConfig';

const LEGACY = 'ts-config:ui.lowIdleUsageEnabled';
const IDLE = 'ts-config:ui.idleAnimationsEnabled';
const BLUR = 'ts-config:ui.blurEffectsEnabled';

interface MockStorage {
  store: Record<string, string>;
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

function makeStorage(initial: Record<string, string> = {}): MockStorage {
  const store: Record<string, string> = { ...initial };
  return {
    store,
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => {
      store[key] = value;
    },
    removeItem: (key) => {
      delete store[key];
    },
  };
}

afterEach(() => {
  delete (globalThis as Record<string, unknown>).electronAPI;
});

describe('migrateLegacyAppearanceConfig', () => {
  it('is a no-op when no legacy key exists', () => {
    const storage = makeStorage();
    migrateLegacyAppearanceConfig(storage);
    expect(storage.store).toEqual({});
  });

  it('maps legacy false → idle animations ON, leaves blur untouched, drops legacy key', () => {
    const storage = makeStorage({ [LEGACY]: 'false' });
    migrateLegacyAppearanceConfig(storage);
    expect(storage.getItem(IDLE)).toBe('true');
    expect(storage.getItem(BLUR)).toBeNull();
    expect(storage.getItem(LEGACY)).toBeNull();
  });

  it('maps legacy true → idle animations OFF + blur OFF, drops legacy key', () => {
    const storage = makeStorage({ [LEGACY]: 'true' });
    migrateLegacyAppearanceConfig(storage);
    expect(storage.getItem(IDLE)).toBe('false');
    expect(storage.getItem(BLUR)).toBe('false');
    expect(storage.getItem(LEGACY)).toBeNull();
  });

  it('is idempotent: when already migrated, drops the stale legacy key without overwriting new keys', () => {
    const storage = makeStorage({ [LEGACY]: 'true', [IDLE]: 'true', [BLUR]: 'true' });
    migrateLegacyAppearanceConfig(storage);
    expect(storage.getItem(IDLE)).toBe('true'); // not clobbered to 'false'
    expect(storage.getItem(BLUR)).toBe('true'); // not clobbered to 'false'
    expect(storage.getItem(LEGACY)).toBeNull();
  });

  it('mirrors the migrated values to electron-store when the config bridge is present', () => {
    const set = vi.fn();
    (globalThis as Record<string, unknown>).electronAPI = { config: { set } };
    const storage = makeStorage({ [LEGACY]: 'true' });
    migrateLegacyAppearanceConfig(storage);
    expect(set).toHaveBeenCalledWith('ui.idleAnimationsEnabled', false);
    expect(set).toHaveBeenCalledWith('ui.blurEffectsEnabled', false);
  });

  it('does not throw and writes nothing on malformed legacy JSON', () => {
    const storage = makeStorage({ [LEGACY]: 'not-json' });
    expect(() => migrateLegacyAppearanceConfig(storage)).not.toThrow();
    expect(storage.getItem(IDLE)).toBeNull();
    expect(storage.getItem(BLUR)).toBeNull();
  });

  it('does not throw when storage is null', () => {
    expect(() => migrateLegacyAppearanceConfig(null)).not.toThrow();
  });

  it('does not throw when storage.getItem throws', () => {
    const storage = {
      store: {},
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    } as unknown as MockStorage;
    expect(() => migrateLegacyAppearanceConfig(storage)).not.toThrow();
  });
});
