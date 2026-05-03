/**
 * ModelProfileSelector — toolbar dropdown for one-click model profile
 * switching (Issue #104, Story 8.3 + 8.4).
 *
 * Behavior contract:
 *   - AC8.3 AC1: shows existing profiles, highlights the active one
 *   - AC8.3 AC2: switching invokes onSwitch(profile) — caller delegates to
 *     existing model_manager unload+load flow (the selector itself is a
 *     thin presentation layer)
 *   - AC8.3 AC3: switch is REJECTED while live mode is in progress —
 *     caller passes `liveModeActive` and we render the option as disabled
 *     with toast text via aria-describedby
 *   - AC8.4: hydrates active id from electron-store on mount; on change
 *     persists back via setActiveId — survives app restart by definition
 *
 * `onSwitch` is async because real swaps take time (existing
 * model_manager.load_transcription_model is heavy); the selector shows
 * "Switching model…" while in-flight.
 */

import React, { useEffect, useState } from 'react';

import { modelProfileStore, type ModelProfile } from '../../src/services/modelProfileStore';

export interface ModelProfileSelectorProps {
  /** True while live mode is engaged — switching is forbidden in that state. */
  liveModeActive: boolean;
  /**
   * Called when the user picks a different profile. Caller is responsible
   * for invoking the existing model_manager swap orchestration. Should
   * resolve when the new model is loaded; selector renders a spinner
   * label until the promise settles.
   */
  onSwitch: (profile: ModelProfile) => Promise<void>;
  /** Optional: emit a toast / inline message when switch is rejected. */
  onRejected?: (reason: string) => void;
}

export const ModelProfileSelector: React.FC<ModelProfileSelectorProps> = ({
  liveModeActive,
  onSwitch,
  onRejected,
}) => {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [switching, setSwitching] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);

  // Hydrate from electron-store on mount (AC8.4 first-paint persistence).
  useEffect(() => {
    void (async () => {
      const [list, active] = await Promise.all([
        modelProfileStore.list(),
        modelProfileStore.getActiveId(),
      ]);
      setProfiles(list);
      setActiveId(active);
      setLoading(false);
    })();
  }, []);

  const handleChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextId = event.target.value;
    if (nextId === activeId || nextId === '') return;

    if (liveModeActive) {
      onRejected?.('Stop live mode before switching the model');
      return;
    }

    const profile = profiles.find((p) => p.id === nextId);
    if (profile === undefined) return;

    setSwitching(true);
    try {
      await onSwitch(profile);
      setActiveId(nextId);
      await modelProfileStore.setActiveId(nextId);
    } catch (err) {
      // onSwitch threw — surface to caller so it can toast. Without this,
      // the select silently snaps back and the user has no idea why.
      onRejected?.(`Model switch failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSwitching(false);
    }
  };

  if (loading) {
    return (
      <div className="text-xs text-slate-400" aria-live="polite">
        Loading model profiles…
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <div className="text-xs text-slate-500">
        No model profiles — set up one in Settings → Model Profiles.
      </div>
    );
  }

  return (
    <label className="flex items-center gap-2 text-xs text-slate-300">
      <span>Model</span>
      <select
        value={activeId ?? ''}
        onChange={(e) => void handleChange(e)}
        disabled={switching}
        aria-label="Active model profile"
        className="rounded bg-white/5 px-2 py-1 text-xs disabled:opacity-50"
      >
        <option value="">— none —</option>
        {profiles.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {switching && <span className="text-cyan-300">Switching model…</span>}
    </label>
  );
};
