/**
 * idleAnimationsBoot — unit tests for the GH-87 "Idle animations" boot probe.
 *
 * Unlike the old combined "Low idle usage" mode, this defaults ON and is
 * INDEPENDENT of blur: the `data-idle-animations="off"` attribute is applied
 * only when storage holds the literal boolean `false`. Every failure mode
 * (missing storage, missing key, malformed JSON, getItem throwing, any
 * non-false value) must fall through to the documented default (animations
 * ON, no attribute). The function MUST never throw — bootstrap runs before
 * React mounts.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  applyIdleAnimationsBoot,
  readPersistedIdleAnimations,
  IDLE_ANIMATIONS_STORAGE_KEY,
} from '../idleAnimationsBoot';

interface MockStorage {
  getItem: (key: string) => string | null;
}

interface MockDoc {
  documentElement: { dataset: Record<string, string> };
}

function makeStorage(initial: Record<string, string> = {}): MockStorage {
  const map: Record<string, string> = { ...initial };
  return {
    getItem: (key: string) => (key in map ? map[key] : null),
  };
}

function makeDoc(): MockDoc {
  return { documentElement: { dataset: {} } };
}

describe('applyIdleAnimationsBoot', () => {
  let doc: MockDoc;

  beforeEach(() => {
    doc = makeDoc();
  });

  it('sets data-idle-animations="off" when storage holds false', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'false' });
    applyIdleAnimationsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.idleAnimations).toBe('off');
  });

  it('leaves attribute unset when storage holds true', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'true' });
    applyIdleAnimationsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('leaves attribute unset when key is absent (first run, default ON)', () => {
    const storage = makeStorage();
    applyIdleAnimationsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('does not throw and leaves attribute unset on JSON parse failure', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'not-json' });
    expect(() => applyIdleAnimationsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('does not throw and leaves attribute unset when storage is null', () => {
    expect(() => applyIdleAnimationsBoot(null, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('does not throw when document is null', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'false' });
    expect(() => applyIdleAnimationsBoot(storage, null)).not.toThrow();
  });

  it('does not throw and leaves attribute unset when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(() => applyIdleAnimationsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('treats non-false JSON values as ON (no attribute set)', () => {
    // Only the literal boolean `false` should freeze animations.
    for (const value of ['1', '0', 'null', '"off"']) {
      const docMock = makeDoc();
      applyIdleAnimationsBoot(
        makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: value }),
        docMock as unknown as Document,
      );
      expect(docMock.documentElement.dataset.idleAnimations).toBeUndefined();
    }
  });
});

/**
 * readPersistedIdleAnimations — used to seed SettingsModal's
 * savedIdleAnimationsRef so the modal close-branch revert agrees with the
 * attribute the boot probe applied. Default true (animations ON) on every
 * failure/missing path; false only for the literal boolean `false`.
 */
describe('readPersistedIdleAnimations', () => {
  it('returns true when key is absent', () => {
    expect(readPersistedIdleAnimations(makeStorage())).toBe(true);
  });

  it('returns false when storage holds the literal string "false"', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'false' })),
    ).toBe(false);
  });

  it('returns true when storage holds true', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'true' })),
    ).toBe(true);
  });

  it('returns true when storage is null (no localStorage available)', () => {
    expect(readPersistedIdleAnimations(null)).toBe(true);
  });

  it('returns true on JSON parse failure', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'not-json' })),
    ).toBe(true);
  });

  it('returns true when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(readPersistedIdleAnimations(storage)).toBe(true);
  });

  it('agrees with applyIdleAnimationsBoot on the same input (state-mirror invariant)', () => {
    for (const value of ['false', 'true', 'null', '1', '0', 'not-json']) {
      const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: value });
      const docMock = makeDoc();
      applyIdleAnimationsBoot(storage, docMock as unknown as Document);
      const persisted = readPersistedIdleAnimations(storage);
      // applyIdleAnimationsBoot sets attribute iff persisted === false.
      const attributeSet = docMock.documentElement.dataset.idleAnimations === 'off';
      expect(attributeSet).toBe(!persisted);
    }
  });
});
