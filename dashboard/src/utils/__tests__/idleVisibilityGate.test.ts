/**
 * idleVisibilityGate — unit tests for the always-on visibility hygiene gate
 * from spec-gh-87-low-idle-usage-toggle.md "Window hidden" row.
 *
 * The gate installs a single `visibilitychange` listener that toggles
 * `data-doc-hidden="true"` on the document element according to
 * `document.visibilityState`. It must be idempotent (calling install twice
 * registers only one listener) and must do no per-frame work.
 *
 * The module keeps a module-level "installed" flag, so each test that needs a
 * fresh install resets the module registry and re-imports it. jsdom provides
 * `document`; we stub `visibilityState` via a configurable getter.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

function dispatchVisibilityChange(): void {
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('installIdleVisibilityGate', () => {
  beforeEach(() => {
    vi.resetModules();
    delete document.documentElement.dataset.docHidden;
    setVisibility('visible');
  });

  afterEach(() => {
    delete document.documentElement.dataset.docHidden;
  });

  it('sets data-doc-hidden="true" when the document becomes hidden', async () => {
    const { installIdleVisibilityGate } = await import('../idleVisibilityGate');
    installIdleVisibilityGate();
    expect(document.documentElement.dataset.docHidden).toBeUndefined();

    setVisibility('hidden');
    dispatchVisibilityChange();
    expect(document.documentElement.dataset.docHidden).toBe('true');
  });

  it('removes data-doc-hidden when the document becomes visible again', async () => {
    const { installIdleVisibilityGate } = await import('../idleVisibilityGate');
    installIdleVisibilityGate();

    setVisibility('hidden');
    dispatchVisibilityChange();
    expect(document.documentElement.dataset.docHidden).toBe('true');

    setVisibility('visible');
    dispatchVisibilityChange();
    expect(document.documentElement.dataset.docHidden).toBeUndefined();
  });

  it('applies the current state immediately on install (starts hidden)', async () => {
    setVisibility('hidden');
    const { installIdleVisibilityGate } = await import('../idleVisibilityGate');
    installIdleVisibilityGate();
    expect(document.documentElement.dataset.docHidden).toBe('true');
  });

  it('registers only one listener even when installed twice (idempotent)', async () => {
    const addSpy = vi.spyOn(document, 'addEventListener');
    const { installIdleVisibilityGate } = await import('../idleVisibilityGate');

    installIdleVisibilityGate();
    installIdleVisibilityGate();
    installIdleVisibilityGate();

    const visibilityListeners = addSpy.mock.calls.filter(([type]) => type === 'visibilitychange');
    expect(visibilityListeners).toHaveLength(1);

    addSpy.mockRestore();
  });

  it('does not throw when document is undefined (jsdom/SSR guard)', async () => {
    // The module reads `typeof document` at call time, so temporarily hide the
    // global to exercise the guard branch without breaking other tests.
    const originalDocument = globalThis.document;
    delete (globalThis as { document?: Document }).document;
    try {
      const { installIdleVisibilityGate } = await import('../idleVisibilityGate');
      expect(() => installIdleVisibilityGate()).not.toThrow();
    } finally {
      globalThis.document = originalDocument;
    }
  });
});
