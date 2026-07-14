import React from 'react';
import { Download, ExternalLink, Loader2, Trash2 } from 'lucide-react';
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
 * One model in the Server tab picker, rendered as a full card: status dot,
 * name, a Main badge on the active model, cache actions, a HuggingFace link,
 * and the always-visible detail block (repo id, params, capabilities,
 * description).
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
  const openHuggingFace = () => {
    const api = (window as any).electronAPI;
    api?.app?.openExternal(model.huggingfaceUrl);
  };

  return (
    <div
      className={`rounded-lg border px-4 py-3 transition-colors duration-200 ${
        selected
          ? 'border-accent-magenta/60 bg-white/10'
          : 'border-white/10 bg-white/5 hover:bg-white/10'
      }`}
    >
      {/* Top line: name + actions */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Status dot */}
          <span
            className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
              downloading
                ? 'animate-pulse bg-blue-400 shadow-[0_0_6px_rgba(96,165,250,0.6)]'
                : cached
                  ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
                  : 'bg-slate-500'
            }`}
          />
          <span className="truncate text-sm font-medium text-white">{model.displayName}</span>
          {selected && (
            <span className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold">
              Main
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Download / Remove */}
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

          {/* Select as main transcriber */}
          {!selected && (
            <Button
              variant="secondary"
              size="sm"
              aria-label={`Select ${model.displayName}`}
              onClick={() => onSelect(model.id)}
              disabled={disabled}
            >
              Select
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
