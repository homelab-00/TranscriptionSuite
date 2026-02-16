import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, FileAudio, Calendar, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { GlassCard } from '../ui/GlassCard';
import { apiClient } from '../../src/api/client';

interface AddNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTime?: number; // e.g. 10 for 10:00
}

export const AddNoteModal: React.FC<AddNoteModalProps> = ({ isOpen, onClose, initialTime }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Form State
  const [title, setTitle] = useState('');
  const [isDiarizationEnabled, setIsDiarizationEnabled] = useState(false);
  const [isTimestampsEnabled, setIsTimestampsEnabled] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Constraint: diarization ON → force timestamps ON
  const handleDiarizationChange = useCallback((enabled: boolean) => {
    setIsDiarizationEnabled(enabled);
    if (enabled) setIsTimestampsEnabled(true);
  }, []);

  // Constraint: timestamps OFF → force diarization OFF
  const handleTimestampsChange = useCallback((enabled: boolean) => {
    setIsTimestampsEnabled(enabled);
    if (!enabled) setIsDiarizationEnabled(false);
  }, []);

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    setSelectedFiles((prev) => [...prev, ...Array.from(files)]);
    setError(null);
  }, []);

  const removeFile = useCallback((index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const handleSubmit = useCallback(async () => {
    if (selectedFiles.length === 0) {
      setError('Please select at least one audio file.');
      return;
    }
    setIsSubmitting(true);
    setError(null);

    try {
      // Build a created-at timestamp from the time slot
      let fileCreatedAt: string | undefined;
      if (initialTime !== undefined) {
        const now = new Date();
        now.setHours(initialTime, 0, 0, 0);
        fileCreatedAt = now.toISOString();
      }

      for (const file of selectedFiles) {
        await apiClient.uploadAndTranscribe(file, {
          enable_diarization: isDiarizationEnabled,
          enable_word_timestamps: isTimestampsEnabled,
          file_created_at: fileCreatedAt,
        });
      }
      // Success — reset and close
      setSelectedFiles([]);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Upload failed. Is the server running?');
    } finally {
      setIsSubmitting(false);
    }
  }, [selectedFiles, isDiarizationEnabled, isTimestampsEnabled, initialTime, onClose]);

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
        setTitle('New Recording');
      }
      // Reset state on open
      setSelectedFiles([]);
      setError(null);
      setIsSubmitting(false);

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
        className={`bg-glass-surface relative flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-white/10 shadow-2xl backdrop-blur-xl transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-4 scale-95 opacity-0'} `}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-white/5 bg-white/5 px-6">
          <h2 className="text-sm font-semibold tracking-wide text-white">New Audio Note</h2>
          <button onClick={onClose} className="text-slate-400 transition-colors hover:text-white">
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="custom-scrollbar max-h-[80vh] space-y-6 overflow-y-auto p-6">
          {/* 1. Time & Title */}
          <div className="space-y-4">
            <div className="text-accent-cyan flex items-center gap-2 text-xs font-medium tracking-wider uppercase">
              <Calendar size={12} />
              <span>
                Today, {initialTime}:00 - {initialTime ? initialTime + 1 : 1}:00
              </span>
            </div>
            <div>
              <label className="mb-1.5 ml-1 block text-xs font-medium text-slate-400">
                Note Title
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="focus:ring-accent-cyan w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white transition-shadow focus:ring-1 focus:outline-none"
                placeholder="Enter title..."
              />
            </div>
          </div>

          {/* 2. Upload Area */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".mp3,.wav,.m4a,.flac,.ogg,.webm,.opus"
            multiple
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`group flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-8 text-center transition-all ${
              isDragOver
                ? 'border-accent-cyan bg-accent-cyan/10 scale-[1.02]'
                : 'hover:border-accent-cyan/50 hover:bg-accent-cyan/5 border-white/20'
            }`}
          >
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-white/5 transition-transform group-hover:scale-110">
              <Upload size={32} className="group-hover:text-accent-cyan text-slate-300" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-white">Drag & Drop Audio Files</h3>
            <p className="mb-6 text-xs text-slate-400">
              Supports MP3, WAV, M4A, FLAC, OGG, WebM, Opus
            </p>
            <Button variant="primary">Browse Files</Button>
          </div>

          {/* Selected Files List */}
          {selectedFiles.length > 0 && (
            <div className="space-y-2">
              <span className="ml-1 text-xs font-medium text-slate-400">
                {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
              </span>
              {selectedFiles.map((file, i) => (
                <div
                  key={`${file.name}-${i}`}
                  className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2"
                >
                  <FileAudio size={14} className="text-accent-cyan shrink-0" />
                  <span className="flex-1 truncate text-sm text-white">{file.name}</span>
                  <span className="text-xs text-slate-500">
                    {(file.size / 1024 / 1024).toFixed(1)} MB
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFile(i);
                    }}
                    className="p-1 text-slate-500 transition-colors hover:text-red-400"
                    title="Remove"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 3. Configuration Options */}
          <GlassCard title="Import Options">
            <div className="space-y-4">
              <AppleSwitch
                checked={isDiarizationEnabled}
                onChange={handleDiarizationChange}
                label="Speaker Diarization"
                description="Identify distinct speakers in the audio"
              />
              <div className="h-px bg-white/5"></div>
              <AppleSwitch
                checked={isTimestampsEnabled}
                onChange={handleTimestampsChange}
                label="Word-level Timestamps"
                description="Generate precise timing for every word"
              />
            </div>
          </GlassCard>

          {/* Error Message */}
          {error && (
            <div className="rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 border-t border-white/10 bg-black/20 p-4">
          <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isSubmitting || selectedFiles.length === 0}
            icon={<FileAudio size={16} />}
          >
            {isSubmitting ? 'Uploading...' : 'Create Note'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
};
