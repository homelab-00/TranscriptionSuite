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
        api.app.getVersion().then((v: string) => {
          if (v) setAppVersion(v);
        }).catch(() => {});
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
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`} 
        onClick={onClose} 
      />
      
      {/* Modal Content */}
      <div 
        className={`
            relative w-full max-w-sm bg-black/60 backdrop-blur-xl border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col 
            transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]
            ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'}
        `}
      >
        
        {/* Banner with Close Button */}
        <div className="h-32 bg-linear-to-br from-accent-cyan/20 via-blue-600/10 to-accent-magenta/20 relative">
           <div className="absolute top-4 right-4 z-10">
                <button 
                    onClick={onClose} 
                    className="p-2 bg-black/20 hover:bg-black/40 rounded-full text-white transition-colors backdrop-blur-md border border-white/5"
                >
                    <X size={16} />
                </button>
           </div>
        </div>

        {/* Content Section */}
        <div className="px-6 pb-8 -mt-12 flex flex-col items-center relative z-0">
            {/* Avatar Profile Picture */}
            <div className="w-24 h-24 rounded-full p-1.5 bg-[#0b1120] border border-white/10 shadow-2xl mb-4 group">
                 <div className="w-full h-full rounded-full overflow-hidden bg-linear-to-br from-slate-700 to-slate-800 relative">
                    <img 
                        src={profileImage}
                        alt="Profile" 
                        className="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                    />
                 </div>
            </div>

            {/* Name & Title */}
            <h2 className="text-xl font-bold text-white mb-0.5 tracking-tight">Transcription Suite</h2>
            <p className="text-xs font-medium text-accent-cyan tracking-widest uppercase mb-4">v{appVersion}{platform ? ` • ${platform}` : ''}</p>
            
            {/* Description */}
            <p className="text-slate-400 text-sm leading-relaxed text-center mb-6 px-2">
                A fully local and private Speech-To-Text app with cross-platform support, speaker diarization, Audio Notebook mode, LM Studio integration, and both longform and live transcription.
            </p>

            {/* Links */}
            <div className="w-full grid grid-cols-2 gap-3 mb-8">
                <button
                    type="button"
                    onClick={() => void openExternal('https://github.com/homelab-00/TranscriptionSuite')}
                    className="flex flex-col items-center justify-center gap-2 p-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/5 hover:border-white/10 transition-all group"
                >
                    <Github size={20} className="text-slate-300 group-hover:text-white transition-colors" />
                    <span className="text-xs font-medium text-slate-400 group-hover:text-slate-200">Repository</span>
                </button>
                <button
                    type="button"
                    onClick={() => void openExternal('https://github.com/homelab-00')}
                    className="flex flex-col items-center justify-center gap-2 p-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/5 hover:border-white/10 transition-all group"
                >
                     <div className="relative">
                        <Github size={20} className="text-slate-300 group-hover:text-white transition-colors" />
                        <div className="absolute -bottom-1 -right-1 bg-accent-cyan w-2.5 h-2.5 rounded-full border-2 border-[#0f172a]"></div>
                     </div>
                    <span className="text-xs font-medium text-slate-400 group-hover:text-slate-200">Profile</span>
                </button>
            </div>

            {/* Footer / License */}
             <div className="w-full pt-6 border-t border-white/5 flex flex-col items-center gap-1.5">
                 <p className="text-[10px] font-medium text-slate-500 uppercase tracking-widest">GNU GPLv3+ © {copyrightYears}</p>
                 <div className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span>Designed by</span>
                    <button
                      type="button"
                      onClick={() => void openExternal('https://github.com/homelab-00')}
                      className="text-white font-medium hover:text-accent-cyan transition-colors"
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
