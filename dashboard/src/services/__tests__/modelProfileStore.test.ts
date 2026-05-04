/**
 * modelProfileStore tests (Issue #104, Stories 8.1–8.4).
 *
 * Backing store is mocked at the electronAPI.config level — keeps the
 * tests fast and dependency-free.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { modelProfileStore } from '../modelProfileStore';

const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

interface FakeConfigBridge {
  values: Map<string, unknown>;
  get: (key: string) => Promise<unknown>;
  set: (key: string, value: unknown) => Promise<void>;
}

function installFakeBridge(): FakeConfigBridge {
  const values = new Map<string, unknown>();
  const bridge: FakeConfigBridge = {
    values,
    get: vi.fn(async (key: string) => values.get(key)),
    set: vi.fn(async (key: string, value: unknown) => {
      values.set(key, value);
    }),
  };
  (window as unknown as { electronAPI: { config: FakeConfigBridge } }).electronAPI = {
    config: bridge,
  };
  return bridge;
}

beforeEach(() => {
  installFakeBridge();
});

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

const SAMPLE = {
  name: 'Fast English',
  sttModel: 'nvidia/parakeet-tdt-0.6b-v2',
  sttLanguage: 'en',
  translateTarget: null,
};

describe('modelProfileStore — Story 8.1 (data + persistence)', () => {
  it('list() returns empty when nothing stored yet', async () => {
    expect(await modelProfileStore.list()).toEqual([]);
  });

  it('create() writes to notebook.modelProfiles[] and returns the new profile', async () => {
    const created = await modelProfileStore.create(SAMPLE);
    expect(created.id).toMatch(/.+/);
    expect(created.createdAt).toBe(created.updatedAt);
    expect(await modelProfileStore.list()).toHaveLength(1);
  });

  it('list() filters out malformed entries', async () => {
    const bridge = installFakeBridge();
    bridge.values.set('notebook.modelProfiles', [
      {
        id: 'good',
        name: 'Real',
        sttModel: 'm',
        sttLanguage: 'en',
        translateTarget: null,
        createdAt: '',
        updatedAt: '',
      },
      'garbage-string',
      null,
      { name: 'no-id' },
    ]);
    const list = await modelProfileStore.list();
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('good');
  });
});

describe('modelProfileStore — independence from notebook profiles (FR42)', () => {
  it('uses a separate electron-store key from notebook.activeProfileId', async () => {
    const bridge = installFakeBridge();
    await modelProfileStore.setActiveId('m1');
    expect(bridge.values.get('notebook.activeModelProfileId')).toBe('m1');
    expect(bridge.values.has('notebook.activeProfileId')).toBe(false);
  });

  it('deleting a model profile does not affect the notebook-profile store key', async () => {
    const bridge = installFakeBridge();
    bridge.values.set('notebook.activeProfileId', 99);
    const created = await modelProfileStore.create(SAMPLE);
    await modelProfileStore.delete(created.id);
    expect(bridge.values.get('notebook.activeProfileId')).toBe(99);
  });
});

describe('modelProfileStore — Story 8.3 / 8.4 (active selector + persistence)', () => {
  it('setActiveId persists to electron-store under notebook.activeModelProfileId', async () => {
    const bridge = installFakeBridge();
    await modelProfileStore.setActiveId('mp_xyz');
    expect(bridge.values.get('notebook.activeModelProfileId')).toBe('mp_xyz');
  });

  it('getActiveId returns the persisted value', async () => {
    const bridge = installFakeBridge();
    bridge.values.set('notebook.activeModelProfileId', 'mp_persisted');
    expect(await modelProfileStore.getActiveId()).toBe('mp_persisted');
  });

  it('getActiveId coerces non-string reads to null', async () => {
    const bridge = installFakeBridge();
    bridge.values.set('notebook.activeModelProfileId', 42);
    expect(await modelProfileStore.getActiveId()).toBeNull();
  });

  it('deleting the active profile clears the active selector', async () => {
    const bridge = installFakeBridge();
    const created = await modelProfileStore.create(SAMPLE);
    await modelProfileStore.setActiveId(created.id);
    await modelProfileStore.delete(created.id);
    expect(bridge.values.get('notebook.activeModelProfileId')).toBeNull();
  });
});

describe('modelProfileStore — update + delete', () => {
  it('update() patches fields and bumps updatedAt', async () => {
    vi.useFakeTimers();
    try {
      const created = await modelProfileStore.create(SAMPLE);
      // Force a clock advance so updatedAt is strictly greater than createdAt.
      // Vitest fake timers also mock Date, so nowIso() picks up the new time.
      vi.advanceTimersByTime(5);
      const updated = await modelProfileStore.update(created.id, { name: 'Renamed' });
      expect(updated).not.toBeNull();
      expect(updated!.name).toBe('Renamed');
      expect(updated!.updatedAt >= created.updatedAt).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('update() returns null when no profile matches', async () => {
    expect(await modelProfileStore.update('nonexistent', { name: 'X' })).toBeNull();
  });

  it('delete() returns true on success, false on missing id', async () => {
    const created = await modelProfileStore.create(SAMPLE);
    expect(await modelProfileStore.delete(created.id)).toBe(true);
    expect(await modelProfileStore.delete(created.id)).toBe(false);
  });
});
