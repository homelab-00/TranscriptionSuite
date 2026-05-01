import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, FileAudio, Calendar, Trash2, Info } from 'lucide-react';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { GlassCard } from '../ui/GlassCard';
import { useImportQueueStore } from '../../src/stores/importQueueStore';
import { apiClient } from '../../src/api/client';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useLanguages } from '../../src/hooks/useLanguages';
import { getConfig } from '../../src/config/store';
import {
  isCanaryModel,
  supportsAutoDetect,
  supportsTranslation,
} from '../../src/services/modelCapabilities';
import { toast } from 'sonner';

interface AddNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTime?: number; // e.g. 10 for 10:00
  initialDate?: string; // e.g. 2026-02-17
  initialFiles?: File[]; // GH #92: pre-populated when opened via per-hour drag-and-drop
  supportsExplicitWordTimestampToggle?: boolean;
}

const DATE_KEY_RE = /^\d{4}-\d{2}-\d{2}$/;

const formatDateKey = (date: Date): string =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

const buildLocalSlotTimestamp = (dateKey: string, hour: number): string =>
  `${dateKey}T${String(hour).padStart(2, '0')}:00:00`;

export const AddNoteModal: React.FC<AddNoteModalProps> = ({
  isOpen,
  onClose,
  initialTime,
  initialDate,
  initialFiles,
  supportsExplicitWordTimestampToggle = true,
}) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Form State
  const [title, setTitle] = useState('');
  const [isDiarizationEnabled, setIsDiarizationEnabled] = useState(false);
  const [isTimestampsEnabled, setIsTimestampsEnabled] = useState(true);
  const [parallelDiarization, setParallelDiarization] = useState<boolean>(false);
  const [parallelDefault, setParallelDefault] = useState<boolean>(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // gh-102 followup #2: notebook-upload surface honors the same Source
  // Language and translation selection persisted by SessionView. Mirrors the
  // SessionImportTab load pattern (SessionImportTab.tsx:122–183 / 163–183) —
  // the persisted picker is the single source of truth, no duplicate UI here.
  const [mainLanguage, setMainLanguage] = useState<string>('Auto Detect');
  const [mainTranslate, setMainTranslate] = useState<boolean>(false);
  const [mainBidiTarget, setMainBidiTarget] = useState<string>('Off');

  const admin = useAdminStatus();
  const activeModel: string | null =
    admin.status?.config?.main_transcriber?.model ??
    admin.status?.config?.transcription?.model ??
    null;
  const { languages, loading: languagesLoading } = useLanguages(activeModel);
  // Mirror SessionImportTab.tsx:129–130 — same predicate shape so the
  // notebook surface produces the same translation envelope handleFiles
  // produces for live recording / session-import.
  const isCanaryMainBidi = isCanaryModel(activeModel) && mainLanguage === 'English';
  const canTranslate = supportsTranslation(activeModel);

  const selectedDateKey =
    initialDate && DATE_KEY_RE.test(initialDate) ? initialDate : formatDateKey(new Date());
  const selectedDateLabel = new Date(`${selectedDateKey}T00:00:00`).toLocaleDateString([], {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

  // Constraint: diarization ON → force timestamps ON
  const handleDiarizationChange = useCallback((enabled: boolean) => {
    setIsDiarizationEnabled(enabled);
    if (enabled) setIsTimestampsEnabled(true);
  }, []);

  // Constraint: timestamps OFF → force diarization OFF
  const handleTimestampsChange = useCallback(
    (enabled: boolean) => {
      if (!supportsExplicitWordTimestampToggle) {
        setIsTimestampsEnabled(true);
        return;
      }
      setIsTimestampsEnabled(enabled);
      if (!enabled) setIsDiarizationEnabled(false);
    },
    [supportsExplicitWordTimestampToggle],
  );

  useEffect(() => {
    if (!supportsExplicitWordTimestampToggle) {
      setIsTimestampsEnabled(true);
    }
  }, [supportsExplicitWordTimestampToggle]);

  // gh-102 followup #2: hydrate the persisted Source Language picker
  // selection (and Canary bidi state) from config. Mirrors
  // SessionImportTab.tsx:163–183 so all import surfaces converge on the same
  // source-of-truth on every mount and every config change driven by setConfig
  // writes from SessionView.
  useEffect(() => {
    let active = true;
    void (async () => {
      const [savedMainLanguage, savedMainTranslate, savedMainBidiTarget] = await Promise.all([
        getConfig<string>('session.mainLanguage'),
        getConfig<boolean>('session.mainTranslate'),
        getConfig<string>('session.mainBidiTarget'),
      ]);
      if (!active) return;
      if (typeof savedMainLanguage === 'string' && savedMainLanguage) {
        setMainLanguage(savedMainLanguage);
      }
      if (typeof savedMainTranslate === 'boolean') setMainTranslate(savedMainTranslate);
      if (typeof savedMainBidiTarget === 'string' && savedMainBidiTarget) {
        setMainBidiTarget(savedMainBidiTarget);
      }
    })().catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Resolve language code from display name. Mirrors SessionImportTab.tsx:270–277.
  const resolveLanguage = useCallback(
    (name: string): string | undefined => {
      if (name === 'Auto Detect') return undefined;
      const match = languages.find((l) => l.name === name);
      return match?.code;
    },
    [languages],
  );

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    const fileArray = Array.from(files);
    setSelectedFiles((prev) => [...prev, ...fileArray]);
    setError(null);
    // Default title to first file's name (minus extension)
    if (fileArray[0]) {
      const nameWithoutExt = fileArray[0].name.replace(/\.[^.]+$/, '');
      setTitle(nameWithoutExt);
    }
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

    // gh-102 followup #2: mirror SessionImportTab.handleFiles guard
    // (SessionImportTab.tsx:291–301). The Canary backend (canary_backend.py:79)
    // raises ValueError when `language` is missing. Without this guard,
    // submitting a notebook upload on Canary with an unresolvable picker
    // (Auto Detect, languages still loading, stale display name) round-trips
    // to the backend fail-loud path. Wording matches the live-recording /
    // session-import guard verbatim so future copy changes propagate via grep.
    const resolvedLang = resolveLanguage(mainLanguage);
    if (resolvedLang === undefined && !supportsAutoDetect(activeModel)) {
      toast.error('Source language required', {
        description: languagesLoading
          ? 'Loading languages — please try again in a moment.'
          : mainLanguage
            ? `"${mainLanguage}" is not a valid source language for the active model. Pick a language from the Source Language dropdown.`
            : 'No source language is selected. Pick a language from the Source Language dropdown.',
      });
      return;
    }

    // Translation parity: mirror SessionImportTab.tsx:308–313 so the notebook
    // surface produces the same envelope live recording / session-import
    // produce. Canary bidi (English source + non-Off target) drives
    // translate=true; the regular Whisper translate-to-English toggle is only
    // honored when the active model supports translation.
    const mainTranslateActive = isCanaryMainBidi
      ? mainBidiTarget !== 'Off'
      : mainTranslate && canTranslate;
    const mainTranslateTarget = isCanaryMainBidi ? (resolveLanguage(mainBidiTarget) ?? 'en') : 'en';

    setIsSubmitting(true);
    setError(null);

    try {
      // Build a created-at timestamp from the time slot
      let fileCreatedAt: string | undefined;
      if (initialTime !== undefined) {
        fileCreatedAt = buildLocalSlotTimestamp(selectedDateKey, initialTime);
      }
      const enableWordTimestamps = supportsExplicitWordTimestampToggle ? isTimestampsEnabled : true;

      useImportQueueStore.getState().addFiles(selectedFiles, 'notebook-normal', {
        language: resolvedLang,
        translation_enabled: mainTranslateActive ? true : undefined,
        translation_target_language: mainTranslateActive ? mainTranslateTarget : undefined,
        enable_diarization: isDiarizationEnabled,
        enable_word_timestamps: enableWordTimestamps,
        parallel_diarization: isDiarizationEnabled ? parallelDiarization : undefined,
        file_created_at: fileCreatedAt,
        title: title.trim() || undefined,
      });

      toast.success(
        `Queued ${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} for import`,
      );

      // Queueing is immediate; close the modal and let the shared import queue
      // process uploads in the background.
      setSelectedFiles([]);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Upload failed. Is the server running?');
    } finally {
      setIsSubmitting(false);
    }
  }, [
    selectedFiles,
    isDiarizationEnabled,
    isTimestampsEnabled,
    parallelDiarization,
    initialTime,
    onClose,
    selectedDateKey,
    supportsExplicitWordTimestampToggle,
    title,
    activeModel,
    mainLanguage,
    mainTranslate,
    mainBidiTarget,
    isCanaryMainBidi,
    canTranslate,
    languagesLoading,
    resolveLanguage,
  ]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;

    if (isOpen) {
      setIsRendered(true);
      // GH #92: when files are preloaded via drag-and-drop on a time slot,
      // seed selectedFiles and prefer the first file's name as the default
      // title (matches the in-modal drop behavior in handleFiles).
      if (initialFiles && initialFiles.length > 0) {
        setSelectedFiles(initialFiles);
        const firstName = initialFiles[0].name.replace(/\.[^.]+$/, '');
        setTitle(firstName);
      } else {
        // Set default title based on time
        if (initialTime !== undefined) {
          const timeStr = `${initialTime.toString().padStart(2, '0')}:00`;
          setTitle(`${timeStr} Recording`);
        } else {
          setTitle('New Recording');
        }
        setSelectedFiles([]);
      }
      setError(null);
      setIsSubmitting(false);

      // Fetch server default for parallel diarization
      apiClient
        .getAdminStatus()
        .then((status) => {
          const val = status.config?.diarization?.parallel ?? false;
          setParallelDefault(val);
          setParallelDiarization(val);
        })
        .catch(() => {});

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
    // GH #92 review: do NOT include `initialFiles` (or `initialTime`) in
    // deps. They are captured at the time the modal opens; re-running this
    // effect on every parent re-render that produces a new array reference
    // would clobber the user's edits to title/selectedFiles mid-flight.
    // Seeding intentionally happens only on the isOpen→true transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

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
                {initialTime !== undefined
                  ? `${selectedDateLabel}, ${String(initialTime).padStart(2, '0')}:00 - ${String((initialTime + 1) % 24).padStart(2, '0')}:00`
                  : selectedDateLabel}
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

          {/* Import Info Note */}
          <div className="flex items-start gap-2 rounded-lg bg-white/5 px-3 py-2.5">
            <Info size={14} className="mt-0.5 shrink-0 text-slate-500" />
            <p className="text-xs leading-relaxed text-slate-500">
              Imported audio files will be saved as audio notes using the file name as the note
              title and the file's creation date as the recording date.
            </p>
          </div>

          {/* 3. Configuration Options */}
          <GlassCard title="Import Options">
            <div className="space-y-4">
              <AppleSwitch
                checked={isDiarizationEnabled}
                onChange={handleDiarizationChange}
                label="Speaker Diarization"
                description="Identify distinct speakers in the audio"
              />
              {isDiarizationEnabled && (
                <>
                  <div className="h-px bg-white/5"></div>
                  <div className="pl-1">
                    <AppleSwitch
                      checked={parallelDiarization}
                      onChange={setParallelDiarization}
                      label="Parallel Processing"
                      description={
                        parallelDiarization === parallelDefault
                          ? 'Using server default'
                          : 'Override'
                      }
                    />
                  </div>
                </>
              )}
              <div className="h-px bg-white/5"></div>
              <AppleSwitch
                checked={isTimestampsEnabled}
                onChange={handleTimestampsChange}
                label="Word-level Timestamps"
                description={
                  supportsExplicitWordTimestampToggle
                    ? 'Generate precise timing for every word'
                    : 'Required by the current model and managed automatically'
                }
                disabled={!supportsExplicitWordTimestampToggle}
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
            {isSubmitting ? 'Queueing...' : 'Create Note'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
};
