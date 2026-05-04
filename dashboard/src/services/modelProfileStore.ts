/**
 * Model profile storage service (Issue #104, Stories 8.1–8.4).
 *
 * Per design §0 override and AC8.1, model profiles live in **electron-store**
 * under `notebook.modelProfiles[]` and the active selection is at
 * `notebook.activeModelProfileId`. They are intentionally NOT in SQLite —
 * model selection is a dashboard-driven concern (the existing model_manager
 * config already lives in electron-store), and post-transcription profiles
 * have a separate id namespace + separate persistence layer (FR42).
 *
 * Async because the underlying electron-store IPC is async; consumers should
 * await the read/write helpers.
 */

const PROFILES_KEY = 'notebook.modelProfiles';
const ACTIVE_KEY = 'notebook.activeModelProfileId';

export interface ModelProfile {
  /** crypto.randomUUID() at create time */
  id: string;
  name: string;
  /** STT model id, e.g. "nvidia/parakeet-tdt-0.6b-v2" */
  sttModel: string;
  /** ISO-639 source language code, e.g. "en" */
  sttLanguage: string;
  /** Translation target for Canary; null for non-translating models */
  translateTarget: string | null;
  /** ISO timestamps */
  createdAt: string;
  updatedAt: string;
}

function nowIso(): string {
  return new Date().toISOString();
}

function configBridge() {
  return window.electronAPI?.config;
}

export const modelProfileStore = {
  async list(): Promise<ModelProfile[]> {
    const raw = await configBridge()?.get(PROFILES_KEY);
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (p): p is ModelProfile =>
        typeof p === 'object' &&
        p !== null &&
        typeof (p as ModelProfile).id === 'string' &&
        typeof (p as ModelProfile).name === 'string',
    );
  },

  async getActiveId(): Promise<string | null> {
    const raw = await configBridge()?.get(ACTIVE_KEY);
    return typeof raw === 'string' ? raw : null;
  },

  async setActiveId(id: string | null): Promise<void> {
    await configBridge()?.set(ACTIVE_KEY, id);
  },

  async create(input: Omit<ModelProfile, 'id' | 'createdAt' | 'updatedAt'>): Promise<ModelProfile> {
    const list = await this.list();
    const id =
      typeof crypto?.randomUUID === 'function'
        ? crypto.randomUUID()
        : `mp_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const now = nowIso();
    const next: ModelProfile = { ...input, id, createdAt: now, updatedAt: now };
    await configBridge()?.set(PROFILES_KEY, [...list, next]);
    return next;
  },

  async update(
    id: string,
    patch: Partial<Omit<ModelProfile, 'id' | 'createdAt'>>,
  ): Promise<ModelProfile | null> {
    const list = await this.list();
    let updated: ModelProfile | null = null;
    const next = list.map((p: ModelProfile) => {
      if (p.id !== id) return p;
      updated = { ...p, ...patch, updatedAt: nowIso() };
      return updated;
    });
    await configBridge()?.set(PROFILES_KEY, next);
    return updated;
  },

  async delete(id: string): Promise<boolean> {
    const list = await this.list();
    const next = list.filter((p: ModelProfile) => p.id !== id);
    if (next.length === list.length) return false;
    await configBridge()?.set(PROFILES_KEY, next);
    // If the deleted profile was active, clear the active selector.
    const active = await this.getActiveId();
    if (active === id) await this.setActiveId(null);
    return true;
  },
};
