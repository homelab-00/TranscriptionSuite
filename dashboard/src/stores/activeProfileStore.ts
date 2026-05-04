/**
 * Active-profile store (Issue #104, Story 1.6).
 *
 * Holds the active profile id; persists to electron-store under the
 * `notebook.activeProfileId` key so the choice survives app restart
 * (FR20). Hydration is explicit — the App init hook calls
 * `hydrateFromStore()` once on first paint.
 *
 * Mid-session edits to the active profile do NOT affect any running job
 * — that invariant is owned by Story 1.3's snapshot-at-job-start helper
 * (the worker uses the snapshot tuple, never live profile state).
 */

import { create } from 'zustand';

const STORE_KEY = 'notebook.activeProfileId';

interface ActiveProfileState {
  activeProfileId: number | null;
  hydrated: boolean;
  setActiveProfileId: (id: number | null) => void;
  hydrateFromStore: () => Promise<void>;
}

export const useActiveProfileStore = create<ActiveProfileState>((set) => ({
  activeProfileId: null,
  hydrated: false,

  setActiveProfileId: (id) => {
    set({ activeProfileId: id });
    // Best-effort persist; storage failures should not crash the renderer.
    void window.electronAPI?.config.set(STORE_KEY, id).catch(() => undefined);
  },

  hydrateFromStore: async () => {
    try {
      const raw = await window.electronAPI?.config.get(STORE_KEY);
      // electron-store returns whatever was last written; coerce to number-or-null.
      const next = typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
      set({ activeProfileId: next, hydrated: true });
    } catch {
      // No bridge / read failure: leave the in-memory default and mark hydrated
      // so consumers stop waiting.
      set({ hydrated: true });
    }
  },
}));
