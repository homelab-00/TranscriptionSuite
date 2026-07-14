import React, { useMemo } from 'react';
import {
  AudioLines,
  Bird,
  Boxes,
  Ear,
  Feather,
  KeyRound,
  Languages,
  Link2,
  Loader2,
  Mic,
  MicOff,
  PenLine,
  Radio,
  Sparkles,
  Speech,
  Users,
  Zap,
} from 'lucide-react';

import { AppleIcon } from '../../ui/icons/AppleIcon';
import { Button } from '../../ui/Button';
import { CustomSelect } from '../../ui/CustomSelect';
import { SelectorGroup } from '../../ui/SelectorGroup';
import { SelectorTile } from '../../ui/SelectorTile';
import type { TileAccent } from '../../ui/SelectorTile';
import {
  DIARIZATION_MODEL_CUSTOM_OPTION,
  type FamilyChoiceId,
  defaultModelForFamilyChoice,
  diarizationTilesFor,
  familyChoiceForModel,
  familyChoicesFor,
  liveModelsFor,
  liveTilesFor,
  type LiveTileId,
  modelsForFamilyChoice,
} from '../../../src/services/instanceMatrix';
import {
  DISABLED_MODEL_SENTINEL,
  LIVE_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_RECOMMENDED_MODEL,
  MAIN_MODEL_CUSTOM_OPTION,
  MODEL_DEFAULT_LOADING_PLACEHOLDER,
  MODEL_DISABLED_OPTION,
  VULKAN_RECOMMENDED_MODEL,
} from '../../../src/services/modelSelection';
import { isWhisperCppModel } from '../../../src/services/modelCapabilities';
import { buildModelOptionPresentation } from '../../../src/services/modelOptionPresentation';
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
  mainCustomModel: string;
  onMainCustomModelChange: (value: string) => void;
  liveModelSelection: string;
  onLiveModelSelectionChange: (value: string) => void;
  liveCustomModel: string;
  onLiveCustomModelChange: (value: string) => void;
  diarizationModelSelection: string;
  onDiarizationModelSelectionChange: (value: string) => void;
  diarizationCustomModel: string;
  onDiarizationCustomModelChange: (value: string) => void;
  activeTranscriber: string;
  activeLiveModel: string;
  diarizationStatusModelId: string;
  modelCacheStatus: Record<string, ModelCacheStatus>;
  liveModelWhisperOnlyCompatible: boolean;
  liveModeModelConstraintMessage: string;
  modelsLoaded: boolean | undefined;
  modelsLoading: boolean;
  onLoadModels: () => void;
  onUnloadModels: () => void;
}

const FAMILY_ICONS: Record<FamilyChoiceId, React.ReactNode> = {
  whisper: <AudioLines size={16} />,
  parakeet: <Bird size={16} />,
  canary: <Feather size={16} />,
  sensevoice: <Ear size={16} />,
  vibevoice: <Speech size={16} />,
  whispercpp: <Boxes size={16} />,
  'mlx-whisper': <AudioLines size={16} />,
  'mlx-parakeet': <Bird size={16} />,
  'mlx-canary': <Feather size={16} />,
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
  whisper: 'slate',
  whispercpp: 'purple',
  disabled: 'slate',
};

const DIARIZATION_TILE_ICONS: Record<string, React.ReactNode> = {
  pyannote: <Users size={16} />,
  campp: <Zap size={16} />,
  sortformer: <AppleIcon size={16} />,
  builtin: <Sparkles size={16} />,
  custom: <PenLine size={16} />,
};

const DIARIZATION_TILE_ACCENTS: Record<string, TileAccent> = {
  pyannote: 'magenta',
  campp: 'amber',
  sortformer: 'slate',
  builtin: 'blue',
  custom: 'cyan',
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
  mainCustomModel,
  onMainCustomModelChange,
  liveModelSelection,
  onLiveModelSelectionChange,
  liveCustomModel,
  onLiveCustomModelChange,
  diarizationModelSelection,
  onDiarizationModelSelectionChange,
  diarizationCustomModel,
  onDiarizationCustomModelChange,
  activeTranscriber,
  activeLiveModel,
  diarizationStatusModelId,
  modelCacheStatus,
  liveModelWhisperOnlyCompatible,
  liveModeModelConstraintMessage,
  modelsLoaded,
  modelsLoading,
  onLoadModels,
  onUnloadModels,
}: InstanceSettingsSelectorsProps) {
  const familyChoices = useMemo(() => familyChoicesFor(runtimeProfile), [runtimeProfile]);

  // The family tile that should light up: derived from the dropdown value
  // (or the custom text when the Custom option is active).
  const selectedFamily = useMemo(() => {
    if (mainModelSelection === MAIN_MODEL_CUSTOM_OPTION) {
      return familyChoiceForModel(mainCustomModel) ?? 'whisper';
    }
    return familyChoiceForModel(mainModelSelection);
  }, [mainModelSelection, mainCustomModel]);

  const mainPresentation = useMemo(() => {
    if (!selectedFamily) {
      return buildModelOptionPresentation([], {}, [
        MODEL_DISABLED_OPTION,
        MAIN_MODEL_CUSTOM_OPTION,
      ]);
    }
    const models = modelsForFamilyChoice(selectedFamily);
    // Vulkan GGML: Custom is omitted — only registry GGML files exist on disk
    // for the sidecar to load (matches the pre-redesign dropdown).
    const tail =
      selectedFamily === 'whispercpp'
        ? [MODEL_DISABLED_OPTION]
        : [MODEL_DISABLED_OPTION, MAIN_MODEL_CUSTOM_OPTION];
    return buildModelOptionPresentation(models, modelCacheStatus, tail);
  }, [selectedFamily, modelCacheStatus]);

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

  const livePresentation = useMemo(() => {
    if (activeLiveTile === 'same-as-main' || activeLiveTile === 'disabled') {
      return buildModelOptionPresentation([], {}, []);
    }
    const models = liveModelsFor(activeLiveTile === 'whispercpp' ? 'vulkan' : 'gpu');
    const tail = activeLiveTile === 'whispercpp' ? [] : [LIVE_MODEL_CUSTOM_OPTION];
    return buildModelOptionPresentation(models, modelCacheStatus, tail);
  }, [activeLiveTile, modelCacheStatus]);

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
            onSelect={() => {
              onMainModelSelectionChange(defaultModelForFamilyChoice(choice.id));
              onMainCustomModelChange('');
            }}
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-xs font-medium tracking-wider text-slate-500 uppercase">
            Model Variant
          </label>
          <CustomSelect
            value={mainModelSelection}
            onChange={onMainModelSelectionChange}
            options={mainPresentation.options}
            optionLabel={mainPresentation.optionLabel}
            optionDescription={mainPresentation.optionDescription}
            optionMeta={mainPresentation.optionMeta}
            accentColor="magenta"
            className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
            disabled={isRunning}
          />
          {mainModelSelection === MAIN_MODEL_CUSTOM_OPTION && (
            <input
              type="text"
              value={mainCustomModel}
              onChange={(e) => onMainCustomModelChange(e.target.value)}
              placeholder="owner/model-name"
              disabled={isRunning}
              className={`focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
            />
          )}
          {selectedFamily === 'whispercpp' && (
            <p className="text-xs text-slate-500 italic">
              This GGML model runs on the AMD/Intel GPU via the whisper.cpp sidecar. Switching
              models requires a server restart.
            </p>
          )}
          {selectedFamily?.startsWith('mlx') && (
            <p className="flex items-center gap-1 text-xs text-violet-400">
              <Zap size={10} />
              Metal / MLX accelerated
            </p>
          )}
        </div>
      </div>

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
      {livePresentation.options.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <CustomSelect
              value={liveModelSelection}
              onChange={onLiveModelSelectionChange}
              options={livePresentation.options}
              optionLabel={livePresentation.optionLabel}
              optionDescription={livePresentation.optionDescription}
              optionMeta={livePresentation.optionMeta}
              className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
              disabled={isRunning}
            />
            {liveModelSelection === LIVE_MODEL_CUSTOM_OPTION && (
              <input
                type="text"
                value={liveCustomModel}
                onChange={(e) => onLiveCustomModelChange(e.target.value)}
                placeholder="owner/model-name"
                disabled={isRunning}
                className={`focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
              />
            )}
          </div>
        </div>
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
      {diarizationTiles.length > 0 &&
        diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <input
              type="text"
              value={diarizationCustomModel}
              onChange={(e) => onDiarizationCustomModelChange(e.target.value)}
              placeholder="owner/model-name"
              disabled={isRunning}
              className={`focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1${isRunning ? 'cursor-not-allowed opacity-50' : ''}`}
            />
          </div>
        )}

      {/* Load / unload models */}
      <div className="flex gap-2 border-t border-white/5 pt-2">
        <Button
          variant={modelsLoaded === false ? 'secondary' : 'danger'}
          className="h-9 px-4 whitespace-nowrap"
          onClick={modelsLoaded === false ? onLoadModels : onUnloadModels}
          disabled={modelsLoading || !isRunning}
        >
          {modelsLoading ? (
            <>
              <Loader2 size={14} className="mr-2 animate-spin" /> Loading...
            </>
          ) : modelsLoaded === false ? (
            'Load Models'
          ) : (
            'Unload Models'
          )}
        </Button>
        {modelsLoaded !== undefined && (
          <span
            className={`ml-auto self-center font-mono text-xs ${modelsLoaded ? 'text-green-400' : 'text-slate-500'}`}
          >
            {modelsLoaded ? 'Models Loaded' : 'Models Not Loaded'}
          </span>
        )}
      </div>
    </div>
  );
}
