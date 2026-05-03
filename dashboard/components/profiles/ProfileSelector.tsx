/**
 * ProfileSelector — toolbar dropdown that switches the active profile in
 * one click (Issue #104, Story 1.6).
 *
 * Hydrates from electron-store on mount (AC3 first-paint persistence).
 * Calls activeProfileStore.setActiveProfileId() on change, which writes
 * back to electron-store. Mid-session switching does NOT affect a running
 * job — that invariant lives in Story 1.3's snapshot-at-job-start helper.
 */

import React, { useEffect, useState } from 'react';

import { apiClient, type Profile } from '../../src/api/client';
import { useActiveProfileStore } from '../../src/stores/activeProfileStore';

export const ProfileSelector: React.FC = () => {
  const activeProfileId = useActiveProfileStore((s) => s.activeProfileId);
  const hydrated = useActiveProfileStore((s) => s.hydrated);
  const setActiveProfileId = useActiveProfileStore((s) => s.setActiveProfileId);
  const hydrateFromStore = useActiveProfileStore((s) => s.hydrateFromStore);

  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Hydrate from electron-store once.
  useEffect(() => {
    if (!hydrated) void hydrateFromStore();
  }, [hydrated, hydrateFromStore]);

  // Fetch the profile list once on mount (refresh on focus would be nicer
  // but is out of scope — captured as deferred polish).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await apiClient.listProfiles();
        if (!cancelled) setProfiles(list);
      } catch {
        if (!cancelled) setProfiles([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="text-xs text-slate-400" aria-live="polite">
        Loading profiles…
      </div>
    );
  }

  if (profiles.length === 0) {
    return <div className="text-xs text-slate-500">No profiles — create one in Settings.</div>;
  }

  return (
    <label className="flex items-center gap-2 text-xs text-slate-300">
      <span>Profile</span>
      <select
        value={activeProfileId ?? ''}
        onChange={(e) => {
          const v = e.target.value;
          setActiveProfileId(v === '' ? null : Number(v));
        }}
        aria-label="Active profile"
        className="rounded bg-white/5 px-2 py-1 text-xs"
      >
        <option value="">— none —</option>
        {profiles.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
};
