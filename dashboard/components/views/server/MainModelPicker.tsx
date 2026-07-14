import React from 'react';
import { Library, Zap } from 'lucide-react';

import { Button } from '../../ui/Button';
import { ModelPickerRow } from '../../models/ModelPickerRow';
import type { ModelCacheStatus } from '../../../src/hooks/useModelCache';
import type { FamilyChoiceId } from '../../../src/services/instanceMatrix';
import { modelsForFamilyChoice } from '../../../src/services/instanceMatrix';
import { MAIN_MODEL_CUSTOM_OPTION } from '../../../src/services/modelSelection';

interface MainModelPickerProps {
  selectedFamily: FamilyChoiceId | null;
  mainModelSelection: string;
  mainCustomModel: string;
  isRunning: boolean;
  canManage: boolean;
  modelCacheStatus: ModelCacheStatus;
  downloadingIds: ReadonlySet<string>;
  onMainModelSelectionChange: (value: string) => void;
  onMainCustomModelChange: (value: string) => void;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
  onOpenManager: () => void;
}

/**
 * Replaces the old single Model Variant dropdown with one expandable row per
 * model in the selected family tile. This is what makes the merged NeMo tile
 * usable: Parakeet (ASR-only) and Canary (translates) show up as two separate,
 * individually selectable rows instead of being flattened into one option.
 *
 * Cross-family work (downloading a family that is not currently selected, or
 * managing diarization models) is out of scope here - it lives behind the
 * Manage all models button, which opens the full Model Manager modal.
 */
export function MainModelPicker({
  selectedFamily,
  mainModelSelection,
  mainCustomModel,
  isRunning,
  canManage,
  modelCacheStatus,
  downloadingIds,
  onMainModelSelectionChange,
  onMainCustomModelChange,
  onDownload,
  onRemove,
  onOpenManager,
}: MainModelPickerProps) {
  const models = selectedFamily ? modelsForFamilyChoice(selectedFamily) : [];
  const isCustomSelected = mainModelSelection === MAIN_MODEL_CUSTOM_OPTION;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium tracking-wider text-slate-500 uppercase">Model</label>
        <Button variant="ghost" size="sm" icon={<Library size={13} />} onClick={onOpenManager}>
          Manage all models
        </Button>
      </div>

      <div className="space-y-2">
        {models.map((model) => (
          <ModelPickerRow
            key={model.id}
            model={model}
            selected={mainModelSelection === model.id}
            cached={Boolean(modelCacheStatus[model.id]?.exists)}
            cacheSize={modelCacheStatus[model.id]?.size}
            downloading={downloadingIds.has(model.id)}
            canManage={canManage}
            disabled={isRunning}
            onSelect={onMainModelSelectionChange}
            onDownload={onDownload}
            onRemove={onRemove}
          />
        ))}

        <div
          className={`rounded-lg border px-3 py-2.5 transition-colors ${
            isCustomSelected ? 'border-accent-magenta/60 bg-white/10' : 'border-white/10 bg-white/5'
          }`}
        >
          <div className="flex items-center gap-3">
            <input
              type="radio"
              name="main-model"
              checked={isCustomSelected}
              disabled={isRunning}
              onChange={() => onMainModelSelectionChange(MAIN_MODEL_CUSTOM_OPTION)}
              aria-label="Custom HuggingFace repo"
              className="accent-accent-magenta h-3.5 w-3.5 shrink-0"
            />
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-white">
              Custom (HuggingFace repo)
            </span>
          </div>

          {isCustomSelected && (
            <input
              type="text"
              value={mainCustomModel}
              onChange={(e) => onMainCustomModelChange(e.target.value)}
              placeholder="owner/model-name"
              disabled={isRunning}
              className={`focus:ring-accent-magenta mt-2 h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
            />
          )}
        </div>
      </div>

      {selectedFamily === 'whispercpp' && (
        <p className="text-xs text-slate-500 italic">
          This GGML model runs on the AMD/Intel GPU via the whisper.cpp sidecar. Switching models
          requires a server restart.
        </p>
      )}
      {selectedFamily?.startsWith('mlx') && (
        <p className="flex items-center gap-1 text-xs text-violet-400">
          <Zap size={10} />
          Metal / MLX accelerated
        </p>
      )}
    </div>
  );
}
