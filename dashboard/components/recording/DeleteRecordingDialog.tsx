/**
 * DeleteRecordingDialog — confirmation dialog for recording deletion
 * with the Story 3.7 on-disk-artifact opt-in checkbox.
 *
 * AC3.7 contract:
 *   - AC1: dialog text explicitly states on-disk files are kept by default
 *   - AC2: confirming with checkbox UNCHECKED leaves on-disk files alone
 *   - AC3: confirming with checkbox CHECKED requests artifact deletion
 *   - AC4: tab order is text → checkbox → Cancel → Delete; the Delete
 *     button has aria-label="Confirm delete recording {name}"
 */

import { useRef, useState } from 'react';

import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';

import { Button } from '../ui/Button';

export interface DeleteRecordingDialogProps {
  open: boolean;
  recordingName: string;
  onCancel: () => void;
  onConfirm: (deleteArtifacts: boolean) => void;
}

export function DeleteRecordingDialog({
  open,
  recordingName,
  onCancel,
  onConfirm,
}: DeleteRecordingDialogProps) {
  const [deleteArtifacts, setDeleteArtifacts] = useState(false);
  // AC3.7.AC4 — initial focus lands on the dialog body (the descriptive
  // text), so the screen reader reads the warning before any focusable
  // control. The first Tab moves to the checkbox, then Cancel, then
  // Delete (DOM order).
  const initialFocusRef = useRef<HTMLDivElement | null>(null);

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      className="relative z-10000"
      initialFocus={initialFocusRef}
    >
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="flex w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center border-b border-white/10 bg-white/5 px-6 py-4 select-none">
            <DialogTitle className="text-base font-semibold text-white">
              Delete recording
            </DialogTitle>
          </div>
          <div
            ref={initialFocusRef}
            tabIndex={-1}
            className="space-y-3 bg-black/20 px-6 py-5 text-sm text-slate-300 focus:outline-none"
          >
            <p>
              Delete recording{' '}
              <span className="font-semibold text-white">&lsquo;{recordingName}&rsquo;</span>? This
              removes the recording from your library. On-disk transcript and summary files exported
              to your folders will <span className="font-semibold text-amber-200">NOT</span> be
              deleted by default — you can opt in below.
            </p>
            <label className="flex items-start gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={deleteArtifacts}
                onChange={(e) => setDeleteArtifacts(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                Also delete on-disk transcript and summary files exported by this recording.
              </span>
            </label>
          </div>
          <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => onConfirm(deleteArtifacts)}
              aria-label={`Confirm delete recording ${recordingName}`}
            >
              Delete
            </Button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
