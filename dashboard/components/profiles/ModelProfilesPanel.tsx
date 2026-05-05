/**
 * ModelProfilesPanel — Settings UI for managing model profiles
 * (Issue #104, Story 8.2).
 *
 * Renders a list of model profiles + an inline edit form. Mountable as
 * a Settings tab once the host modal is ready to consume it.
 *
 * Field set per AC8.2:
 *   - name (text)
 *   - STT model (dropdown of available models)
 *   - STT language (dropdown of available languages)
 *   - Translate target (dropdown — Canary translation targets only)
 *
 * Accessibility (FR51, FR53): descriptive aria-labels via a11yLabels;
 * native <select> for keyboard-friendly dropdowns; tab order is DOM order.
 */

import React, { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';

import { Button } from '../ui/Button';
import { modelProfileStore, type ModelProfile } from '../../src/services/modelProfileStore';

interface FormState {
  id: string | null;
  name: string;
  sttModel: string;
  sttLanguage: string;
  translateTarget: string;
}

const EMPTY_FORM: FormState = {
  id: null,
  name: '',
  sttModel: '',
  sttLanguage: 'en',
  translateTarget: '',
};

export interface ModelProfilesPanelProps {
  /** STT model ids the user can pick from (sourced from existing model registry). */
  availableModels: ReadonlyArray<{ id: string; label: string }>;
  /** ISO-639 language codes the user can pick from (sourced from existing language list). */
  availableLanguages: ReadonlyArray<{ code: string; label: string }>;
  /**
   * Translation-target options — populated only for STT models that support
   * translation (Canary). Pass an empty array to disable the dropdown.
   */
  translationTargets: ReadonlyArray<{ code: string; label: string }>;
}

export const ModelProfilesPanel: React.FC<ModelProfilesPanelProps> = ({
  availableModels,
  availableLanguages,
  translationTargets,
}) => {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const refresh = async () => {
    setProfiles(await modelProfileStore.list());
  };

  useEffect(() => {
    void (async () => {
      await refresh();
      setLoading(false);
    })();
  }, []);

  const startNew = () => setForm({ ...EMPTY_FORM });

  const startEdit = (p: ModelProfile) =>
    setForm({
      id: p.id,
      name: p.name,
      sttModel: p.sttModel,
      sttLanguage: p.sttLanguage,
      translateTarget: p.translateTarget ?? '',
    });

  const cancel = () => setForm(null);

  const save = async () => {
    if (form === null) return;
    const payload = {
      name: form.name.trim(),
      sttModel: form.sttModel,
      sttLanguage: form.sttLanguage,
      translateTarget: form.translateTarget === '' ? null : form.translateTarget,
    };
    if (form.id === null) {
      await modelProfileStore.create(payload);
    } else {
      await modelProfileStore.update(form.id, payload);
    }
    setForm(null);
    await refresh();
  };

  const remove = async (id: string) => {
    await modelProfileStore.delete(id);
    await refresh();
  };

  if (loading) return <div className="text-sm text-slate-400">Loading model profiles…</div>;

  return (
    <section className="flex flex-col gap-4" aria-label="Model profiles">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Model profiles</h3>
        {form === null && (
          <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={startNew}>
            New profile
          </Button>
        )}
      </header>

      {profiles.length === 0 && form === null && (
        <p className="text-xs text-slate-500">
          No model profiles yet. Create one to switch between STT models in one click.
        </p>
      )}

      <ul className="flex flex-col gap-2" aria-label="Existing model profiles">
        {profiles.map((p) => (
          <li
            key={p.id}
            className="flex items-center justify-between rounded bg-white/5 px-3 py-2 text-sm"
          >
            <div className="flex flex-col">
              <span className="font-medium text-slate-100">{p.name}</span>
              <span className="text-xs text-slate-400">
                {p.sttModel} · {p.sttLanguage}
                {p.translateTarget !== null ? ` → ${p.translateTarget}` : ''}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => startEdit(p)}
                aria-label={`Edit model profile "${p.name}"`}
                className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => void remove(p.id)}
                aria-label={`Delete model profile "${p.name}"`}
                className="rounded bg-red-500/20 px-2 py-1 text-xs text-red-200 hover:bg-red-500/30"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {form !== null && (
        <form
          onSubmit={(e: React.FormEvent<HTMLFormElement>) => {
            e.preventDefault();
            void save();
          }}
          className="flex flex-col gap-3 rounded border border-white/10 bg-white/5 p-3"
          aria-label={form.id === null ? 'Create model profile' : 'Edit model profile'}
        >
          <label className="flex flex-col gap-1 text-xs">
            <span>Profile name</span>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              aria-label="Model profile name"
              required
              className="rounded bg-white/5 px-2 py-1 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1 text-xs">
            <span>Speech-to-text model</span>
            <select
              value={form.sttModel}
              onChange={(e) => setForm({ ...form, sttModel: e.target.value })}
              aria-label="Speech-to-text model"
              required
              className="rounded bg-white/5 px-2 py-1 text-sm"
            >
              <option value="">— select model —</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs">
            <span>Source language</span>
            <select
              value={form.sttLanguage}
              onChange={(e) => setForm({ ...form, sttLanguage: e.target.value })}
              aria-label="Source language"
              className="rounded bg-white/5 px-2 py-1 text-sm"
            >
              {availableLanguages.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>

          {translationTargets.length > 0 && (
            <label className="flex flex-col gap-1 text-xs">
              <span>Translation target language (optional)</span>
              <select
                value={form.translateTarget}
                onChange={(e) => setForm({ ...form, translateTarget: e.target.value })}
                aria-label="Translation target language"
                className="rounded bg-white/5 px-2 py-1 text-sm"
              >
                <option value="">— none —</option>
                {translationTargets.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={cancel}
              className="rounded bg-white/5 px-3 py-1 text-xs hover:bg-white/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded bg-cyan-500/80 px-3 py-1 text-xs text-black hover:bg-cyan-400"
            >
              Save
            </button>
          </div>
        </form>
      )}
    </section>
  );
};
