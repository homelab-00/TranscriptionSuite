import React, { useState } from 'react';
import { ChevronDown, Download, Loader2, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { ModelRowDetails } from './ModelRowDetails';
import type { ModelInfo } from '../../src/services/modelRegistry';

interface ModelPickerRowProps {
  model: ModelInfo;
  selected: boolean;
  cached: boolean;
  cacheSize?: string;
  downloading: boolean;
  /** Whether download and remove are permitted right now. */
  canManage: boolean;
  /** Selection is locked while the server is running. */
  disabled: boolean;
  onSelect: (id: string) => void;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
}

/**
 * One model in the Server tab picker: a compact row that expands to the same
 * detail block the Model Manager shows.
 *
 * Collapsed by default because the largest families carry a dozen models, and a
 * dozen always-expanded rows would swamp an already long Server tab.
 */
export const ModelPickerRow: React.FC<ModelPickerRowProps> = ({
  model,
  selected,
  cached,
  cacheSize,
  downloading,
  canManage,
  disabled,
  onSelect,
  onDownload,
  onRemove,
}) => {
  const [expanded, setExpanded] = useState(false);

  const statusDot = downloading
    ? 'animate-pulse bg-blue-400'
    : cached
      ? 'bg-green-500'
      : 'bg-slate-500';

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 transition-colors ${
        selected ? 'border-accent-magenta/60 bg-white/10' : 'border-white/10 bg-white/5'
      }`}
    >
      <div className="flex items-center gap-3">
        <input
          type="radio"
          name="main-model"
          checked={selected}
          disabled={disabled}
          onChange={() => onSelect(model.id)}
          aria-label={model.displayName}
          className="accent-accent-magenta h-3.5 w-3.5 shrink-0"
        />

        <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${statusDot}`} />

        <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">
          {model.displayName}
        </span>

        {model.capabilities.translation !== 'none' && (
          <span
            className="shrink-0 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-slate-400"
            title={
              model.capabilities.translation === 'multilingual'
                ? 'Translates between languages'
                : 'Translates to English'
            }
          >
            {model.capabilities.translation === 'multilingual' ? 'A⇄B' : '→EN'}
          </span>
        )}
        {model.parameterCount && (
          <span className="shrink-0 text-xs text-slate-500">{model.parameterCount}</span>
        )}

        {downloading ? (
          <Button variant="secondary" size="sm" disabled>
            <Loader2 size={13} className="mr-1.5 animate-spin" />
            Downloading
          </Button>
        ) : cached ? (
          <Button
            variant="danger"
            size="sm"
            onClick={() => onRemove(model.id)}
            disabled={!canManage}
          >
            <Trash2 size={13} className="mr-1.5" />
            Remove
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onDownload(model.id)}
            disabled={!canManage}
          >
            <Download size={13} className="mr-1.5" />
            Download
          </Button>
        )}

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? 'Hide details' : 'Show details'}
          aria-expanded={expanded}
          className="shrink-0 rounded p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ChevronDown
            size={14}
            className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {expanded && (
        <ModelRowDetails
          model={model}
          cached={cached}
          cacheSize={cacheSize}
          className="mt-2 pl-7"
        />
      )}
    </div>
  );
};
