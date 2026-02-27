import React, { useState, useRef, useCallback } from 'react';

interface ShortcutCaptureProps {
  value: string;
  onChange: (accelerator: string) => void;
  placeholder?: string;
  disabled?: boolean;
  portalTrigger?: string;
  isWaylandPortal?: boolean;
  onPortalRebind?: () => void;
}

/**
 * Map a KeyboardEvent to an Electron accelerator string.
 * Requires at least one modifier + a non-modifier key.
 */
function keyEventToAccelerator(e: React.KeyboardEvent): string | null {
  const modifiers: string[] = [];
  if (e.ctrlKey) modifiers.push('Ctrl');
  if (e.altKey) modifiers.push('Alt');
  if (e.shiftKey) modifiers.push('Shift');
  if (e.metaKey) modifiers.push('Super');

  // Ignore bare modifier presses
  const ignoredKeys = new Set([
    'Control',
    'Alt',
    'Shift',
    'Meta',
    'Dead',
    'Unidentified',
    'Process',
  ]);
  if (ignoredKeys.has(e.key)) return null;

  // Must have at least one modifier
  if (modifiers.length === 0) return null;

  // Normalize key name to Electron accelerator format
  let key = e.key;

  // Single character keys → uppercase
  if (key.length === 1) {
    key = key.toUpperCase();
  } else {
    // Map special keys to Electron names
    const keyMap: Record<string, string> = {
      ArrowUp: 'Up',
      ArrowDown: 'Down',
      ArrowLeft: 'Left',
      ArrowRight: 'Right',
      ' ': 'Space',
      Escape: 'Escape',
      Enter: 'Return',
      Backspace: 'Backspace',
      Delete: 'Delete',
      Tab: 'Tab',
      Home: 'Home',
      End: 'End',
      PageUp: 'PageUp',
      PageDown: 'PageDown',
      Insert: 'Insert',
      F1: 'F1',
      F2: 'F2',
      F3: 'F3',
      F4: 'F4',
      F5: 'F5',
      F6: 'F6',
      F7: 'F7',
      F8: 'F8',
      F9: 'F9',
      F10: 'F10',
      F11: 'F11',
      F12: 'F12',
    };
    key = keyMap[key] ?? key;
  }

  return [...modifiers, key].join('+');
}

export const ShortcutCapture: React.FC<ShortcutCaptureProps> = ({
  value,
  onChange,
  placeholder = 'Click to set shortcut',
  disabled = false,
  portalTrigger,
  isWaylandPortal = false,
  onPortalRebind,
}) => {
  const [capturing, setCapturing] = useState(false);
  const [pendingDisplay, setPendingDisplay] = useState('');
  const inputRef = useRef<HTMLDivElement>(null);

  const startCapture = useCallback(() => {
    if (disabled || isWaylandPortal) return;
    setCapturing(true);
    setPendingDisplay('');
    // Focus the element for keyboard events
    inputRef.current?.focus();
  }, [disabled, isWaylandPortal]);

  const cancelCapture = useCallback(() => {
    setCapturing(false);
    setPendingDisplay('');
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!capturing) return;

      e.preventDefault();
      e.stopPropagation();

      // Escape cancels capture
      if (e.key === 'Escape') {
        cancelCapture();
        return;
      }

      const accelerator = keyEventToAccelerator(e);
      if (accelerator) {
        setCapturing(false);
        setPendingDisplay('');
        onChange(accelerator);
      } else {
        // Show current modifier state as feedback
        const mods: string[] = [];
        if (e.ctrlKey) mods.push('Ctrl');
        if (e.altKey) mods.push('Alt');
        if (e.shiftKey) mods.push('Shift');
        if (e.metaKey) mods.push('Super');
        setPendingDisplay(mods.length > 0 ? mods.join('+') + '+...' : '');
      }
    },
    [capturing, cancelCapture, onChange],
  );

  const handleBlur = useCallback(() => {
    if (capturing) {
      cancelCapture();
    }
  }, [capturing, cancelCapture]);

  // Wayland portal mode: read-only display + Change button
  if (isWaylandPortal) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex min-h-[38px] flex-1 items-center rounded-lg border border-white/10 bg-black/20 px-3 py-2 font-mono text-sm text-slate-400">
          {portalTrigger || 'Not assigned'}
        </div>
        <button
          type="button"
          onClick={onPortalRebind}
          disabled={disabled}
          className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-white transition-all duration-200 hover:bg-white/10 disabled:pointer-events-none disabled:opacity-50"
        >
          Change
        </button>
      </div>
    );
  }

  // Interactive capture mode
  return (
    <div
      ref={inputRef}
      tabIndex={disabled ? -1 : 0}
      role="button"
      onClick={startCapture}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
      className={`flex min-h-[38px] w-full cursor-pointer items-center rounded-lg border px-3 py-2 font-mono text-sm transition-all duration-200 focus:outline-none ${
        capturing
          ? 'border-accent-cyan/50 ring-accent-cyan/20 text-accent-cyan bg-black/30 ring-1'
          : 'border-white/10 bg-black/20 text-white hover:border-white/20'
      } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
    >
      {capturing ? (
        <span className="text-accent-cyan animate-pulse">
          {pendingDisplay || 'Press shortcut...'}
        </span>
      ) : value ? (
        <span>{value}</span>
      ) : (
        <span className="text-slate-500">{placeholder}</span>
      )}
    </div>
  );
};
