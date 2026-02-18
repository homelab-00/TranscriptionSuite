import React, { useState, useEffect } from 'react';
import { X, Github } from 'lucide-react';
import profileImage from '../../../build/assets/profile.png';

interface AboutModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AboutModal: React.FC<AboutModalProps> = ({ isOpen, onClose }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [appVersion, setAppVersion] = useState<string>(import.meta.env.VITE_APP_VERSION ?? '0.0.0');
  const [platform, setPlatform] = useState<string>('');
  const copyrightYears = '2025-2026';

  const openExternal = async (url: string): Promise<void> => {
    try {
      if (window.electronAPI?.app?.openExternal) {
        await window.electronAPI.app.openExternal(url);
        return;
      }
    } catch {
      // Fall through to browser open when Electron API is unavailable or fails.
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
      // Ensure initial state is applied before transition
      setIsVisible(false);

      // Fetch app version from Electron
      const api = window.electronAPI;
      if (api?.app) {
        api.app
          .getVersion()
          .then((v: string) => {
            if (v) setAppVersion(v);
          })
          .catch(() => {});
        setPlatform(api.app.getPlatform?.() ?? '');
      }

      // Double RAF to ensure DOM paint before transition
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      // Wait for transition to finish before unmounting (matches duration)
      timer = setTimeout(() => setIsRendered(false), 500);
    }

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  if (!isRendered) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />

      {/* Modal Content */}
      <div
        className={`relative flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-white/20 bg-linear-to-b from-white/5 to-black/20 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'} `}
      >
        <div className="bg-accent-cyan/20 pointer-events-none absolute top-0 left-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="bg-accent-magenta/10 pointer-events-none absolute right-0 bottom-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="pointer-events-none absolute inset-0 bg-white/1" />

        {/* Banner with Close Button */}
        <div className="from-accent-cyan/20 to-accent-magenta/20 relative h-32 bg-linear-to-br via-blue-600/10">
          <div className="absolute top-4 right-4 z-10">
            <button
              onClick={onClose}
              className="rounded-full border border-white/10 bg-black/10 p-2 text-white backdrop-blur-md transition-colors hover:bg-black/40"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Content Section */}
        <div className="relative z-0 -mt-12 flex flex-col items-center px-6 pb-8">
          {/* Avatar Profile Picture */}
          <div className="group mb-4 h-24 w-24 rounded-full border border-white/10 bg-[#0b1120] p-1.5 shadow-2xl">
            <div className="relative h-full w-full overflow-hidden rounded-full bg-linear-to-br from-slate-700 to-slate-800">
              <img
                src={profileImage}
                alt="Profile"
                className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
              />
            </div>
          </div>

          {/* Name & Title */}
          <h2 className="mb-0.5 text-xl font-bold tracking-tight text-white">
            Transcription Suite
          </h2>
          <p className="text-accent-cyan mb-4 text-xs font-medium tracking-widest uppercase">
            v{appVersion}
            {platform ? ` • ${platform}` : ''}
          </p>

          {/* Description */}
          <p className="mb-6 px-2 text-center text-sm leading-relaxed text-slate-300">
            A fully local and private Speech-To-Text app with cross-platform support, speaker
            diarization, Audio Notebook mode, LM Studio integration, and both longform and live
            transcription.
          </p>

          {/* Links */}
          <div className="mb-8 grid w-full grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => void openExternal('https://github.com/homelab-00/TranscriptionSuite')}
              className="group border-accent-cyan/20 bg-accent-cyan/20 flex flex-col items-center justify-center gap-2 rounded-2xl border p-3 transition-all hover:border-white/10 hover:bg-white/10"
            >
              <Github
                size={20}
                className="text-accent-cyan transition-colors group-hover:text-white"
              />
              <span className="text-accent-cyan text-xs font-medium group-hover:text-white">
                Repository
              </span>
            </button>
            <button
              type="button"
              onClick={() => void openExternal('https://github.com/homelab-00')}
              className="group border-accent-magenta/20 bg-accent-magenta/10 flex flex-col items-center justify-center gap-2 rounded-2xl border p-3 transition-all hover:border-white/10 hover:bg-white/10"
            >
              <div className="relative">
                <Github
                  size={20}
                  className="text-accent-magenta transition-colors group-hover:text-white"
                />
                <div className="bg-accent-cyan absolute -right-1 -bottom-1 h-2.5 w-2.5 rounded-full border-2 border-slate-900"></div>
              </div>
              <span className="text-accent-magenta text-xs font-medium group-hover:text-white">
                Profile
              </span>
            </button>
          </div>

          {/* Footer / License */}
          <div className="flex w-full flex-col items-center gap-1.5 border-t border-white/10 pt-6">
            <p className="text-[10px] font-medium tracking-widest text-slate-400 uppercase">
              GNU GPLv3+ © {copyrightYears}
            </p>
            <div className="flex items-center gap-1.5 text-xs text-slate-300">
              <span>Designed by</span>
              <button
                type="button"
                onClick={() => void openExternal('https://github.com/homelab-00')}
                className="hover:text-accent-cyan font-medium text-white transition-colors"
              >
                homelab-00
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
