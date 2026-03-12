import React, { useState, useEffect } from 'react';
import { X, Star, ExternalLink } from 'lucide-react';

interface StarPopupModalProps {
  isOpen: boolean;
  onDismiss: () => void;
}

const REPO_URL = 'https://github.com/homelab-00/TranscriptionSuite';

export const StarPopupModal: React.FC<StarPopupModalProps> = ({ isOpen, onDismiss }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  const openExternal = async (url: string): Promise<void> => {
    try {
      if (window.electronAPI?.app?.openExternal) {
        await window.electronAPI.app.openExternal(url);
        return;
      }
    } catch {
      // Fall through
    }
    if (!window.electronAPI) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;

    if (isOpen) {
      setIsRendered(true);
      setIsVisible(false);

      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 500);
    }

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  const handleStar = () => {
    void openExternal(REPO_URL);
    onDismiss();
  };

  if (!isRendered) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onDismiss}
      />

      {/* Modal Content */}
      <div
        className={`relative flex w-full max-w-xs flex-col overflow-hidden rounded-3xl border border-white/20 bg-black/40 bg-linear-to-b from-white/5 to-black/20 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'} `}
      >
        <div className="bg-accent-cyan/20 pointer-events-none absolute top-0 left-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="bg-accent-magenta/10 pointer-events-none absolute right-0 bottom-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="pointer-events-none absolute inset-0 bg-black/20" />

        {/* Close button */}
        <div className="absolute top-4 right-4 z-10">
          <button
            onClick={onDismiss}
            className="rounded-full border border-white/10 bg-black/10 p-2 text-white backdrop-blur-md transition-colors hover:bg-black/40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="relative z-0 flex flex-col items-center gap-4 px-6 py-8">
          <div className="flex h-16 w-16 items-center justify-center rounded-full border border-yellow-400/20 bg-yellow-400/10">
            <Star size={32} className="text-yellow-400" />
          </div>

          <h2 className="text-center text-lg font-semibold text-white">
            Enjoying TranscriptionSuite?
          </h2>
          <p className="text-center text-sm leading-relaxed text-slate-300">
            If you find this project useful, consider leaving a star on GitHub. It helps others
            discover it!
          </p>

          <div className="flex w-full flex-col gap-2 pt-2">
            <button
              onClick={handleStar}
              className="flex items-center justify-center gap-2 rounded-xl border border-yellow-400/30 bg-yellow-400/20 px-4 py-2.5 text-sm font-medium text-yellow-300 transition-colors hover:bg-yellow-400/30"
            >
              <ExternalLink size={16} />
              Star on GitHub
            </button>
            <button
              onClick={onDismiss}
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
            >
              Maybe Later
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
