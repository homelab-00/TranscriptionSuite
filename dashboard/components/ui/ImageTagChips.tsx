import React, { useState, useEffect, useMemo } from 'react';
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';
import { MoreHorizontal } from 'lucide-react';
import type { RemoteTag } from '../../src/hooks/useDocker';
import { parseVersionTag, isNewerVersion, formatDateDMY } from '../../src/services/versionUtils';

interface ImageTagChipsProps {
  /** All remote tags sorted descending by semver, with optional creation dates. */
  remoteTags: RemoteTag[];
  /** Set of tag strings that are downloaded locally. */
  localTags: Set<string>;
  /** Map of local tag → Docker created date string. */
  localDates: Map<string, string>;
  /** Currently selected tag string. */
  value: string;
  /** Called when the user selects a tag. */
  onChange: (tag: string) => void;
}

/** Number of stable tags shown as chips in the main row. */
const MAIN_CHIP_COUNT = 4;
/** Number of items shown per overflow section before "Load All". */
const OVERFLOW_INITIAL = 4;

export const ImageTagChips: React.FC<ImageTagChipsProps> = ({
  remoteTags,
  localTags,
  localDates,
  value,
  onChange,
}) => {
  const [showAllOlder, setShowAllOlder] = useState(false);
  const [showAllRC, setShowAllRC] = useState(false);

  // Reset expansion state when the tag list changes (e.g. after refresh)
  useEffect(() => {
    setShowAllOlder(false);
    setShowAllRC(false);
  }, [remoteTags]);

  const { stableChips, rcTags, olderTags, hasOverflow } = useMemo(() => {
    const stable = remoteTags.filter((rt) => {
      const p = parseVersionTag(rt.tag);
      return p && !p.isRC;
    });
    const chips = stable.slice(0, MAIN_CHIP_COUNT);
    const older = stable.slice(MAIN_CHIP_COUNT);

    // Latest stable tag for RC filtering
    const latestStable = chips[0]?.tag;

    // RC tags: when a stable baseline exists, only show RCs with version > latest stable.
    // When no stable tags exist at all, show all RCs so the user isn't stuck with a blank selector.
    const rc = remoteTags.filter((rt) => {
      const p = parseVersionTag(rt.tag);
      if (!p?.isRC) return false;
      return !latestStable || isNewerVersion(rt.tag, latestStable);
    });

    return {
      stableChips: chips,
      rcTags: rc,
      olderTags: older,
      hasOverflow: rc.length > 0 || older.length > 0,
    };
  }, [remoteTags]);

  /** Resolve a display date for a tag — prefer GHCR date, fallback to local Docker date. */
  const getDate = (rt: RemoteTag): string | null =>
    formatDateDMY(rt.created) ?? formatDateDMY(localDates.get(rt.tag) ?? null);

  const chipClass = (tag: string): string =>
    `flex min-w-[5rem] flex-col items-center justify-center rounded-lg border px-3 py-1.5 text-center transition-all cursor-pointer ${
      tag === value
        ? 'bg-accent-cyan/15 border-accent-cyan/40 text-accent-cyan shadow-[0_0_10px_rgba(34,211,238,0.15)]'
        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white'
    }`;

  const renderTagItem = (rt: RemoteTag, close?: () => void) => {
    const date = getDate(rt);
    const isLocal = localTags.has(rt.tag);
    return (
      <button
        key={rt.tag}
        onClick={() => {
          onChange(rt.tag);
          close?.();
        }}
        className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${
          rt.tag === value
            ? 'bg-accent-cyan/10 text-accent-cyan'
            : 'text-slate-300 hover:bg-white/5 hover:text-white'
        }`}
      >
        <div className="flex flex-col">
          <span className="font-medium">{rt.tag}</span>
          {date && <span className="text-[10px] text-slate-500">{date}</span>}
        </div>
        {isLocal && (
          <span className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
            local
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="flex items-center gap-1.5">
      {stableChips.map((rt) => {
        const date = getDate(rt);
        const isLocal = localTags.has(rt.tag);
        return (
          <button key={rt.tag} onClick={() => onChange(rt.tag)} className={chipClass(rt.tag)}>
            <span className="text-sm leading-tight font-semibold">{rt.tag}</span>
            <span className="text-[10px] leading-tight text-slate-500">
              {date ?? (isLocal ? 'local' : '\u00A0')}
            </span>
          </button>
        );
      })}

      {hasOverflow && (
        <Popover className="relative">
          <PopoverButton
            className={`flex cursor-pointer items-center justify-center rounded-lg border px-3 py-2.5 transition-all ${
              // Highlight if the selected tag is inside the overflow (positive membership check)
              [...rcTags, ...olderTags].some((rt) => rt.tag === value)
                ? 'bg-accent-cyan/15 border-accent-cyan/40 text-accent-cyan shadow-[0_0_10px_rgba(34,211,238,0.15)]'
                : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            <MoreHorizontal size={16} />
          </PopoverButton>

          <PopoverPanel
            anchor="bottom end"
            className="z-9999 mt-2 w-56 overflow-hidden rounded-xl border border-white/10 bg-slate-900 shadow-2xl ring-1 ring-white/5 focus:outline-none"
          >
            {({ close }) => (
              <div className="custom-scrollbar max-h-72 overflow-y-auto py-1">
                {rcTags.length > 0 && (
                  <div className="px-3 pt-2 pb-1">
                    <span className="text-[10px] font-medium tracking-wider text-slate-500 uppercase">
                      RC Releases
                    </span>
                    <div className="mt-1 flex flex-col">
                      {(showAllRC ? rcTags : rcTags.slice(0, OVERFLOW_INITIAL)).map((rt) =>
                        renderTagItem(rt, close),
                      )}
                      {!showAllRC && rcTags.length > OVERFLOW_INITIAL && (
                        <button
                          onClick={() => setShowAllRC(true)}
                          className="mt-1 rounded px-3 py-1 text-xs text-slate-500 hover:text-slate-300"
                        >
                          Load All ({rcTags.length})
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {olderTags.length > 0 && (
                  <div className="px-3 pt-2 pb-1">
                    {rcTags.length > 0 && <div className="mb-2 border-t border-white/5" />}
                    <span className="text-[10px] font-medium tracking-wider text-slate-500 uppercase">
                      Older Releases
                    </span>
                    <div className="mt-1 flex flex-col">
                      {(showAllOlder ? olderTags : olderTags.slice(0, OVERFLOW_INITIAL)).map((rt) =>
                        renderTagItem(rt, close),
                      )}
                      {!showAllOlder && olderTags.length > OVERFLOW_INITIAL && (
                        <button
                          onClick={() => setShowAllOlder(true)}
                          className="mt-1 rounded px-3 py-1 text-xs text-slate-500 hover:text-slate-300"
                        >
                          Load All ({olderTags.length})
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </PopoverPanel>
        </Popover>
      )}
    </div>
  );
};
