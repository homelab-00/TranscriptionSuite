import type { ModelInfo } from './modelRegistry';
import type { OptionMeta } from '../../components/ui/CustomSelect';

export interface ModelCacheEntryLike {
  exists: boolean;
  size?: string;
}

export interface ModelOptionPresentation {
  options: string[];
  optionLabel: Record<string, string>;
  optionDescription: Record<string, string>;
  optionMeta: Record<string, OptionMeta>;
}

/**
 * Build CustomSelect props for a model dropdown: human names, repo-id
 * descriptions, downloaded badges, downloaded-first ordering (GH-213).
 * `tail` holds sentinel options (Disabled/Custom) pinned after the models.
 * A model absent from `cache` has UNKNOWN state - never claim "Not downloaded".
 */
export function buildModelOptionPresentation(
  models: ModelInfo[],
  cache: Record<string, ModelCacheEntryLike | undefined>,
  tail: string[],
): ModelOptionPresentation {
  const downloaded = models.filter((m) => cache[m.id]?.exists === true);
  const rest = models.filter((m) => cache[m.id]?.exists !== true);
  const ordered = [...downloaded, ...rest];

  const optionLabel: Record<string, string> = {};
  const optionDescription: Record<string, string> = {};
  const optionMeta: Record<string, OptionMeta> = {};
  for (const m of ordered) {
    optionLabel[m.id] = m.displayName;
    optionDescription[m.id] = m.id;
    const entry = cache[m.id];
    if (entry?.exists) {
      optionMeta[m.id] = { badge: entry.size ? `Downloaded ${entry.size}` : 'Downloaded' };
    } else if (entry && entry.exists === false) {
      optionMeta[m.id] = {
        badge: m.approxSize ? `Not downloaded (${m.approxSize})` : 'Not downloaded',
      };
    } else if (m.approxSize) {
      optionMeta[m.id] = { badge: m.approxSize };
    }
  }
  return {
    options: [...ordered.map((m) => m.id), ...tail],
    optionLabel,
    optionDescription,
    optionMeta,
  };
}
