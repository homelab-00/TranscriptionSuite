import React from 'react';

interface AppleSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: string;
  size?: 'sm' | 'md';
  disabled?: boolean;
}

export const AppleSwitch: React.FC<AppleSwitchProps> = ({
  checked,
  onChange,
  label,
  description,
  size = 'sm',
  disabled = false,
}) => {
  // sm: 36px width, 20px height
  // md: 44px width, 24px height
  const dimensions = size === 'sm' ? 'w-9 h-5' : 'w-11 h-6';

  // Padding is set to 3px (p-[3px])
  // sm: 20px height - 6px padding = 14px knob (h-3.5 w-3.5)
  // md: 24px height - 6px padding = 18px knob (h-4.5 w-4.5)
  const knobSize = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4.5 w-4.5';

  // Translation:
  // sm: 36px width - 6px padding - 14px knob = 16px travel (translate-x-4)
  // md: 44px width - 6px padding - 18px knob = 20px travel (translate-x-5)
  const translate = size === 'sm' ? 'translate-x-4' : 'translate-x-5';

  return (
    <div className="flex items-center justify-between py-1">
      {(label || description) && (
        <div className="mr-4">
          {label && <div className="text-sm font-medium text-white/90">{label}</div>}
          {description && <div className="text-xs text-slate-400">{description}</div>}
        </div>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => {
          if (!disabled) onChange(!checked);
        }}
        className={`focus:ring-accent-cyan relative inline-flex shrink-0 items-center rounded-full p-[3px] transition-colors duration-200 ease-in-out focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-900 focus:outline-none ${disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'} ${checked ? 'bg-accent-cyan' : 'bg-slate-700'} ${dimensions} `}
      >
        <span
          className={`pointer-events-none inline-block rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${checked ? translate : 'translate-x-0'} ${knobSize} `}
        />
      </button>
    </div>
  );
};
