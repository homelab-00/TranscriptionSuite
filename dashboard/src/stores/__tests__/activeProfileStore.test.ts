/**
 * activeProfileStore tests (Issue #104, Story 1.6).
 *
 * Covers:
 *  - AC1 selector switches active profile (in-memory)
 *  - AC1 persists to electron-store key 'notebook.activeProfileId'
 *  - AC3 hydration on first paint (read from electron-store)
 *  - graceful degradation when electronAPI bridge is missing
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useActiveProfileStore } from '../activeProfileStore';

const STORE_KEY = 'notebook.activeProfileId';
const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

interface MockBridge {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
}

function installBridge(bridge: MockBridge) {
  (window as unknown as { electronAPI: { config: MockBridge } }).electronAPI = {
    config: bridge,
  };
}

beforeEach(() => {
  // Reset the in-memory store between tests so they don't bleed.
  useActiveProfileStore.setState({ activeProfileId: null, hydrated: false });
});

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

describe('activeProfileStore', () => {
  it('setActiveProfileId updates in-memory state', () => {
    useActiveProfileStore.getState().setActiveProfileId(7);
    expect(useActiveProfileStore.getState().activeProfileId).toBe(7);
  });

  it('setActiveProfileId persists to electron-store under notebook.activeProfileId', () => {
    const bridge: MockBridge = {
      get: vi.fn().mockResolvedValue(null),
      set: vi.fn().mockResolvedValue(undefined),
    };
    installBridge(bridge);

    useActiveProfileStore.getState().setActiveProfileId(42);
    expect(bridge.set).toHaveBeenCalledWith(STORE_KEY, 42);
  });

  it('setActiveProfileId(null) writes null (clears the active selection)', () => {
    const bridge: MockBridge = {
      get: vi.fn().mockResolvedValue(null),
      set: vi.fn().mockResolvedValue(undefined),
    };
    installBridge(bridge);

    useActiveProfileStore.getState().setActiveProfileId(null);
    expect(bridge.set).toHaveBeenCalledWith(STORE_KEY, null);
  });

  it('hydrateFromStore reads electron-store and populates state', async () => {
    const bridge: MockBridge = {
      get: vi.fn().mockResolvedValue(99),
      set: vi.fn().mockResolvedValue(undefined),
    };
    installBridge(bridge);

    await useActiveProfileStore.getState().hydrateFromStore();
    expect(bridge.get).toHaveBeenCalledWith(STORE_KEY);
    expect(useActiveProfileStore.getState().activeProfileId).toBe(99);
    expect(useActiveProfileStore.getState().hydrated).toBe(true);
  });

  it('hydrateFromStore coerces non-number reads to null', async () => {
    const bridge: MockBridge = {
      get: vi.fn().mockResolvedValue('garbage'),
      set: vi.fn().mockResolvedValue(undefined),
    };
    installBridge(bridge);

    await useActiveProfileStore.getState().hydrateFromStore();
    expect(useActiveProfileStore.getState().activeProfileId).toBeNull();
    expect(useActiveProfileStore.getState().hydrated).toBe(true);
  });

  it('hydrateFromStore marks hydrated=true when bridge is missing (no infinite wait)', async () => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    await useActiveProfileStore.getState().hydrateFromStore();
    expect(useActiveProfileStore.getState().hydrated).toBe(true);
    expect(useActiveProfileStore.getState().activeProfileId).toBeNull();
  });

  it('setActiveProfileId does not throw when electronAPI is missing', () => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    expect(() => useActiveProfileStore.getState().setActiveProfileId(5)).not.toThrow();
    expect(useActiveProfileStore.getState().activeProfileId).toBe(5);
  });
});
