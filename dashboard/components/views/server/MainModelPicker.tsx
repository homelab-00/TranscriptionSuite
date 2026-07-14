import React from 'react';
import { Zap } from 'lucide-react';

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
}

/**
 * One card per model in the selected family tile. This is what makes the
 * merged NeMo tile usable: Parakeet (ASR-only) and Canary (translates) show
 * up as two separate, individually selectable cards instead of being
 * flattened into one option.
 *
 * This picker is the only model-management surface: each card carries its own
 * download/remove actions, so downloading a family that is not currently
 * selected means selecting that family tile first.
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
}: MainModelPickerProps) {
  const models = selectedFamily ? modelsForFamilyChoice(selectedFamily) : [];
  const isCustomSelected = mainModelSelection === MAIN_MODEL_CUSTOM_OPTION;

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium tracking-wider text-slate-500 uppercase">Model</label>

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
          className={`rounded-lg border px-4 py-3 transition-colors duration-200 ${
            isCustomSelected
              ? 'border-accent-magenta/60 bg-white/10'
              : 'border-white/10 bg-white/5 hover:bg-white/10'
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="truncate text-sm font-medium text-white">
                Custom (HuggingFace repo)
              </span>
              {isCustomSelected && (
                <span className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold">
                  Main
                </span>
              )}
            </div>
            {!isCustomSelected && (
              <Button
                variant="secondary"
                size="sm"
                aria-label="Select custom HuggingFace repo"
                onClick={() => onMainModelSelectionChange(MAIN_MODEL_CUSTOM_OPTION)}
                disabled={isRunning}
              >
                Select
              </Button>
            )}
          </div>

          {isCustomSelected && (
            <input
              type="text"
              value={mainCustomModel}
              onChange={(e) => onMainCustomModelChange(e.target.value)}
              placeholder="owner/model-name"
              disabled={isRunning}
              className={`focus:ring-accent-magenta mt-2 h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1 ${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
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
