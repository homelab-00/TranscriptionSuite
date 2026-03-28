import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Download,
  Trash2,
  ExternalLink,
  Loader2,
  Plus,
  X,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import {
  MODEL_REGISTRY,
  getModelsByFamily,
  getModelById,
  type ModelInfo,
  type ModelFamily,
  type ModelRole,
} from '../../src/services/modelRegistry';
import { isWhisperModel } from '../../src/services/modelCapabilities';
import {
  MAIN_MODEL_CUSTOM_OPTION,
  LIVE_MODEL_SAME_AS_MAIN_OPTION,
  LIVE_MODEL_CUSTOM_OPTION,
  MODEL_DISABLED_OPTION,
} from '../../src/services/modelSelection';

// ─── Sentinel constants (must match ServerView) ─────────────────────────────

const DIARIZATION_MODEL_CUSTOM_OPTION = 'Custom (HuggingFace repo)';
const DIARIZATION_DEFAULT_MODEL = 'pyannote/speaker-diarization-community-1';

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ModelManagerTabProps {
  mainModelSelection: string;
  setMainModelSelection: (value: string) => void;
  mainCustomModel: string;
  setMainCustomModel: (value: string) => void;
  liveModelSelection: string;
  setLiveModelSelection: (value: string) => void;
  liveCustomModel: string;
  setLiveCustomModel: (value: string) => void;
  diarizationModelSelection: string;
  setDiarizationModelSelection: (value: string) => void;
  diarizationCustomModel: string;
  setDiarizationCustomModel: (value: string) => void;
  modelCacheStatus: Record<string, { exists: boolean; size?: string }>;
  isRunning: boolean;
  refreshCacheStatus: (extraIds?: string[]) => void;
}

// ─── Family section configuration ───────────────────────────────────────────

interface FamilySectionConfig {
  family: ModelFamily;
  label: string;
  borderClass: string;
  badgeClass: string;
  headerTextClass: string;
}

const FAMILY_SECTIONS: FamilySectionConfig[] = [
  {
    family: 'nemo',
    label: 'NeMo',
    borderClass: 'border-l-green-400',
    badgeClass: 'bg-green-500/10 text-green-400',
    headerTextClass: 'text-green-400',
  },
  {
    family: 'whisper',
    label: 'Faster Whisper',
    borderClass: 'border-l-slate-300',
    badgeClass: 'bg-white/10 text-slate-200',
    headerTextClass: 'text-slate-300',
  },
  {
    family: 'vibevoice',
    label: 'VibeVoice',
    borderClass: 'border-l-blue-400',
    badgeClass: 'bg-blue-500/10 text-blue-400',
    headerTextClass: 'text-blue-400',
  },
  {
    family: 'mlx',
    label: 'MLX Whisper (Apple Silicon)',
    borderClass: 'border-l-orange-400',
    badgeClass: 'bg-orange-500/10 text-orange-400',
    headerTextClass: 'text-orange-400',
  },
  {
    family: 'diarization',
    label: 'Diarization',
    borderClass: 'border-l-accent-magenta',
    badgeClass: 'bg-accent-magenta/10 text-accent-magenta',
    headerTextClass: 'text-accent-magenta',
  },
];

// ─── Capability badge helper ────────────────────────────────────────────────

function CapBadge({ label, active }: { label: string; active: boolean }) {
  if (!active) return null;
  return (
    <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-400">
      {label}
    </span>
  );
}

// ─── Model Row ──────────────────────────────────────────────────────────────

interface ModelRowProps {
  model: ModelInfo;
  cached: boolean;
  cacheSize?: string;
  downloading: boolean;
  isRunning: boolean;
  isActiveMain: boolean;
  isActiveLive: boolean;
  isActiveDiarization: boolean;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
  onSelectAs: (id: string, role: ModelRole) => void;
}

function ModelRow({
  model,
  cached,
  cacheSize,
  downloading,
  isRunning,
  isActiveMain,
  isActiveLive,
  isActiveDiarization,
  onDownload,
  onRemove,
  onSelectAs,
}: ModelRowProps) {
  const [selectOpen, setSelectOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!selectOpen) return;
    const handler = (e: MouseEvent) => {
      if (selectRef.current && !selectRef.current.contains(e.target as Node)) {
        setSelectOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [selectOpen]);

  const openHuggingFace = () => {
    const api = (window as any).electronAPI;
    api?.app?.openExternal(model.huggingfaceUrl);
  };

  const roleOptions: { role: ModelRole; label: string }[] = model.roles.map((r) => {
    switch (r) {
      case 'main':
        return { role: r as ModelRole, label: 'Main Transcriber' };
      case 'live':
        return { role: r as ModelRole, label: 'Live Model' };
      case 'diarization':
        return { role: r as ModelRole, label: 'Diarization Model' };
    }
  });

  const activeBadges: string[] = [];
  if (isActiveMain) activeBadges.push('Main');
  if (isActiveLive) activeBadges.push('Live');
  if (isActiveDiarization) activeBadges.push('Diarization');

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-4 py-3 transition-colors duration-200 hover:bg-white/10">
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
          {activeBadges.length > 0 &&
            activeBadges.map((b) => (
              <span
                key={b}
                className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold"
              >
                {b}
              </span>
            ))}
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
              disabled={!isRunning}
            >
              <Trash2 size={13} className="mr-1.5" />
              Remove
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onDownload(model.id)}
              disabled={!isRunning}
            >
              <Download size={13} className="mr-1.5" />
              Download
            </Button>
          )}

          {/* Select dropdown */}
          {roleOptions.length > 0 && (
            <div ref={selectRef} className="relative">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSelectOpen(!selectOpen)}
                disabled={isRunning}
              >
                Select
                <ChevronDown size={12} className="ml-1" />
              </Button>
              {selectOpen && (
                <div className="absolute right-0 z-20 mt-1 min-w-42.5 overflow-hidden rounded-lg border border-white/10 bg-slate-800 py-1 shadow-xl">
                  {roleOptions.map((opt) => (
                    <button
                      key={opt.role}
                      onClick={() => {
                        onSelectAs(model.id, opt.role);
                        setSelectOpen(false);
                      }}
                      className="block w-full px-3 py-1.5 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
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

      {/* Detail line */}
      <div className="mt-1.5 flex flex-wrap items-center gap-2 pl-5 text-xs text-slate-500">
        <span className="font-mono">{model.id}</span>
        {cached && cacheSize && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span className="text-green-400">Downloaded {cacheSize}</span>
          </>
        )}
        {model.parameterCount && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span>{model.parameterCount} params</span>
          </>
        )}
        <span className="text-slate-600">&middot;</span>
        <CapBadge label="Translation" active={model.capabilities.translation} />
        <CapBadge label="Live Mode" active={model.capabilities.liveMode} />
        <CapBadge label="Diarization" active={model.capabilities.diarization} />
        {model.capabilities.languageCount > 0 && (
          <span className="text-slate-500">
            {model.capabilities.languageCount} language
            {model.capabilities.languageCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Description */}
      <p className="mt-1 pl-5 text-xs text-slate-500">{model.description}</p>
    </div>
  );
}

// ─── Custom Model Row ───────────────────────────────────────────────────────

interface CustomModelRowProps {
  modelId: string;
  cached: boolean;
  cacheSize?: string;
  downloading: boolean;
  isRunning: boolean;
  isActiveMain: boolean;
  isActiveLive: boolean;
  isActiveDiarization: boolean;
  onDownload: (id: string) => void;
  onRemove: (id: string) => void;
  onSelectAs: (id: string, role: ModelRole) => void;
  onDelete: (id: string) => void;
}

function CustomModelRow({
  modelId,
  cached,
  cacheSize,
  downloading,
  isRunning,
  isActiveMain,
  isActiveLive,
  isActiveDiarization,
  onDownload,
  onRemove,
  onSelectAs,
  onDelete,
}: CustomModelRowProps) {
  const [selectOpen, setSelectOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectOpen) return;
    const handler = (e: MouseEvent) => {
      if (selectRef.current && !selectRef.current.contains(e.target as Node)) {
        setSelectOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [selectOpen]);

  const activeBadges: string[] = [];
  if (isActiveMain) activeBadges.push('Main');
  if (isActiveLive) activeBadges.push('Live');
  if (isActiveDiarization) activeBadges.push('Diarization');

  const roleOptions: { role: ModelRole; label: string }[] = [
    { role: 'main', label: 'Main Transcriber' },
    ...(isWhisperModel(modelId) ? [{ role: 'live' as ModelRole, label: 'Live Model' }] : []),
    { role: 'diarization', label: 'Diarization Model' },
  ];

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-4 py-3 transition-colors duration-200 hover:bg-white/10">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
              downloading
                ? 'animate-pulse bg-blue-400 shadow-[0_0_6px_rgba(96,165,250,0.6)]'
                : cached
                  ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
                  : 'bg-slate-500'
            }`}
          />
          <span className="truncate font-mono text-sm text-white">{modelId}</span>
          <span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-[10px] text-slate-400">
            Custom
          </span>
          {activeBadges.map((b) => (
            <span
              key={b}
              className="bg-accent-cyan/15 text-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-semibold"
            >
              {b}
            </span>
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {downloading ? (
            <Button variant="secondary" size="sm" disabled>
              <Loader2 size={13} className="mr-1.5 animate-spin" />
              Downloading
            </Button>
          ) : cached ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => onRemove(modelId)}
              disabled={!isRunning}
            >
              <Trash2 size={13} className="mr-1.5" />
              Remove
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onDownload(modelId)}
              disabled={!isRunning}
            >
              <Download size={13} className="mr-1.5" />
              Download
            </Button>
          )}

          <div ref={selectRef} className="relative">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSelectOpen(!selectOpen)}
              disabled={isRunning}
            >
              Select
              <ChevronDown size={12} className="ml-1" />
            </Button>
            {selectOpen && (
              <div className="absolute right-0 z-20 mt-1 min-w-42.5 overflow-hidden rounded-lg border border-white/10 bg-slate-800 py-1 shadow-xl">
                {roleOptions.map((opt) => (
                  <button
                    key={opt.role}
                    onClick={() => {
                      onSelectAs(modelId, opt.role);
                      setSelectOpen(false);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => onDelete(modelId)}
            className="rounded p-1.5 text-slate-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
            title="Remove custom model"
          >
            <X size={14} />
          </button>
        </div>
      </div>
      {cached && cacheSize && (
        <p className="mt-1 pl-5 text-xs text-green-400">Downloaded {cacheSize}</p>
      )}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export const ModelManagerTab: React.FC<ModelManagerTabProps> = ({
  mainModelSelection,
  setMainModelSelection,
  mainCustomModel,
  setMainCustomModel,
  liveModelSelection,
  setLiveModelSelection,
  liveCustomModel,
  setLiveCustomModel,
  diarizationModelSelection,
  setDiarizationModelSelection,
  diarizationCustomModel,
  setDiarizationCustomModel,
  modelCacheStatus,
  isRunning,
  refreshCacheStatus,
}) => {
  const [downloadingModels, setDownloadingModels] = useState<Set<string>>(new Set());
  const [customModels, setCustomModels] = useState<string[]>([]);
  const [customModelInput, setCustomModelInput] = useState('');
  const [customSectionExpanded, setCustomSectionExpanded] = useState(true);
  const [toast, setToast] = useState<string | null>(null);

  // Load custom models from electron store
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('modelManager.customModels')
        .then((val: unknown) => {
          if (Array.isArray(val)) setCustomModels(val as string[]);
        })
        .catch(() => {});
    }
  }, []);

  // Persist custom models
  const persistCustomModels = useCallback((models: string[]) => {
    const api = (window as any).electronAPI;
    api?.config?.set('modelManager.customModels', models);
  }, []);

  // Toast helper
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }, []);

  // Resolve which model IDs are currently selected for each role
  const resolveActiveMain = (): string => {
    if (mainModelSelection === MODEL_DISABLED_OPTION) return '';
    if (mainModelSelection === MAIN_MODEL_CUSTOM_OPTION) return mainCustomModel.trim();
    return mainModelSelection;
  };

  const resolveActiveLive = (): string => {
    if (liveModelSelection === MODEL_DISABLED_OPTION) return '';
    if (liveModelSelection === LIVE_MODEL_SAME_AS_MAIN_OPTION) return resolveActiveMain();
    if (liveModelSelection === LIVE_MODEL_CUSTOM_OPTION) return liveCustomModel.trim();
    return liveModelSelection;
  };

  const resolveActiveDiarization = (): string => {
    if (diarizationModelSelection === DIARIZATION_MODEL_CUSTOM_OPTION)
      return diarizationCustomModel.trim();
    return diarizationModelSelection;
  };

  const activeMain = resolveActiveMain();
  const activeLive = resolveActiveLive();
  const activeDiarization = resolveActiveDiarization();

  // ── Actions ─────────────────────────────────────────────────────────────

  const handleDownload = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      if (!api?.docker?.downloadModelToCache) return;

      setDownloadingModels((prev) => new Set(prev).add(modelId));
      try {
        await api.docker.downloadModelToCache(modelId);
        showToast(`Downloaded ${modelId}`);
        refreshCacheStatus([modelId]);
      } catch (err: any) {
        showToast(`Download failed: ${err?.message || 'Unknown error'}`);
      } finally {
        setDownloadingModels((prev) => {
          const next = new Set(prev);
          next.delete(modelId);
          return next;
        });
      }
    },
    [refreshCacheStatus, showToast],
  );

  const handleRemove = useCallback(
    async (modelId: string) => {
      const api = (window as any).electronAPI;
      if (!api?.docker?.removeModelCache) return;

      try {
        await api.docker.removeModelCache(modelId);
        showToast(`Removed cache for ${modelId}`);
        refreshCacheStatus([modelId]);
      } catch (err: any) {
        showToast(`Remove failed: ${err?.message || 'Unknown error'}`);
      }
    },
    [refreshCacheStatus, showToast],
  );

  const handleSelectAs = useCallback(
    (modelId: string, role: ModelRole) => {
      const registryModel = getModelById(modelId);
      const isPreset = !!registryModel;

      switch (role) {
        case 'main':
          if (isPreset) {
            setMainModelSelection(modelId);
            setMainCustomModel('');
          } else {
            setMainModelSelection(MAIN_MODEL_CUSTOM_OPTION);
            setMainCustomModel(modelId);
          }
          showToast(`Set ${modelId} as Main Transcriber`);
          break;
        case 'live':
          if (!isWhisperModel(modelId)) {
            showToast('Live Mode only supports faster-whisper models in v1.');
            break;
          }
          if (isPreset && registryModel?.family === 'whisper') {
            // Whisper models are in the live preset dropdown
            setLiveModelSelection(modelId);
            setLiveCustomModel('');
          } else {
            setLiveModelSelection(LIVE_MODEL_CUSTOM_OPTION);
            setLiveCustomModel(modelId);
          }
          showToast(`Set ${modelId} as Live Model`);
          break;
        case 'diarization':
          if (modelId === DIARIZATION_DEFAULT_MODEL) {
            setDiarizationModelSelection(DIARIZATION_DEFAULT_MODEL);
            setDiarizationCustomModel('');
          } else {
            setDiarizationModelSelection(DIARIZATION_MODEL_CUSTOM_OPTION);
            setDiarizationCustomModel(modelId);
          }
          showToast(`Set ${modelId} as Diarization Model`);
          break;
      }
    },
    [
      setMainModelSelection,
      setMainCustomModel,
      setLiveModelSelection,
      setLiveCustomModel,
      setDiarizationModelSelection,
      setDiarizationCustomModel,
      showToast,
    ],
  );

  // ── Custom model management ─────────────────────────────────────────────

  const handleAddCustomModel = useCallback(() => {
    const id = customModelInput.trim();
    if (!id || !id.includes('/')) return;
    // Don't add if already in registry or custom list
    if (getModelById(id) || customModels.includes(id)) {
      showToast('Model already exists');
      return;
    }
    const updated = [...customModels, id];
    setCustomModels(updated);
    persistCustomModels(updated);
    setCustomModelInput('');
  }, [customModelInput, customModels, persistCustomModels, showToast]);

  const handleDeleteCustomModel = useCallback(
    (id: string) => {
      const updated = customModels.filter((m) => m !== id);
      setCustomModels(updated);
      persistCustomModels(updated);
    },
    [customModels, persistCustomModels],
  );

  // Check cache for all models (registry + custom) when container is running
  const allModelIds = [...MODEL_REGISTRY.map((m) => m.id), ...customModels];

  const cacheCheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!isRunning) return;

    const ids = allModelIds.filter(Boolean);
    if (ids.length === 0) return;

    if (cacheCheckRef.current) clearTimeout(cacheCheckRef.current);
    cacheCheckRef.current = setTimeout(() => {
      refreshCacheStatus(ids);
    }, 800);

    return () => {
      if (cacheCheckRef.current) clearTimeout(cacheCheckRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning, customModels.length, refreshCacheStatus]);

  return (
    <div className="space-y-6">
      {/* Toast notification */}
      {toast && (
        <div className="animate-in fade-in slide-in-from-top-2 fixed top-4 right-4 z-50 rounded-lg border border-white/10 bg-slate-800 px-4 py-2.5 text-sm text-white shadow-xl duration-200">
          {toast}
        </div>
      )}

      {!isRunning && (
        <div className="rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-400">
          Start the server to manage model downloads. Model selection is available while the server
          is stopped.
        </div>
      )}

      {/* Family sections */}
      {FAMILY_SECTIONS.map((section) => {
        const models = getModelsByFamily(section.family);
        if (models.length === 0) return null;

        return (
          <GlassCard
            key={section.family}
            className={`border-l-2 ${section.borderClass}`}
            title={
              <span className={`text-sm font-semibold ${section.headerTextClass}`}>
                {section.label}
                <span
                  className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-medium ${section.badgeClass}`}
                >
                  {models.length} model{models.length !== 1 ? 's' : ''}
                </span>
              </span>
            }
          >
            <div className="space-y-2">
              {models.map((model) => (
                <ModelRow
                  key={model.id}
                  model={model}
                  cached={modelCacheStatus[model.id]?.exists ?? false}
                  cacheSize={modelCacheStatus[model.id]?.size}
                  downloading={downloadingModels.has(model.id)}
                  isRunning={isRunning}
                  isActiveMain={activeMain.toLowerCase() === model.id.toLowerCase()}
                  isActiveLive={activeLive.toLowerCase() === model.id.toLowerCase()}
                  isActiveDiarization={activeDiarization.toLowerCase() === model.id.toLowerCase()}
                  onDownload={handleDownload}
                  onRemove={handleRemove}
                  onSelectAs={handleSelectAs}
                />
              ))}
            </div>
          </GlassCard>
        );
      })}

      {/* Custom models section */}
      <GlassCard
        className="border-l-2 border-l-slate-500"
        title={
          <button
            onClick={() => setCustomSectionExpanded(!customSectionExpanded)}
            className="flex items-center gap-2 text-sm font-semibold text-slate-400"
          >
            Custom Models
            <span className="rounded-full bg-slate-500/10 px-2 py-0.5 text-[10px] font-medium text-slate-400">
              {customModels.length}
            </span>
            {customSectionExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        }
      >
        {customSectionExpanded && (
          <div className="space-y-3">
            {/* Add custom model input */}
            <div className="flex gap-2">
              <input
                type="text"
                value={customModelInput}
                onChange={(e) => setCustomModelInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddCustomModel();
                }}
                placeholder="owner/model-name"
                className="h-8 flex-1 rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white placeholder-slate-500 transition-shadow outline-none focus:ring-1 focus:ring-slate-400"
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={handleAddCustomModel}
                disabled={!customModelInput.trim().includes('/')}
              >
                <Plus size={13} className="mr-1" />
                Add
              </Button>
            </div>

            {/* Custom model rows */}
            {customModels.length > 0 ? (
              <div className="space-y-2">
                {customModels.map((id) => (
                  <CustomModelRow
                    key={id}
                    modelId={id}
                    cached={modelCacheStatus[id]?.exists ?? false}
                    cacheSize={modelCacheStatus[id]?.size}
                    downloading={downloadingModels.has(id)}
                    isRunning={isRunning}
                    isActiveMain={activeMain.toLowerCase() === id.toLowerCase()}
                    isActiveLive={activeLive.toLowerCase() === id.toLowerCase()}
                    isActiveDiarization={activeDiarization.toLowerCase() === id.toLowerCase()}
                    onDownload={handleDownload}
                    onRemove={handleRemove}
                    onSelectAs={handleSelectAs}
                    onDelete={handleDeleteCustomModel}
                  />
                ))}
              </div>
            ) : (
              <p className="py-2 text-center text-xs text-slate-500">
                No custom models added. Enter a HuggingFace repo ID above.
              </p>
            )}
          </div>
        )}
      </GlassCard>
    </div>
  );
};
