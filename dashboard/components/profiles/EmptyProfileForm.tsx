/**
 * EmptyProfileForm — first-run profile-create screen (Issue #104, Story 1.5).
 *
 * Pre-populates fields with sane defaults (FR15 downscoped) and shows ONE
 * dismissible inline help banner (UX-DR2 via QueuePausedBanner primitive).
 * No multi-step wizard — Save / Cancel are the only commit actions.
 *
 * Tab order is enforced by DOM source order (no tabIndex overrides):
 *   banner-dismiss → name → description → filename template
 *   → destination folder + Choose folder button
 *   → auto-summary toggle → auto-export toggle → Save → Cancel
 */

import React, { useEffect, useId, useState } from 'react';
import { X } from 'lucide-react';

import { apiClient, type Profile } from '../../src/api/client';
import { useFolderPicker } from '../../src/hooks/useFolderPicker';
import { defaultPublicFields, resolveDocumentsPath } from '../../src/services/profileDefaults';

const BANNER_DISMISS_KEY = 'notebook.dismissedBanners.emptyProfile';

export interface EmptyProfileFormProps {
  /** Called with the newly-created profile after a successful Save. */
  onCreated: (profile: Profile) => void;
  onCancel: () => void;
  /**
   * Override the documents-path resolution — primarily used by tests and
   * by callers that already know the path (e.g. via a pre-fetched IPC value).
   */
  documentsPathOverride?: string;
}

export const EmptyProfileForm: React.FC<EmptyProfileFormProps> = ({
  onCreated,
  onCancel,
  documentsPathOverride,
}) => {
  const nameId = useId();
  const descId = useId();
  const templateId = useId();
  const destId = useId();
  const summaryId = useId();
  const exportId = useId();

  const pickFolder = useFolderPicker();

  const [name, setName] = useState<string>('Default');
  const [description, setDescription] = useState<string>('');
  const [filenameTemplate, setFilenameTemplate] = useState<string>('{date} {title}.txt');
  const [destinationFolder, setDestinationFolder] = useState<string>(documentsPathOverride ?? '');
  const [autoSummary, setAutoSummary] = useState<boolean>(false);
  const [autoExport, setAutoExport] = useState<boolean>(false);

  const [bannerVisible, setBannerVisible] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Resolve the OS Documents path on first paint (AC1).
  useEffect(() => {
    if (documentsPathOverride !== undefined) return;
    let cancelled = false;
    void resolveDocumentsPath().then((p) => {
      if (!cancelled) setDestinationFolder((cur) => (cur === '' ? p : cur));
    });
    return () => {
      cancelled = true;
    };
  }, [documentsPathOverride]);

  // Hydrate banner-visibility from electron-store (dismissal persists per AC2).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const dismissed = await window.electronAPI?.config.get(BANNER_DISMISS_KEY);
        if (!cancelled && dismissed === true) setBannerVisible(false);
      } catch {
        // bridge missing — keep default (visible)
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const dismissBanner = () => {
    setBannerVisible(false);
    void window.electronAPI?.config.set(BANNER_DISMISS_KEY, true).catch(() => undefined);
  };

  const onChooseFolder = async () => {
    const chosen = await pickFolder();
    if (chosen !== null) setDestinationFolder(chosen);
  };

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const fields = defaultPublicFields(destinationFolder);
      const created = await apiClient.createProfile({
        name: name.trim() || 'Default',
        description: description.trim() || null,
        schema_version: '1.0',
        public_fields: {
          ...fields,
          filename_template: filenameTemplate,
          destination_folder: destinationFolder,
          auto_summary_enabled: autoSummary,
          auto_export_enabled: autoExport,
        },
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create profile');
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 p-4" aria-label="Create profile">
      {bannerVisible && (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100"
        >
          <span>Edit any field below to customize, or save as-is to use the defaults.</span>
          <button
            type="button"
            onClick={dismissBanner}
            aria-label="Dismiss help banner"
            className="shrink-0 rounded p-1 hover:bg-amber-500/20 focus-visible:outline-2"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      )}

      <label className="flex flex-col gap-1 text-sm">
        <span>Name</span>
        <input
          id={nameId}
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Profile name"
          className="rounded bg-white/5 px-2 py-1"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span>Description</span>
        <input
          id={descId}
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          aria-label="Profile description"
          className="rounded bg-white/5 px-2 py-1"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span>Filename template</span>
        <input
          id={templateId}
          type="text"
          value={filenameTemplate}
          onChange={(e) => setFilenameTemplate(e.target.value)}
          aria-label="Filename template"
          className="rounded bg-white/5 px-2 py-1 font-mono"
        />
      </label>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor={destId}>Destination folder</label>
        <div className="flex gap-2">
          <input
            id={destId}
            type="text"
            readOnly
            value={destinationFolder}
            aria-label="Destination folder (read-only — use the Choose button)"
            className="flex-1 rounded bg-white/5 px-2 py-1"
          />
          <button
            type="button"
            onClick={onChooseFolder}
            aria-label="Choose destination folder"
            className="rounded bg-white/10 px-3 py-1 hover:bg-white/15"
          >
            Choose folder…
          </button>
        </div>
      </div>

      <label className="flex items-center justify-between gap-3 text-sm">
        <span>Auto-generate AI summary on completion</span>
        <input
          id={summaryId}
          type="checkbox"
          checked={autoSummary}
          onChange={(e) => setAutoSummary(e.target.checked)}
          aria-label="Auto-generate AI summary"
        />
      </label>

      <label className="flex items-center justify-between gap-3 text-sm">
        <span>Auto-export transcript on completion</span>
        <input
          id={exportId}
          type="checkbox"
          checked={autoExport}
          onChange={(e) => setAutoExport(e.target.checked)}
          aria-label="Auto-export transcript"
        />
      </label>

      {error !== null && (
        <div role="alert" className="text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded bg-white/5 px-3 py-1 hover:bg-white/10"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-cyan-500/80 px-3 py-1 text-black hover:bg-cyan-400 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  );
};
