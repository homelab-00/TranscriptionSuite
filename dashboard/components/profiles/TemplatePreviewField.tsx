/**
 * TemplatePreviewField — live filename preview for the profile editor
 * (Issue #104, Story 3.3).
 *
 * AC contract:
 *   - AC1: preview updates on every keystroke against a fixed sample
 *   - AC2: synchronous render — p95 < 50 ms (no debounce needed)
 *   - AC3: invalid template surfaces inline; parent disables Save via
 *     `onValidityChange`.
 */

import { useEffect, useMemo } from 'react';

import {
  PREVIEW_SAMPLE,
  findUnknownPlaceholders,
  renderTemplate,
} from '../../src/utils/filenameTemplate';

export interface TemplatePreviewFieldProps {
  template: string;
  onTemplateChange: (next: string) => void;
  onValidityChange?: (valid: boolean) => void;
  /**
   * If set, render the Story 3.6 AC1 sticky-OK notice below the preview.
   * Defaults to false; the parent controls whether the notice has been
   * acknowledged this session.
   */
  showForwardOnlyNotice?: boolean;
  onAckForwardOnly?: () => void;
}

export function TemplatePreviewField({
  template,
  onTemplateChange,
  onValidityChange,
  showForwardOnlyNotice = false,
  onAckForwardOnly,
}: TemplatePreviewFieldProps) {
  const unknown = useMemo(() => findUnknownPlaceholders(template), [template]);
  const isValid = unknown.length === 0;
  const preview = useMemo(
    () => (isValid ? renderTemplate(template, PREVIEW_SAMPLE) : ''),
    [template, isValid],
  );

  useEffect(() => {
    onValidityChange?.(isValid);
  }, [isValid, onValidityChange]);

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="profile-filename-template" className="text-xs font-medium text-slate-300">
        Filename template
      </label>
      <input
        id="profile-filename-template"
        type="text"
        value={template}
        onChange={(e) => onTemplateChange(e.target.value)}
        className="rounded-md border border-white/10 bg-black/20 px-3 py-2 text-sm text-white"
        aria-label="Filename template"
        aria-invalid={!isValid}
        aria-describedby="profile-filename-preview"
      />
      <p
        id="profile-filename-preview"
        className={`text-xs ${isValid ? 'text-slate-400' : 'text-red-400'}`}
      >
        {isValid ? (
          <>
            <span className="font-medium">Preview:</span> {preview}
          </>
        ) : (
          <>
            <span className="font-medium">Invalid:</span> unknown placeholder{' '}
            {unknown.map((p) => `{${p}}`).join(', ')}
          </>
        )}
      </p>
      {showForwardOnlyNotice && (
        <div
          role="status"
          aria-live="polite"
          className="mt-2 flex items-start gap-2 rounded-md border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-xs text-amber-200"
        >
          <span aria-hidden="true">ⓘ</span>
          <div className="flex-1">
            This template applies to future transcriptions. Existing transcripts on disk keep their
            current names. To re-export old recordings with the new template, use the Re-export
            action in the recording context menu.
          </div>
          {onAckForwardOnly && (
            <button
              type="button"
              onClick={onAckForwardOnly}
              className="rounded-sm bg-amber-400/10 px-2 py-1 text-xs font-medium hover:bg-amber-400/20"
            >
              OK
            </button>
          )}
        </div>
      )}
    </div>
  );
}
