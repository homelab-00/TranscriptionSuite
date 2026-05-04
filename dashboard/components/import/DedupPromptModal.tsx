/**
 * DedupPromptModal — prompts the user when an imported file matches a
 * prior recording's audio_hash (Issue #104, Story 2.4).
 *
 * AC2.4 contract:
 *   - AC2: two buttons, "Use existing" (primary) and "Create new"
 *   - AC4: focus moves to "Use existing" on open; Esc cancels; Tab cycles
 *     between buttons; both have descriptive `aria-label` attributes.
 *
 * The modal is purely presentational. The caller decides what each button
 * means in context (navigate to existing recording, proceed with import,
 * cancel) — this component only emits the selection.
 */

import { useRef } from 'react';

import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';

import { Button } from '../ui/Button';

import type { DedupMatch } from '../../src/api/types';

export type DedupChoice = 'use_existing' | 'create_new' | 'cancel';

export interface DedupPromptModalProps {
  open: boolean;
  match: DedupMatch | null;
  onChoice: (choice: DedupChoice) => void;
}

export function DedupPromptModal({ open, match, onChoice }: DedupPromptModalProps) {
  // AC2.4.AC4 — focus the primary button on open. Headless UI's Dialog
  // accepts an `initialFocus` ref and handles the focus transition for
  // us (preserving the first-focus contract through the portal mount).
  const useExistingRef = useRef<HTMLButtonElement | null>(null);

  if (!match) return null;

  const formattedDate = (() => {
    if (!match.created_at) return '';
    try {
      const dt = new Date(match.created_at);
      if (Number.isNaN(dt.getTime())) return match.created_at;
      return dt.toLocaleDateString();
    } catch {
      return match.created_at;
    }
  })();

  return (
    <Dialog
      open={open}
      onClose={() => onChoice('cancel')}
      className="relative z-10000"
      initialFocus={useExistingRef}
    >
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="flex w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center border-b border-white/10 bg-white/5 px-6 py-4 select-none">
            <DialogTitle className="text-base font-semibold text-white">
              Possible duplicate detected
            </DialogTitle>
          </div>
          <div className="bg-black/20 px-6 py-5 text-sm text-slate-300">
            <p>
              This recording matches an existing one:{' '}
              <span className="font-semibold text-white">&lsquo;{match.name}&rsquo;</span>
              {formattedDate ? (
                <>
                  {' '}
                  from <span className="text-slate-200">{formattedDate}</span>
                </>
              ) : null}
              .
            </p>
            <p className="mt-2">Use the existing transcript, or create a new entry?</p>
          </div>
          <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
            <Button
              variant="ghost"
              onClick={() => onChoice('create_new')}
              aria-label="Create new recording entry"
            >
              Create new
            </Button>
            <Button
              ref={useExistingRef}
              variant="primary"
              onClick={() => onChoice('use_existing')}
              aria-label="Use existing recording"
            >
              Use existing
            </Button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
