/**
 * A single editable prompt in Settings → AI (GH-254).
 *
 * Shared by the summary, chat and title prompts so all three are identical by
 * construction: label row with a Reset affordance, helper text, and a textarea
 * that opts into .custom-scrollbar. The title prompt predates this component
 * and had none of that — long prompts rendered a chunky native scrollbar that
 * did not match the rest of the app.
 *
 * defaultValue is supplied by the server (GET /api/llm/status) rather than
 * hardcoded here, so Reset can never drift from the backend fallback.
 */

import React from 'react';
import { RotateCw } from 'lucide-react';
import { Button } from '../../ui/Button';

interface PromptFieldProps {
  /** DOM id, used to tie the label to the textarea. */
  id: string;
  label: string;
  helpText: string;
  value: string;
  defaultValue: string;
  onChange: (value: string) => void;
  /** Visible rows. Longer prompts get more room; styling is unchanged. */
  rows?: number;
}

export const PromptField: React.FC<PromptFieldProps> = ({
  id,
  label,
  helpText,
  value,
  defaultValue,
  onChange,
  rows = 4,
}) => (
  <div>
    <div className="mb-2 flex items-center justify-between gap-3">
      <label htmlFor={id} className="text-sm text-slate-200">
        {label}
      </label>
      <Button
        variant="secondary"
        size="sm"
        icon={<RotateCw size={14} />}
        aria-label={`Reset ${label} to default`}
        onClick={() => onChange(defaultValue)}
      >
        Reset to default
      </Button>
    </div>
    <p className="mb-3 text-xs text-slate-400">{helpText}</p>
    <textarea
      id={id}
      aria-label={label}
      rows={rows}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={defaultValue}
      className="custom-scrollbar focus:border-accent-cyan/50 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none"
    />
  </div>
);
