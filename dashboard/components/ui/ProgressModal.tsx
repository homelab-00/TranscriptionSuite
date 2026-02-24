import React from 'react';

export interface ProgressModalProps {
  isOpen: boolean;
  title?: string;
  message: string;
  phase: number; // 0-100 for determinate, -1 for error, -2 for indeterminate
  onClose?: () => void;
  allowClose?: boolean; // Default false - prevent closing during critical operations
}

export const ProgressModal: React.FC<ProgressModalProps> = ({
  isOpen,
  title = 'Loading Model',
  message,
  phase,
  onClose,
  allowClose = false,
}) => {
  if (!isOpen) return null;

  const isError = phase === -1;
  const isIndeterminate = phase === -2;
  const progressPercent = Math.min(Math.max(phase, 0), 100);

  const handleBackdropClick = () => {
    if (allowClose && onClose) {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
        onClick={handleBackdropClick}
      />

      {/* Modal */}
      <div className="relative flex w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
        {/* Header */}
        <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          {allowClose && onClose && (
            <button
              onClick={onClose}
              className="ml-4 text-slate-400 transition-colors hover:text-white"
              aria-label="Close"
            >
              <svg
                className="h-5 w-5"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 bg-black/20 p-6">
          {/* Status Message */}
          <div className="mb-4 text-sm text-slate-300">
            <p className="leading-relaxed">{message}</p>
          </div>

          {/* Progress Bar Container */}
          <div className="relative h-2 overflow-hidden rounded-full bg-white/10">
            {isError ? (
              // Error state - red bar
              <div className="h-full w-full bg-linear-to-r from-red-500 to-red-600" />
            ) : isIndeterminate ? (
              // Indeterminate animation
              <div className="h-full w-full overflow-hidden">
                <div className="animate-progress-indeterminate from-accent-cyan h-full w-1/3 bg-linear-to-r to-blue-500" />
              </div>
            ) : (
              // Determinate progress
              <div
                className="from-accent-cyan h-full bg-linear-to-r to-blue-500 transition-all duration-500 ease-out"
                style={{ width: `${progressPercent}%` }}
              />
            )}
          </div>

          {/* Phase Percentage (if not error or indeterminate) */}
          {!isError && !isIndeterminate && (
            <div className="mt-2 text-right text-xs text-slate-400">{progressPercent}%</div>
          )}
        </div>

        {/* Footer (only show if error or allow close) */}
        {(isError || allowClose) && (
          <div className="flex flex-none justify-end border-t border-white/10 bg-white/5 px-6 py-4 select-none">
            {onClose && (
              <button
                onClick={onClose}
                className={`inline-flex h-10 items-center justify-center rounded-lg px-4 text-sm font-medium transition-all duration-200 active:scale-95 ${
                  isError
                    ? 'border border-red-500/20 bg-red-500/10 text-red-400 hover:bg-red-500/20'
                    : 'border border-white/10 bg-white/5 text-white hover:bg-white/10'
                }`}
              >
                {isError ? 'Close' : 'Cancel'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
