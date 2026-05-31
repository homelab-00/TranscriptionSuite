/**
 * FindReplaceTextEditor — reusable plain-text editor with find/replace.
 *
 * A single <textarea> plus a floating find/replace control (FindReplaceToolbar)
 * driven by useFindReplace. Shared by all three transcript surfaces. Find/replace
 * uses the textarea's native selection (no overlay) per design D6.
 *
 * Keyboard (scoped to this editor; preventDefault stops Electron's native find):
 *   Ctrl/Cmd+F open find · Ctrl/Cmd+H open replace · Esc close.
 *   Enter / Shift+Enter next/prev in the find input · Enter in replace = replace current.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useFindReplace } from '../../src/hooks/useFindReplace';
import { FindReplaceToolbar } from './FindReplaceToolbar';

export interface FindReplaceTextEditorProps {
  value: string;
  onChange: (next: string) => void;
  /** Display-only: no editing, no find/replace control. */
  readOnly?: boolean;
  /** Focus the textarea on mount (Audio-Note edit entry). */
  autoFocus?: boolean;
  placeholder?: string;
  /** Container styling — each surface passes its own box look. */
  className?: string;
  /** Textarea typography, e.g. 'font-mono text-sm leading-relaxed text-slate-300'. */
  textClassName?: string;
  /** Default true. */
  enableFindReplace?: boolean;
  /**
   * When true (default), the textarea grows to fit content (capped by its CSS
   * max-height). When false, the editor becomes a flex column and the textarea
   * flex-fills its container, then scrolls — use for flex-sized regions like the
   * Live box and Audio-Note transcript. Flex fill (not `h-full`) is required so
   * the textarea fills containers sized only by `min-height`, where a percentage
   * height would not resolve.
   */
  autoGrow?: boolean;
  ariaLabel?: string;
}

export function FindReplaceTextEditor({
  value,
  onChange,
  readOnly = false,
  autoFocus = false,
  placeholder,
  className = '',
  textClassName = '',
  enableFindReplace = true,
  autoGrow = true,
  ariaLabel = 'Editable text',
}: FindReplaceTextEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [hasFocus, setHasFocus] = useState(false);
  const fr = useFindReplace({ textareaRef, value, onChange });

  const controlEnabled = enableFindReplace && !readOnly;
  const showControl = controlEnabled && (hasFocus || fr.isOpen);

  // Auto-grow to fit content, capped by the textarea's CSS max-height (then it
  // scrolls). Skipped when read-only or when autoGrow is off (fill-container).
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta || readOnly || !autoGrow) return;
    ta.style.height = 'auto';
    const maxH = parseFloat(getComputedStyle(ta).maxHeight);
    const target = Number.isFinite(maxH) ? Math.min(ta.scrollHeight, maxH) : ta.scrollHeight;
    if (target > 0) ta.style.height = `${target}px`;
  }, [value, readOnly, autoGrow]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const onContainerKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const mod = e.ctrlKey || e.metaKey;
      if (controlEnabled && mod && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        e.stopPropagation();
        fr.open('find');
      } else if (controlEnabled && mod && (e.key === 'h' || e.key === 'H')) {
        e.preventDefault();
        e.stopPropagation();
        fr.open('replace');
      } else if (e.key === 'Escape' && fr.isOpen) {
        e.preventDefault();
        e.stopPropagation();
        fr.close();
      }
    },
    [controlEnabled, fr],
  );

  return (
    <div
      className={`relative ${autoGrow ? '' : 'flex flex-col'} ${className}`}
      onKeyDown={onContainerKeyDown}
      onFocus={() => setHasFocus(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHasFocus(false);
      }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
        placeholder={placeholder}
        aria-label={ariaLabel}
        spellCheck={false}
        className={`w-full resize-none bg-transparent outline-none ${autoGrow ? '' : 'min-h-0 flex-1'} ${textClassName}`}
      />
      {showControl && <FindReplaceToolbar state={fr} />}
    </div>
  );
}
