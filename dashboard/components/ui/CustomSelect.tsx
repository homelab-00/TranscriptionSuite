import React from 'react';
import { Listbox, ListboxButton, ListboxOptions, ListboxOption } from '@headlessui/react';
import { ChevronDown } from 'lucide-react';

export interface OptionMeta {
  /** When true, the option is visually dimmed with reduced opacity. */
  dim?: boolean;
  /** Short badge text shown to the right of the option label (e.g. "Requires CUDA"). */
  badge?: string;
}

interface CustomSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  /** Per-option display metadata (dim / badge). Keyed by option value. */
  optionMeta?: Record<string, OptionMeta>;
  className?: string;
  placeholder?: string;
  accentColor?: 'cyan' | 'magenta';
  disabled?: boolean;
}

export const CustomSelect: React.FC<CustomSelectProps> = ({
  value,
  onChange,
  options,
  optionMeta,
  className = '',
  placeholder = 'Select...',
  accentColor = 'cyan',
  disabled = false,
}) => {
  // Extract layout classes from className to apply to the container div
  const isFlex = className.includes('flex-1');
  const heightClass = className.match(/h-\w+|h-\[.*?\]/)?.[0] ?? '';
  const widthClass = className.match(/w-\w+|w-\[.*?\]/)?.[0] ?? '';
  const minWidthClass = className.match(/min-w-\w+|min-w-\[.*?\]/)?.[0] ?? '';
  const maxWidthClass = className.match(/max-w-\w+|max-w-\[.*?\]/)?.[0] ?? '';

  const containerClasses = `relative min-w-0 ${isFlex ? 'flex-1' : ''} ${heightClass} ${widthClass} ${minWidthClass} ${maxWidthClass}`;

  const activeItemClass =
    accentColor === 'magenta'
      ? 'bg-accent-magenta/10 text-accent-magenta'
      : 'bg-accent-cyan/10 text-accent-cyan';

  const dotClass =
    accentColor === 'magenta'
      ? 'bg-accent-magenta shadow-[0_0_5px_rgba(217,70,239,0.5)]'
      : 'bg-accent-cyan shadow-[0_0_5px_rgba(34,211,238,0.5)]';

  return (
    <Listbox value={value} onChange={onChange} disabled={disabled}>
      <div className={containerClasses}>
        <ListboxButton
          title={value || placeholder}
          className={`flex h-full w-full min-w-0 items-center justify-between text-left ${disabled ? 'cursor-not-allowed opacity-50' : ''} ${className}`}
        >
          {({ open }) => (
            <>
              <span className="mr-2 truncate">{value || placeholder}</span>
              <ChevronDown
                size={14}
                className={`shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''} opacity-50`}
              />
            </>
          )}
        </ListboxButton>

        <ListboxOptions
          anchor="bottom start"
          className="dropdown-appear z-9999 mt-1 w-[var(--button-width)] overflow-hidden rounded-xl border border-white/10 bg-slate-900 shadow-2xl ring-1 ring-white/5 focus:outline-none"
        >
          <div className="custom-scrollbar max-h-60 overflow-y-auto py-1">
            {options.map((option) => {
              const meta = optionMeta?.[option];
              return (
                <ListboxOption
                  key={option}
                  value={option}
                  title={meta?.badge ? `${option} — ${meta.badge}` : option}
                  className={({ focus, selected }) =>
                    `flex min-w-0 cursor-pointer items-center justify-between px-4 py-2 text-sm transition-colors ${
                      meta?.dim && !selected ? 'opacity-40' : ''
                    } ${
                      selected
                        ? activeItemClass
                        : focus
                          ? 'bg-white/5 text-white'
                          : 'text-slate-300'
                    }`
                  }
                >
                  {({ selected }) => (
                    <>
                      <span className="mr-2 truncate">{option}</span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {meta?.badge && (
                          <span className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                            {meta.badge}
                          </span>
                        )}
                        {selected && <div className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />}
                      </div>
                    </>
                  )}
                </ListboxOption>
              );
            })}
          </div>
        </ListboxOptions>
      </div>
    </Listbox>
  );
};
