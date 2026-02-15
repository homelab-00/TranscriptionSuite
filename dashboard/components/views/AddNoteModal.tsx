
import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, FileAudio, Calendar } from 'lucide-react';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { GlassCard } from '../ui/GlassCard';

interface AddNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTime?: number; // e.g. 10 for 10:00
}

export const AddNoteModal: React.FC<AddNoteModalProps> = ({ isOpen, onClose, initialTime }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  
  // Form State
  const [title, setTitle] = useState('');
  const [isDiarizationEnabled, setIsDiarizationEnabled] = useState(true);
  const [isTimestampsEnabled, setIsTimestampsEnabled] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;

    if (isOpen) {
      setIsRendered(true);
      // Set default title based on time
      if (initialTime !== undefined) {
        const timeStr = `${initialTime.toString().padStart(2, '0')}:00`;
        setTitle(`${timeStr} Recording`);
      } else {
        setTitle("New Recording");
      }

      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 300);
    }

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen, initialTime]);

  if (!isRendered) return null;

  return createPortal(
    <div className="fixed inset-0 z-9999 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div 
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />

      {/* Modal Window */}
      <div 
        className={`
            relative w-full max-w-xl bg-glass-surface backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl overflow-hidden flex flex-col
            transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]
            ${isVisible ? 'scale-100 opacity-100 translate-y-0' : 'scale-95 opacity-0 translate-y-4'}
        `}
      >
        {/* Header */}
        <div className="h-14 px-6 border-b border-white/5 bg-white/5 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white tracking-wide">New Audio Note</h2>
            <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
                <X size={18} />
            </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6 overflow-y-auto max-h-[80vh] custom-scrollbar">
            
            {/* 1. Time & Title */}
            <div className="space-y-4">
                <div className="flex items-center gap-2 text-xs font-medium text-accent-cyan uppercase tracking-wider">
                    <Calendar size={12} />
                    <span>Today, {initialTime}:00 - {initialTime ? initialTime + 1 : 1}:00</span>
                </div>
                <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1.5 ml-1">Note Title</label>
                    <input 
                        type="text" 
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:ring-1 focus:ring-accent-cyan transition-shadow"
                        placeholder="Enter title..."
                    />
                </div>
            </div>

            {/* 2. Upload Area - Matched to ImportTab */}
            <div className="border-2 border-dashed border-white/20 rounded-3xl p-8 flex flex-col items-center justify-center text-center hover:border-accent-cyan/50 hover:bg-accent-cyan/5 transition-all cursor-pointer group">
                <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
                    <Upload size={32} className="text-slate-300 group-hover:text-accent-cyan" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Drag & Drop Audio Files</h3>
                <p className="text-slate-400 text-xs mb-6">Supports MP3, WAV, M4A, FLAC</p>
                <Button variant="primary">Browse Files</Button>
            </div>

            {/* 3. Configuration Options - Matched to ImportTab */}
            <GlassCard title="Import Options">
                 <div className="space-y-4">
                    <AppleSwitch 
                        checked={isDiarizationEnabled} 
                        onChange={setIsDiarizationEnabled} 
                        label="Speaker Diarization" 
                        description="Identify distinct speakers in the audio"
                    />
                    <div className="h-px bg-white/5"></div>
                    <AppleSwitch 
                        checked={isTimestampsEnabled} 
                        onChange={setIsTimestampsEnabled} 
                        label="Word-level Timestamps" 
                        description="Generate precise timing for every word"
                    />
                 </div>
            </GlassCard>

        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/10 bg-black/20 flex justify-end gap-3">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={onClose} icon={<FileAudio size={16}/>}>Create Note</Button>
        </div>

      </div>
    </div>,
    document.body
  );
};
