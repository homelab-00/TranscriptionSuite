/**
 * Salvage coordination store (GH-239 follow-up).
 *
 * Glue between the salvage progress monitor (useSalvageProgress) and the
 * parts of the app that learn about salvages first:
 *   - checkNonce: bumped to request an immediate /api/status check
 *     (session_busy with is_salvage, unexpected socket close).
 *   - dropRequestedJobId: set by the SessionView popup before it cancels a
 *     salvage, so the monitor renders "stopped" instead of probing outcome.
 *   - lastCompletedAt: stamped when a salvage ends; SessionView refreshes
 *     the recovery banner on change.
 */

import { create } from 'zustand';

interface SalvageStoreState {
  checkNonce: number;
  dropRequestedJobId: string | null;
  lastCompletedAt: number | null;
  requestCheck: () => void;
  markDropRequested: (jobId: string) => void;
  clearDropRequested: () => void;
  markSalvageEnded: () => void;
}

export const useSalvageStore = create<SalvageStoreState>((set) => ({
  checkNonce: 0,
  dropRequestedJobId: null,
  lastCompletedAt: null,
  requestCheck: () => set((s) => ({ checkNonce: s.checkNonce + 1 })),
  markDropRequested: (jobId) => set({ dropRequestedJobId: jobId }),
  clearDropRequested: () => set({ dropRequestedJobId: null }),
  markSalvageEnded: () => set({ lastCompletedAt: Date.now() }),
}));
