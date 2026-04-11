import { useState, useCallback } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { Button } from '../../components/ui/Button';

interface ConfirmOptions {
  title?: string;
  confirmLabel?: string;
  danger?: boolean;
}

interface ConfirmState {
  message: string;
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

/**
 * Returns a `confirm(message, options?)` function that shows a styled dialog
 * and resolves to true (confirmed) or false (cancelled).
 * Also returns a `dialog` element that must be rendered in the component tree.
 */
export function useConfirm() {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback(
    (message: string, options: ConfirmOptions = {}): Promise<boolean> =>
      new Promise((resolve) => {
        setState({ message, options, resolve });
      }),
    [],
  );

  const handleClose = useCallback(
    (ok: boolean) => {
      state?.resolve(ok);
      setState(null);
    },
    [state],
  );

  const dialog = state ? (
    <Dialog open onClose={() => handleClose(false)} className="relative z-10000">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center border-b border-white/10 bg-white/5 px-6 py-4 select-none">
            <DialogTitle className="text-base font-semibold text-white">
              {state.options.title ?? 'Confirm'}
            </DialogTitle>
          </div>
          <div className="bg-black/20 px-6 py-5">
            <p className="text-sm text-slate-300">{state.message}</p>
          </div>
          <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
            <Button variant="ghost" onClick={() => handleClose(false)}>
              Cancel
            </Button>
            <Button
              variant={state.options.danger ? 'danger' : 'primary'}
              onClick={() => handleClose(true)}
            >
              {state.options.confirmLabel ?? 'Confirm'}
            </Button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  ) : null;

  return { confirm, dialog };
}
