/**
 * Profile sane-default values (Issue #104, Story 1.5 — FR15 downscoped).
 *
 * The empty-profile screen pre-populates these so the user can save-as-is
 * (Lurker path) or override what they want (Configurator path) — no
 * multi-step wizard.
 */

export interface ProfilePublicFieldDefaults {
  filename_template: string;
  destination_folder: string;
  auto_summary_enabled: boolean;
  auto_export_enabled: boolean;
  summary_model_id: string | null;
  summary_prompt_template: string | null;
  export_format: 'plaintext';
}

export function defaultPublicFields(documentsPath: string): ProfilePublicFieldDefaults {
  return {
    filename_template: '{date} {title}.txt',
    destination_folder: documentsPath,
    // Lurker-safe: both auto-actions OFF by default (FR30/FR31 intent)
    auto_summary_enabled: false,
    auto_export_enabled: false,
    summary_model_id: null,
    summary_prompt_template: null,
    export_format: 'plaintext',
  };
}

/**
 * Resolve the OS-default Documents path. In Electron we'd ask main for
 * `app.getPath('documents')`; in jsdom/web preview we fall back to a
 * sensible string the user will likely override.
 */
export async function resolveDocumentsPath(): Promise<string> {
  const api = window.electronAPI?.fileIO;
  if (api?.getDownloadsPath) {
    try {
      // No dedicated getDocumentsPath today; Downloads is the closest existing
      // bridge. Story 1.5 follow-up could add a getDocumentsPath IPC if needed
      // — captured in docs/dashboard/folder-picker.md cross-platform notes.
      const downloads = await api.getDownloadsPath();
      // Replace trailing 'Downloads' segment with 'Documents' as a heuristic;
      // user can always override via the folder picker.
      return downloads.replace(/Downloads\/?$/, 'Documents');
    } catch {
      return '~/Documents';
    }
  }
  return '~/Documents';
}
