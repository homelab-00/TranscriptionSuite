/**
 * blurEffectsBoot — unit tests covering the I/O matrix from
 * spec-gh-87-blur-effects-toggle.md "First-ever launch", "App relaunch
 * after OFF", and the bootstrap-error-tolerance constraint.
 *
 * The function MUST never throw — bootstrap is on the critical path
 * before React mounts. Storage access can fail in many ways
 * (private-browsing quota, disabled localStorage, malformed JSON
 * written by an external tool, missing globals during SSR-style
 * pre-rendering). All of those branches must fall through to the
 * documented default (blur ON, no attribute set).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  applyBlurEffectsBoot,
  readPersistedBlurEffects,
  BLUR_EFFECTS_STORAGE_KEY,
} from '../blurEffectsBoot';

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

describe('applyBlurEffectsBoot', () => {
  let doc: MockDoc;

  beforeEach(() => {
    doc = makeDoc();
  });

  it('sets data-blur-effects="off" when storage holds false', () => {
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'false' });
    applyBlurEffectsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.blurEffects).toBe('off');
  });

  it('leaves attribute unset when storage holds true', () => {
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'true' });
    applyBlurEffectsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('leaves attribute unset when key is absent (first-ever launch)', () => {
    const storage = makeStorage();
    applyBlurEffectsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('does not throw and leaves attribute unset on JSON parse failure', () => {
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'not-json' });
    expect(() => applyBlurEffectsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('does not throw and leaves attribute unset when storage is null', () => {
    expect(() => applyBlurEffectsBoot(null, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('does not throw and leaves attribute unset when document is null', () => {
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'false' });
    expect(() => applyBlurEffectsBoot(storage, null)).not.toThrow();
  });

  it('does not throw when storage.getItem itself throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(() => applyBlurEffectsBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('treats truthy non-boolean JSON as ON (no attribute set)', () => {
    // Defensive: any value other than literal `false` should NOT trigger OFF.
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: '1' });
    applyBlurEffectsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });

  it('treats null JSON as ON (no attribute set)', () => {
    const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'null' });
    applyBlurEffectsBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.blurEffects).toBeUndefined();
  });
});

/**
 * readPersistedBlurEffects — used to seed SettingsModal's savedBlurEffectsRef
 * so the modal's close-branch revert agrees with the attribute the boot probe
 * applied. Without that agreement, the modal's first effect tick (with the
 * always-mounted modal at App.tsx, isOpen=false on first render) would clobber
 * the boot probe by deleting data-blur-effects=off, defeating AC3.
 */
describe('readPersistedBlurEffects', () => {
  it('returns true when key is absent', () => {
    expect(readPersistedBlurEffects(makeStorage())).toBe(true);
  });

  it('returns false when storage holds the literal string "false"', () => {
    expect(readPersistedBlurEffects(makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'false' }))).toBe(
      false,
    );
  });

  it('returns true when storage holds true', () => {
    expect(readPersistedBlurEffects(makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'true' }))).toBe(
      true,
    );
  });

  it('returns true when storage is null (no localStorage available)', () => {
    expect(readPersistedBlurEffects(null)).toBe(true);
  });

  it('returns true on JSON parse failure', () => {
    expect(readPersistedBlurEffects(makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: 'not-json' }))).toBe(
      true,
    );
  });

  it('returns true when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(readPersistedBlurEffects(storage)).toBe(true);
  });

  it('agrees with applyBlurEffectsBoot on the same input (state-mirror invariant)', () => {
    // The whole point of the helper is that the modal can pre-seed its
    // baseline ref to whatever the boot probe set. They MUST agree.
    for (const value of ['false', 'true', 'null', '1', '0', 'not-json']) {
      const storage = makeStorage({ [BLUR_EFFECTS_STORAGE_KEY]: value });
      const docMock = makeDoc();
      applyBlurEffectsBoot(storage, docMock as unknown as Document);
      const persisted = readPersistedBlurEffects(storage);
      // applyBlurEffectsBoot sets attribute iff persisted === false.
      const attributeSet = docMock.documentElement.dataset.blurEffects === 'off';
      expect(attributeSet).toBe(!persisted);
    }
  });
});
