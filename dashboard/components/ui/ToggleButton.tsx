import React from 'react';

interface ToggleButtonProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Visible text inside the button; doubles as the accessible name. */
  label: string;
  icon?: React.ReactNode;
  size?: 'sm' | 'md';
  disabled?: boolean;
  /** Tooltip text; also shown while disabled to explain why. */
  title?: string;
  /** Accessible name override when the visible label is not enough. */
  ariaLabel?: string;
  /** Stretch to fill the available width of the parent flex row. */
  fullWidth?: boolean;
  className?: string;
}

/**
 * Pill-style on/off button with a visible pressed state. Keeps the same
 * semantics as AppleSwitch (role switch plus aria-checked) so the two are
 * interchangeable for tests and screen readers.
 *
 * The title lives on a wrapper span, never on the button itself: Chromium
 * (the Electron renderer) never shows a native tooltip on a disabled form
 * control, and the disabled state is exactly when the explanatory tooltip
 * matters. The disabled button also gets pointer-events-none so hover
 * always lands on the wrapper.
 */
export const ToggleButton: React.FC<ToggleButtonProps> = ({
  checked,
  onChange,
  label,
  icon,
  size = 'md',
  disabled = false,
  title,
  ariaLabel,
  fullWidth = false,
  className = '',
}) => {
  const sizeClasses = size === 'sm' ? 'h-8 gap-1.5 px-3 text-xs' : 'gap-2 px-4 py-2 text-sm';

  const stateClasses = disabled
    ? 'pointer-events-none border-white/10 bg-white/5 text-slate-500 opacity-40'
    : checked
      ? 'border-accent-cyan/40 bg-accent-cyan/15 text-accent-cyan shadow-[0_0_10px_rgba(34,211,238,0.15)] hover:bg-accent-cyan/25'
      : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white active:scale-95';

  return (
    <span
      title={title}
      className={`inline-flex ${fullWidth ? 'min-w-0 flex-1' : ''} ${disabled ? 'cursor-not-allowed' : ''}`}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel ?? label}
        disabled={disabled}
        onClick={() => {
          if (!disabled) onChange(!checked);
        }}
        className={`focus:ring-accent-cyan inline-flex items-center justify-center rounded-xl border font-medium transition-all duration-200 focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-900 focus:outline-none ${fullWidth ? 'w-full' : ''} ${sizeClasses} ${stateClasses} ${className}`}
      >
        {icon}
        <span className="whitespace-nowrap">{label}</span>
      </button>
    </span>
  );
};
