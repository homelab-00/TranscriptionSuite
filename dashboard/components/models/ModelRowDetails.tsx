import React from 'react';
import type { ModelInfo } from '../../src/services/modelRegistry';

function CapBadge({ label, active }: { label: string; active: boolean }) {
  if (!active) return null;
  return (
    <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-400">
      {label}
    </span>
  );
}

interface ModelRowDetailsProps {
  model: ModelInfo;
  cached: boolean;
  /** On-disk size. Only known after download, so it renders only when cached. */
  cacheSize?: string;
  className?: string;
}

/**
 * The detail block for one model: repo id, on-disk size, parameter count,
 * capability badges, language count, and description.
 *
 * Shared by the Model Manager rows and the Server tab model picker so the two
 * cannot drift apart. ModelInfo carries no size field, so a size is shown only
 * for a model that is already cached.
 */
export const ModelRowDetails: React.FC<ModelRowDetailsProps> = ({
  model,
  cached,
  cacheSize,
  className = '',
}) => (
  <div className={className}>
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
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
      <CapBadge
        label={
          model.capabilities.translation === 'multilingual'
            ? 'Translation (between languages)'
            : model.capabilities.translation === 'toEnglish'
              ? 'Translation (to English)'
              : 'Translation'
        }
        active={model.capabilities.translation !== 'none'}
      />
      <CapBadge label="Live Mode" active={model.capabilities.liveMode} />
      <CapBadge label="Diarization" active={model.capabilities.diarization} />
      {model.capabilities.languageCount > 0 && (
        <span className="text-slate-500">
          {model.capabilities.languageCount} language
          {model.capabilities.languageCount !== 1 ? 's' : ''}
        </span>
      )}
    </div>
    <p className="mt-1 text-xs text-slate-500">{model.description}</p>
  </div>
);
