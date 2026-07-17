import React, { useMemo } from 'react';
import {
  AudioLines,
  Bird,
  Boxes,
  Ear,
  KeyRound,
  Languages,
  Link2,
  Mic,
  MicOff,
  Radio,
  Sparkles,
  Speech,
  Users,
  Zap,
} from 'lucide-react';

import { AppleIcon } from '../../ui/icons/AppleIcon';
import { SelectorGroup } from '../../ui/SelectorGroup';
import { SelectorTile } from '../../ui/SelectorTile';
import type { TileAccent } from '../../ui/SelectorTile';
import { MainModelPicker } from './MainModelPicker';
import { ModelCardPicker } from '../../models/ModelCardPicker';
import {
  type FamilyChoiceId,
  defaultModelForFamilyChoice,
  diarizationTilesFor,
  familyChoiceForModel,
  familyChoicesFor,
  liveModelsFor,
  liveTilesFor,
  type LiveTileId,
} from '../../../src/services/instanceMatrix';
import {
  DISABLED_MODEL_SENTINEL,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_RECOMMENDED_MODEL,
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MODEL_DISABLED_OPTION,
  VULKAN_RECOMMENDED_MODEL,
} from '../../../src/services/modelSelection';
import { isWhisperCppModel } from '../../../src/services/modelCapabilities';
import type { RuntimeProfile } from '../../../src/types/runtime';

interface ModelCacheStatus {
  exists: boolean;
  size?: string;
}

interface InstanceSettingsSelectorsProps {
  runtimeProfile: RuntimeProfile;
  isRunning: boolean;
  mainModelSelection: string;
  onMainModelSelectionChange: (value: string) => void;
  liveModelSelection: string;
  onLiveModelSelectionChange: (value: string) => void;
  diarizationModelSelection: string;
  onDiarizationModelSelectionChange: (value: string) => void;
  activeTranscriber: string;
  activeLiveModel: string;
  diarizationStatusModelId: string;
  modelCacheStatus: Record<string, ModelCacheStatus>;
  liveModelWhisperOnlyCompatible: boolean;
  liveModeModelConstraintMessage: string;
  canManage: boolean;
  onRemoveModel: (id: string) => void;
}

const FAMILY_ICONS: Record<FamilyChoiceId, React.ReactNode> = {
  whisper: <AudioLines size={16} />,
  nemo: <Bird size={16} />,
  sensevoice: <Ear size={16} />,
  vibevoice: <Speech size={16} />,
  whispercpp: <Boxes size={16} />,
  'mlx-whisper': <AudioLines size={16} />,
  'mlx-nemo': <Bird size={16} />,
  'mlx-vibevoice': <Speech size={16} />,
};

const LIVE_TILE_ICONS: Record<LiveTileId, React.ReactNode> = {
  'same-as-main': <Link2 size={16} />,
  whisper: <AudioLines size={16} />,
  whispercpp: <Boxes size={16} />,
  disabled: <MicOff size={16} />,
};

const LIVE_TILE_ACCENTS: Record<LiveTileId, TileAccent> = {
  'same-as-main': 'cyan',
  whisper: 'purple',
  whispercpp: 'purple',
  disabled: 'slate',
};

const DIARIZATION_TILE_ICONS: Record<string, React.ReactNode> = {
  pyannote: <Users size={16} />,
  campp: <Zap size={16} />,
  sortformer: <AppleIcon size={16} />,
  builtin: <Sparkles size={16} />,
};

const DIARIZATION_TILE_ACCENTS: Record<string, TileAccent> = {
  pyannote: 'magenta',
  campp: 'amber',
  sortformer: 'slate',
  builtin: 'blue',
};

function CacheBadge({ status }: { status: ModelCacheStatus | undefined }) {
  const exists = status?.exists ?? false;
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`inline-block h-2 w-2 rounded-full ${exists ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-slate-500'}`}
      />
      <span className={`font-mono text-[10px] ${exists ? 'text-green-400' : 'text-slate-500'}`}>
        {exists ? 'Downloaded' : 'Missing'}
      </span>
    </div>
  );
}

function isRealModelValue(value: string): boolean {
  return Boolean(
    value && value !== MODEL_DEFAULT_LOADING_PLACEHOLDER && value !== DISABLED_MODEL_SENTINEL,
  );
}

/**
 * The three model selector groups of the Instance Settings card: main
 * transcriber (family tiles + per-family model dropdown), Live Mode and
 * diarization engine. All valid/invalid combinations come from
 * src/services/instanceMatrix.ts — this component only renders them.
 */
export function InstanceSettingsSelectors({
  runtimeProfile,
  isRunning,
  mainModelSelection,
  onMainModelSelectionChange,
  liveModelSelection,
  onLiveModelSelectionChange,
  diarizationModelSelection,
  onDiarizationModelSelectionChange,
  activeTranscriber,
  activeLiveModel,
  diarizationStatusModelId,
  modelCacheStatus,
  liveModelWhisperOnlyCompatible,
  liveModeModelConstraintMessage,
  canManage,
  onRemoveModel,
}: InstanceSettingsSelectorsProps) {
  const familyChoices = useMemo(() => familyChoicesFor(runtimeProfile), [runtimeProfile]);

  // The family tile that should light up, derived from the selected model id.
  const selectedFamily = useMemo(
    () => familyChoiceForModel(mainModelSelection),
    [mainModelSelection],
  );

  const liveTiles = useMemo(
    () => liveTilesFor(runtimeProfile, activeTranscriber),
    [runtimeProfile, activeTranscriber],
  );

  const activeLiveTile: LiveTileId = useMemo(() => {
    if (liveModelSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION) return 'same-as-main';
    if (liveModelSelection === MODEL_DISABLED_OPTION) return 'disabled';
    if (isWhisperCppModel(liveModelSelection)) return 'whispercpp';
    return 'whisper';
  }, [liveModelSelection]);

  const liveModels = useMemo(() => {
    if (activeLiveTile === 'same-as-main' || activeLiveTile === 'disabled') return [];
    return liveModelsFor(activeLiveTile === 'whispercpp' ? 'vulkan' : 'gpu');
  }, [activeLiveTile]);

  const diarizationTiles = useMemo(
    () => diarizationTilesFor(runtimeProfile, activeTranscriber),
    [runtimeProfile, activeTranscriber],
  );

  const handleLiveTileSelect = (id: LiveTileId) => {
    if (id === 'same-as-main') onLiveModelSelectionChange(LIVE_MODEL_SAME_AS_MAIN_OPTION);
    else if (id === 'disabled') onLiveModelSelectionChange(MODEL_DISABLED_OPTION);
    else if (id === 'whispercpp') onLiveModelSelectionChange(VULKAN_RECOMMENDED_MODEL);
    else onLiveModelSelectionChange(LIVE_RECOMMENDED_MODEL);
  };

  const liveBadgeKey =
    liveModelSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION ? activeTranscriber : activeLiveModel;

  return (
    <div className="space-y-6">
      {/* Main transcriber */}
      <SelectorGroup
        icon={<Mic size={16} className="text-accent-magenta" />}
        title="Main Transcriber"
        hint="Which model transcribes your recordings"
        action={
          isRunning && isRealModelValue(activeTranscriber) ? (
            <CacheBadge status={modelCacheStatus[activeTranscriber]} />
          ) : undefined
        }
      >
        {familyChoices.map((choice) => (
          <SelectorTile
            key={choice.id}
            icon={FAMILY_ICONS[choice.id]}
            label={choice.label}
            sublabel={choice.sublabel}
            accent={choice.accent as TileAccent}
            selected={selectedFamily === choice.id}
            disabled={!choice.enabled || isRunning}
            badge={choice.reason}
            hint={choice.hint}
            onSelect={() => onMainModelSelectionChange(defaultModelForFamilyChoice(choice.id))}
            glyphs={
              <>
                <span
                  className="flex items-center gap-0.5 text-[10px] text-slate-400"
                  title={`${choice.capabilities.languages} languages`}
                >
                  <Languages size={10} />
                  {choice.capabilities.languages}
                </span>
                {choice.capabilities.translation !== 'none' && (
                  <span
                    className="text-[10px] text-slate-400"
                    title={
                      choice.capabilities.translation === 'multilingual'
                        ? 'Translates between languages'
                        : 'Translates to English'
                    }
                  >
                    {choice.capabilities.translation === 'multilingual' ? 'A⇄B' : '→EN'}
                  </span>
                )}
                {choice.capabilities.live && (
                  <Radio size={10} className="text-slate-400" aria-label="Live Mode capable" />
                )}
                {choice.capabilities.diarization !== 'none' && (
                  <Users size={10} className="text-slate-400" aria-label="Diarization capable" />
                )}
                {choice.capabilities.requiresToken && (
                  <KeyRound
                    size={10}
                    className="text-slate-500"
                    aria-label="Diarization needs a HuggingFace token"
                  />
                )}
              </>
            }
          />
        ))}
      </SelectorGroup>

      <MainModelPicker
        selectedFamily={selectedFamily}
        mainModelSelection={mainModelSelection}
        isRunning={isRunning}
        canManage={canManage}
        modelCacheStatus={modelCacheStatus}
        onMainModelSelectionChange={onMainModelSelectionChange}
        onRemove={onRemoveModel}
      />

      {/* Live Mode model */}
      <SelectorGroup
        icon={<Radio size={16} className="text-accent-cyan" />}
        title="Live Mode Model"
        hint="Realtime transcription runs on faster-whisper or whisper.cpp"
        columnsClass="grid-cols-2 sm:grid-cols-4"
        action={
          isRunning && isRealModelValue(activeLiveModel) ? (
            <CacheBadge status={modelCacheStatus[liveBadgeKey ?? '']} />
          ) : undefined
        }
      >
        {liveTiles.map((tile) => (
          <SelectorTile
            key={tile.id}
            icon={LIVE_TILE_ICONS[tile.id]}
            label={tile.label}
            accent={LIVE_TILE_ACCENTS[tile.id]}
            selected={activeLiveTile === tile.id}
            disabled={!tile.enabled || isRunning}
            badge={tile.reason}
            hint={tile.hint}
            onSelect={() => handleLiveTileSelect(tile.id)}
          />
        ))}
      </SelectorGroup>
      {liveModels.length > 0 && (
        <ModelCardPicker
          models={liveModels}
          selection={liveModelSelection}
          badgeLabel="Live"
          isRunning={isRunning}
          canManage={canManage}
          modelCacheStatus={modelCacheStatus}
          onSelectionChange={onLiveModelSelectionChange}
          onRemove={onRemoveModel}
        />
      )}
      {!liveModelWhisperOnlyCompatible && (
        <p className="text-accent-orange text-xs">{liveModeModelConstraintMessage}</p>
      )}

      {/* Diarization engine */}
      <SelectorGroup
        icon={<Users size={16} className="text-accent-magenta" />}
        title="Diarization"
        hint="How speakers get identified"
        columnsClass="grid-cols-2 sm:grid-cols-4"
        action={
          isRunning && diarizationStatusModelId ? (
            <CacheBadge status={modelCacheStatus[diarizationStatusModelId]} />
          ) : undefined
        }
      >
        {diarizationTiles.map((tile) => (
          <SelectorTile
            key={tile.id}
            icon={DIARIZATION_TILE_ICONS[tile.id]}
            label={tile.label}
            accent={DIARIZATION_TILE_ACCENTS[tile.id]}
            selected={tile.id === 'builtin' || diarizationModelSelection === tile.storedValue}
            locked={tile.id === 'builtin'}
            disabled={!tile.enabled || isRunning}
            badge={tile.reason}
            hint={tile.hint}
            onSelect={() => onDiarizationModelSelectionChange(tile.storedValue)}
          />
        ))}
      </SelectorGroup>
      {diarizationTiles.length === 0 && (
        <p className="text-xs text-slate-500 italic">
          Diarization is not available for whisper.cpp (GGML) models.
        </p>
      )}
    </div>
  );
}
