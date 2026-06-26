/**
 * idleAnimationsBoot — unit tests for the GH-87 "Idle animations" boot probe.
 *
 * Defaults OFF (GH #87): the idle wave animations continuously force the
 * compositor/main-thread to repaint (~85% CPU / ~32% GPU at idle on Apple
 * Silicon), so `data-idle-animations="off"` is applied by default and ONLY the
 * explicit literal boolean `true` (a deliberate Settings opt-in) leaves the
 * animations running. Every other value/failure mode (missing storage, missing
 * key, malformed JSON, getItem throwing, any non-true value) falls through to
 * the default OFF (attribute set). The function MUST never throw — bootstrap
 * runs before React mounts.
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

  it('leaves attribute unset only when storage holds the explicit true opt-in', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'true' });
    applyIdleAnimationsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.idleAnimations).toBeUndefined();
  });

  it('sets off when key is absent (first run, default OFF)', () => {
    const storage = makeStorage();
    applyIdleAnimationsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.idleAnimations).toBe('off');
  });

  it('does not throw and sets off (default) on JSON parse failure', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'not-json' });
    expect(() => applyIdleAnimationsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBe('off');
  });

  it('does not throw and sets off (default) when storage is null', () => {
    expect(() => applyIdleAnimationsBoot(null, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBe('off');
  });

  it('does not throw when document is null', () => {
    const storage = makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'false' });
    expect(() => applyIdleAnimationsBoot(storage, null)).not.toThrow();
  });

  it('does not throw and sets off (default) when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(() => applyIdleAnimationsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.idleAnimations).toBe('off');
  });

  it('treats non-true JSON values as OFF (attribute set)', () => {
    // Only the literal boolean `true` should leave animations running.
    for (const value of ['1', '0', 'null', '"on"']) {
      const docMock = makeDoc();
      applyIdleAnimationsBoot(
        makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: value }),
        docMock as unknown as Document,
      );
      expect(docMock.documentElement.dataset.idleAnimations).toBe('off');
    }
  });
});

/**
 * readPersistedIdleAnimations — used to seed SettingsModal's
 * savedIdleAnimationsRef so the modal close-branch revert agrees with the
 * attribute the boot probe applied. Default false (animations OFF) on every
 * failure/missing path; true only for the explicit literal boolean `true`.
 */
describe('readPersistedIdleAnimations', () => {
  it('returns false when key is absent (default OFF)', () => {
    expect(readPersistedIdleAnimations(makeStorage())).toBe(false);
  });

  it('returns false when storage holds the literal string "false"', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'false' })),
    ).toBe(false);
  });

  it('returns true only when storage holds the explicit true opt-in', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'true' })),
    ).toBe(true);
  });

  it('returns false when storage is null (no localStorage available)', () => {
    expect(readPersistedIdleAnimations(null)).toBe(false);
  });

  it('returns false on JSON parse failure', () => {
    expect(
      readPersistedIdleAnimations(makeStorage({ [IDLE_ANIMATIONS_STORAGE_KEY]: 'not-json' })),
    ).toBe(false);
  });

  it('returns false when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(readPersistedIdleAnimations(storage)).toBe(false);
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
