import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { ModelManagerTab, type ModelManagerTabProps } from './ModelManagerTab';

export interface ModelManagerModalProps extends ModelManagerTabProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Full cross-family Model Manager, reached from the "Manage all models"
 * button inside MainModelPicker. Renders ModelManagerTab directly against
 * the state ServerView already owns.
 *
 * ModelManagerTab is presentational: it takes every selection value as a
 * prop and holds no electron-store effects of its own. This modal must
 * never wrap the old ModelManagerView instead, since that component owned
 * its own copy of the model selection state and persisted it to the same
 * electron-store keys as ServerView - mounting both at once would race two
 * writers on those keys and silently drop whichever change landed second.
 */
export function ModelManagerModal({
  isOpen,
  onClose,
  ...tabProps
}: ModelManagerModalProps): React.ReactElement | null {
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const modalContent = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Model Manager"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/60" aria-hidden="true" />

      <div
        className="relative flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-white">Model Manager</h2>
            <p className="-mt-0.5 text-xs text-slate-400">
              Browse, download, and manage model weights.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full border border-white/10 bg-black/10 p-2 text-white transition-colors hover:bg-black/40"
          >
            <X size={16} />
          </button>
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto p-6">
          <ModelManagerTab {...tabProps} />
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
