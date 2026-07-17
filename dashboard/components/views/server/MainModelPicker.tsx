import React from 'react';
import { Zap } from 'lucide-react';

import { ModelCardPicker } from '../../models/ModelCardPicker';
import type { ModelCacheStatus } from '../../../src/hooks/useModelCache';
import type { FamilyChoiceId } from '../../../src/services/instanceMatrix';
import { modelsForFamilyChoice } from '../../../src/services/instanceMatrix';

interface MainModelPickerProps {
  selectedFamily: FamilyChoiceId | null;
  mainModelSelection: string;
  isRunning: boolean;
  canManage: boolean;
  modelCacheStatus: ModelCacheStatus;
  onMainModelSelectionChange: (value: string) => void;
  onRemove: (id: string) => void;
}

/**
 * One card per model in the selected family tile, collapsed by default
 * behind a summary of the current selection. This is what makes the merged
 * NeMo tile usable: Parakeet (ASR-only) and Canary (translates) show up as
 * two separate, individually selectable cards instead of being flattened
 * into one option.
 *
 * This picker is the only model-management surface: clicking a card selects
 * that model, and cached cards carry a Remove action. There is no Download
 * action — missing weights are fetched automatically at server start.
 */
export function MainModelPicker({
  selectedFamily,
  mainModelSelection,
  isRunning,
  canManage,
  modelCacheStatus,
  onMainModelSelectionChange,
  onRemove,
}: MainModelPickerProps) {
  const models = selectedFamily ? modelsForFamilyChoice(selectedFamily) : [];

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium tracking-wider text-slate-500 uppercase">Model</label>

      <ModelCardPicker
        models={models}
        selection={mainModelSelection}
        badgeLabel="Main"
        isRunning={isRunning}
        canManage={canManage}
        modelCacheStatus={modelCacheStatus}
        onSelectionChange={onMainModelSelectionChange}
        onRemove={onRemove}
      />

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
