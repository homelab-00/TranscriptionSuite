/**
 * lowIdleUsageBoot — unit tests covering the I/O matrix from
 * spec-gh-87-low-idle-usage-toggle.md "First run", "Boot, stored true", and
 * the corrupt/throwing-storage edge cases.
 *
 * Unlike the Blur effects boot probe, this mode defaults OFF — the attribute
 * is only ever applied when storage holds the literal boolean `true`. Every
 * failure mode (missing storage, missing key, malformed JSON, getItem
 * throwing, any non-true value) must fall through to the documented default
 * (mode OFF, no attribute set). The function MUST never throw — bootstrap is
 * on the critical path before React mounts.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  applyLowIdleUsageBoot,
  readPersistedLowIdleUsage,
  LOW_IDLE_USAGE_STORAGE_KEY,
} from '../lowIdleUsageBoot';

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

describe('applyLowIdleUsageBoot', () => {
  let doc: MockDoc;

  beforeEach(() => {
    doc = makeDoc();
  });

  it('sets data-low-idle-usage="on" when storage holds true', () => {
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'true' });
    applyLowIdleUsageBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.lowIdleUsage).toBe('on');
  });

  it('leaves attribute unset when storage holds false', () => {
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'false' });
    applyLowIdleUsageBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('leaves attribute unset when key is absent (first run)', () => {
    const storage = makeStorage();
    applyLowIdleUsageBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('does not throw and leaves attribute unset on JSON parse failure', () => {
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'not-json' });
    expect(() => applyLowIdleUsageBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('does not throw and leaves attribute unset when storage is null', () => {
    expect(() => applyLowIdleUsageBoot(null, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('does not throw when document is null', () => {
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'true' });
    expect(() => applyLowIdleUsageBoot(storage, null)).not.toThrow();
  });

  it('does not throw and leaves attribute unset when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(() => applyLowIdleUsageBoot(storage, doc as unknown as Document)).not.toThrow();
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('treats truthy non-boolean JSON as OFF (no attribute set)', () => {
    // Defensive: only the literal boolean `true` should trigger ON.
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: '1' });
    applyLowIdleUsageBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });

  it('treats null JSON as OFF (no attribute set)', () => {
    const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'null' });
    applyLowIdleUsageBoot(storage, doc as unknown as Document);
    expect(doc.documentElement.dataset.lowIdleUsage).toBeUndefined();
  });
});

/**
 * readPersistedLowIdleUsage — used to seed SettingsModal's
 * savedLowIdleUsageRef so the modal close-branch revert agrees with the
 * attribute the boot probe applied. Default is the INVERSE of blur: false
 * (mode OFF) on every failure/missing path.
 */
describe('readPersistedLowIdleUsage', () => {
  it('returns false when key is absent', () => {
    expect(readPersistedLowIdleUsage(makeStorage())).toBe(false);
  });

  it('returns true when storage holds the literal string "true"', () => {
    expect(readPersistedLowIdleUsage(makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'true' }))).toBe(
      true,
    );
  });

  it('returns false when storage holds false', () => {
    expect(readPersistedLowIdleUsage(makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'false' }))).toBe(
      false,
    );
  });

  it('returns false when storage is null (no localStorage available)', () => {
    expect(readPersistedLowIdleUsage(null)).toBe(false);
  });

  it('returns false on JSON parse failure', () => {
    expect(
      readPersistedLowIdleUsage(makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: 'not-json' })),
    ).toBe(false);
  });

  it('returns false when storage.getItem throws', () => {
    const storage: MockStorage = {
      getItem: vi.fn(() => {
        throw new Error('storage disabled');
      }),
    };
    expect(readPersistedLowIdleUsage(storage)).toBe(false);
  });

  it('agrees with applyLowIdleUsageBoot on the same input (state-mirror invariant)', () => {
    // The whole point of the helper is that the modal can pre-seed its
    // baseline ref to whatever the boot probe set. They MUST agree.
    for (const value of ['false', 'true', 'null', '1', '0', 'not-json']) {
      const storage = makeStorage({ [LOW_IDLE_USAGE_STORAGE_KEY]: value });
      const docMock = makeDoc();
      applyLowIdleUsageBoot(storage, docMock as unknown as Document);
      const persisted = readPersistedLowIdleUsage(storage);
      // applyLowIdleUsageBoot sets attribute iff persisted === true.
      const attributeSet = docMock.documentElement.dataset.lowIdleUsage === 'on';
      expect(attributeSet).toBe(persisted);
    }
  });
});
