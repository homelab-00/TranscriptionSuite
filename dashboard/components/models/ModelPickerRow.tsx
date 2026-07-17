import React from 'react';
import { ExternalLink, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { ModelRowDetails } from './ModelRowDetails';
import type { ModelInfo } from '../../src/services/modelRegistry';

interface ModelPickerRowProps {
  model: ModelInfo;
  selected: boolean;
  /** Badge on the selected card, naming its role. Defaults to "Main". */
  badgeLabel?: string;
  cached: boolean;
  cacheSize?: string;
  /** Whether removing the cached weights is permitted right now. */
  canManage: boolean;
  /** Selection is locked while the server is running. */
  disabled: boolean;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
}

/**
 * One model in the Server tab pickers, rendered as a full card: status dot,
 * name, a role badge (Main/Live) on the active model, a cache Remove action,
 * a HuggingFace link, and the always-visible detail block (repo id, params,
 * capabilities, description).
 *
 * The card itself is the select control — clicking anywhere on it picks the
 * model. There is no Download action: missing weights are fetched
 * automatically when the server starts. The card can't be a <button> because
 * it nests the Remove/HF-link buttons, so it carries button semantics via
 * role/tabIndex/keyboard handling instead.
 */
export const ModelPickerRow: React.FC<ModelPickerRowProps> = ({
  model,
  selected,
  badgeLabel = 'Main',
  cached,
  cacheSize,
  canManage,
  disabled,
  onSelect,
  onRemove,
}) => {
  const openHuggingFace = (event: React.MouseEvent) => {
    event.stopPropagation();
    const api = (window as any).electronAPI;
    api?.app?.openExternal(model.huggingfaceUrl);
  };

  const select = () => {
    if (!disabled) onSelect(model.id);
  };

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={`Select ${model.displayName}`}
      aria-pressed={selected}
      aria-disabled={disabled}
      onClick={select}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select();
        }
      }}
      className={`rounded-lg border px-4 py-3 transition-colors duration-200 ${
        disabled ? 'cursor-default' : 'cursor-pointer'
      } ${
        selected
          ? 'border-accent-magenta/60 bg-white/10'
          : `border-white/10 bg-white/5 ${disabled ? '' : 'hover:bg-white/10'}`
      }`}
    >
      {/* Top line: name + actions */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Status dot */}
          <span
            className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
              cached ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'
            }`}
          />
          <span className="truncate text-sm font-medium text-white">{model.displayName}</span>
          {selected && (
            <span className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold">
              {badgeLabel}
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {cached && (
            <Button
              variant="danger"
              size="sm"
              onClick={(event) => {
                event.stopPropagation();
                onRemove(model.id);
              }}
              disabled={!canManage}
            >
              <Trash2 size={13} className="mr-1.5" />
              Remove
            </Button>
          )}

          {/* HF Link */}
          <button
            onClick={openHuggingFace}
            className="rounded p-1.5 text-slate-500 transition-colors hover:bg-white/10 hover:text-white"
            title="View on HuggingFace"
          >
            <ExternalLink size={14} />
          </button>
        </div>
      </div>

      <ModelRowDetails
        model={model}
        cached={cached}
        cacheSize={cacheSize}
        className="mt-1.5 pl-5"
      />
    </div>
  );
};
