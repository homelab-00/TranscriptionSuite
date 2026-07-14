import React from 'react';
import { Lock } from 'lucide-react';

export type TileAccent =
  | 'cyan'
  | 'magenta'
  | 'green'
  | 'yellow'
  | 'amber'
  | 'blue'
  | 'purple'
  | 'orange'
  | 'red'
  | 'slate';

interface AccentClasses {
  selected: string;
  icon: string;
}

// Static class strings per accent so the Tailwind JIT scanner picks them up.
const ACCENT_CLASSES: Record<TileAccent, AccentClasses> = {
  cyan: {
    selected: 'border-accent-cyan/60 bg-accent-cyan/10 shadow-[0_0_12px_rgba(34,211,238,0.2)]',
    icon: 'text-accent-cyan',
  },
  magenta: {
    selected:
      'border-accent-magenta/60 bg-accent-magenta/10 shadow-[0_0_12px_rgba(232,121,249,0.2)]',
    icon: 'text-accent-magenta',
  },
  green: {
    selected: 'border-green-400/60 bg-green-400/10 shadow-[0_0_12px_rgba(74,222,128,0.2)]',
    icon: 'text-green-400',
  },
  yellow: {
    selected: 'border-yellow-400/60 bg-yellow-400/10 shadow-[0_0_12px_rgba(250,204,21,0.2)]',
    icon: 'text-yellow-400',
  },
  amber: {
    selected: 'border-amber-400/60 bg-amber-400/10 shadow-[0_0_12px_rgba(251,191,36,0.2)]',
    icon: 'text-amber-400',
  },
  blue: {
    selected: 'border-blue-400/60 bg-blue-400/10 shadow-[0_0_12px_rgba(96,165,250,0.2)]',
    icon: 'text-blue-400',
  },
  purple: {
    selected: 'border-purple-400/60 bg-purple-400/10 shadow-[0_0_12px_rgba(192,132,252,0.2)]',
    icon: 'text-purple-400',
  },
  orange: {
    selected: 'border-orange-400/60 bg-orange-400/10 shadow-[0_0_12px_rgba(251,146,60,0.2)]',
    icon: 'text-orange-400',
  },
  red: {
    selected: 'border-red-400/60 bg-red-400/10 shadow-[0_0_12px_rgba(248,113,113,0.2)]',
    icon: 'text-red-400',
  },
  slate: {
    selected: 'border-slate-300/60 bg-slate-300/10 shadow-[0_0_12px_rgba(203,213,225,0.2)]',
    icon: 'text-slate-200',
  },
};

interface SelectorTileProps {
  icon: React.ReactNode;
  label: string;
  sublabel?: string;
  selected: boolean;
  onSelect: () => void;
  accent?: TileAccent;
  disabled?: boolean;
  /** Reason badge shown when the tile is disabled (e.g. "Requires Metal"). */
  badge?: string;
  /** Small note shown under the label (e.g. "Slow on CPU"). */
  hint?: string;
  /** Selected but not user-changeable (e.g. VibeVoice built-in diarization). */
  locked?: boolean;
  /** Optional mini capability glyph row rendered at the bottom of the tile. */
  glyphs?: React.ReactNode;
}

/**
 * A colorful icon tile used by the Instance Settings selector groups.
 * Disabled tiles stay visible (dimmed, with a reason badge) so the whole
 * compatibility matrix remains readable at a glance.
 */
export const SelectorTile: React.FC<SelectorTileProps> = ({
  icon,
  label,
  sublabel,
  selected,
  onSelect,
  accent = 'cyan',
  disabled = false,
  badge,
  hint,
  locked = false,
  glyphs,
}) => {
  const accentClasses = ACCENT_CLASSES[accent];
  const stateClasses = disabled
    ? 'cursor-not-allowed border-white/5 bg-white/[0.02] opacity-45'
    : selected
      ? `${accentClasses.selected} ${locked ? 'cursor-default' : 'cursor-pointer'}`
      : 'cursor-pointer border-white/10 bg-white/5 hover:border-white/25 hover:bg-white/10';

  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => {
        if (!disabled && !locked) onSelect();
      }}
      title={disabled && badge ? badge : hint}
      className={`relative flex min-h-20 flex-col items-start gap-1 rounded-xl border p-3 text-left transition-all duration-200 ${stateClasses}`}
    >
      <span className="flex w-full items-center gap-2">
        <span className={selected && !disabled ? accentClasses.icon : 'text-slate-300'}>
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium break-words text-white/90">{label}</span>
          {sublabel && (
            <span className="block text-[10px] break-words text-slate-400">{sublabel}</span>
          )}
        </span>
        {locked && <Lock size={12} className="shrink-0 text-slate-400" />}
      </span>
      {badge && disabled && (
        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-slate-300">
          {badge}
        </span>
      )}
      {hint && !disabled && <span className="text-[10px] text-slate-400">{hint}</span>}
      {glyphs && <span className="mt-auto flex items-center gap-1.5">{glyphs}</span>}
    </button>
  );
};
