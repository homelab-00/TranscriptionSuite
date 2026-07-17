import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { ModelPickerRow } from './ModelPickerRow';
import type { ModelCacheStatus } from '../../src/hooks/useModelCache';
import type { ModelInfo } from '../../src/services/modelRegistry';

interface ModelCardPickerProps {
  models: ModelInfo[];
  /** Currently selected model id. */
  selection: string;
  /** Badge on the selected card, naming its role (e.g. "Main", "Live"). */
  badgeLabel: string;
  isRunning: boolean;
  canManage: boolean;
  modelCacheStatus: ModelCacheStatus;
  onSelectionChange: (value: string) => void;
  onRemove: (id: string) => void;
}

/**
 * A collapsible list of model cards. Collapsed (the default) it shows only a
 * summary of the current selection; clicking it reveals one ModelPickerRow
 * card per model.
 */
export function ModelCardPicker({
  models,
  selection,
  badgeLabel,
  isRunning,
  canManage,
  modelCacheStatus,
  onSelectionChange,
  onRemove,
}: ModelCardPickerProps) {
  const [expanded, setExpanded] = useState(false);

  const selectedModel = models.find((model) => model.id === selection);
  const summaryName = selectedModel ? selectedModel.displayName : 'Select a model';

  const summaryDotClass = modelCacheStatus[selection]?.exists
    ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
    : 'bg-slate-500';

  return (
    <div className="space-y-2">
      {/* Collapsed summary of the current selection; toggles the full list */}
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-left transition-colors duration-200 hover:bg-white/10"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${summaryDotClass}`} />
          <span className="truncate text-sm font-medium text-white">{summaryName}</span>
          {selectedModel && (
            <span className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold">
              {badgeLabel}
            </span>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1.5 text-xs text-slate-500">
          {expanded ? 'Hide models' : 'Change model'}
          <ChevronDown
            size={14}
            className={`transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          />
        </span>
      </button>

      {expanded && (
        <div className="space-y-2">
          {models.map((model) => (
            <ModelPickerRow
              key={model.id}
              model={model}
              selected={selection === model.id}
              badgeLabel={badgeLabel}
              cached={Boolean(modelCacheStatus[model.id]?.exists)}
              cacheSize={modelCacheStatus[model.id]?.size}
              canManage={canManage}
              disabled={isRunning}
              onSelect={onSelectionChange}
              onRemove={onRemove}
            />
          ))}
          <p className="text-xs text-slate-500 italic">
            Missing models are downloaded automatically when the server starts.
          </p>
        </div>
      )}
    </div>
  );
}
