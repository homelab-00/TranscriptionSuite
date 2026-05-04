/**
 * Inline speaker-rename input — Issue #104, Story 4.3.
 *
 * Click (or focus + Enter) on a speaker label transitions the chip into
 * a text-input pre-filled with the current display label. Enter commits
 * (calls onCommit), Esc cancels. Blur also commits (treats blur as
 * "soft-Enter" — matches the AudioNoteModal title rename UX).
 *
 * Accessibility (FR51, FR53):
 *   - The input has `aria-label="Speaker label for {speakerId}"`.
 *   - The screen-reader announcement on focus ("Edit speaker label,
 *     current value: {label}") is fired by the parent via the
 *     ariaAnnouncement prop, dispatched through the ARIA live region
 *     (Sprint 1 useAriaAnnouncer).
 *   - Tab order is dictated by DOM order — no manual tabIndex other
 *     than the default (0).
 */

import { useEffect, useRef, useState } from 'react';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';

interface Props {
  /** The raw speaker_id (e.g. "SPEAKER_00"). Stays constant across renames. */
  speakerId: string;
  /** The current display label (alias_name OR "Speaker N" fallback). */
  currentLabel: string;
  /** Optional Tailwind classes to keep visual parity with the surrounding chip. */
  className?: string;
  /** Whether the speaker label can be edited. Defaults to true. */
  editable?: boolean;
  /** Called with the trimmed new name when the user commits. */
  onCommit: (newName: string) => void;
}

export function SpeakerRenameInput({
  speakerId,
  currentLabel,
  className,
  editable = true,
  onCommit,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(currentLabel);
  const inputRef = useRef<HTMLInputElement>(null);
  const announce = useAriaAnnouncer();

  // Keep input in sync if the underlying alias was changed elsewhere
  useEffect(() => {
    if (!editing) setValue(currentLabel);
  }, [currentLabel, editing]);

  // Focus + announce on edit-mode entry
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
      announce(`Edit speaker label, current value: ${currentLabel}`);
    }
  }, [editing, currentLabel, announce]);

  if (!editing || !editable) {
    return (
      <button
        type="button"
        className={className}
        disabled={!editable}
        onClick={() => editable && setEditing(true)}
        onKeyDown={(e) => {
          if (editable && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            setEditing(true);
          }
        }}
        aria-label={`Rename speaker label for ${speakerId}, current value: ${currentLabel}`}
        title={editable ? 'Click to rename speaker' : currentLabel}
      >
        {currentLabel}
      </button>
    );
  }

  const commit = () => {
    const trimmed = value.trim();
    setEditing(false);
    if (trimmed && trimmed !== currentLabel) {
      onCommit(trimmed);
    } else {
      // No-op — restore label
      setValue(currentLabel);
    }
  };

  const cancel = () => {
    setValue(currentLabel);
    setEditing(false);
  };

  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commit();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          cancel();
        }
      }}
      onBlur={commit}
      aria-label={`Speaker label for ${speakerId}`}
      className={className}
      maxLength={120}
    />
  );
}
