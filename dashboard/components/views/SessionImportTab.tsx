import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Upload,
  Clock,
  Loader2,
  Check,
  AlertCircle,
  Trash2,
  RotateCcw,
  XCircle,
  Info,
  FolderOpen,
  FileText,
  Eye,
  Pause,
  Play,
  ChevronDown,
  WifiOff,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { useShallow } from 'zustand/react/shallow';
import {
  useImportQueueStore,
  selectSessionJobs,
  selectPendingCount,
  selectCompletedCount,
  selectErrorCount,
  selectIsProcessing,
} from '../../src/stores/importQueueStore';
import type { UnifiedImportJob } from '../../src/stores/importQueueStore';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useLanguages } from '../../src/hooks/useLanguages';
import { apiClient } from '../../src/api/client';
import { supportsExplicitWordTimestampToggle as supportsExplicitWordTimestampToggleForModel } from '../../src/utils/transcriptionBackend';
import { getConfig, setConfig } from '../../src/config/store';
import { useSessionWatcher } from '../../src/hooks/useSessionWatcher';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTimeEst(ms: number): string {
  const min = Math.round(ms / 60_000);
  if (min < 1) return '<1 min';
  return `${min} min`;
}

// ─── Component ───────────────────────────────────────────────────────────────

export const SessionImportTab: React.FC = () => {
  // Zustand store
  const jobs = useImportQueueStore(useShallow(selectSessionJobs));
  const isPaused = useImportQueueStore((s) => s.isPaused);
  const isProcessing = useImportQueueStore(selectIsProcessing);
  const pendingCount = useImportQueueStore(selectPendingCount);
  const completedCount = useImportQueueStore(selectCompletedCount);
  const errorCount = useImportQueueStore(selectErrorCount);
  const addFiles = useImportQueueStore((s) => s.addFiles);
  const removeJob = useImportQueueStore((s) => s.removeJob);
  const retryJob = useImportQueueStore((s) => s.retryJob);
  const clearFinished = useImportQueueStore((s) => s.clearFinished);
  const pauseQueue = useImportQueueStore((s) => s.pauseQueue);
  const resumeQueue = useImportQueueStore((s) => s.resumeQueue);
  const updateSessionConfig = useImportQueueStore((s) => s.updateSessionConfig);
  const watcherServerConnected = useImportQueueStore((s) => s.watcherServerConnected);
  const avgProcessingMs = useImportQueueStore((s) => s.avgProcessingMs);
  const watchLog = useImportQueueStore((s) => s.watchLog);
  const clearWatchLog = useImportQueueStore((s) => s.clearWatchLog);

  const {
    sessionWatchPath,
    sessionWatchActive,
    setSessionWatchActive,
    setWatchPath,
    sessionWatchAccessible,
  } = useSessionWatcher();
  const notebookWatchPath = useImportQueueStore((s) => s.notebookWatchPath);
  const watchConflict =
    sessionWatchPath && notebookWatchPath && sessionWatchPath === notebookWatchPath;

  const [outputDir, setOutputDir] = useState('');
  const [diarization, setDiarization] = useState(true);
  const [diarizedFormat, setDiarizedFormat] = useState<'srt' | 'ass'>('srt');
  const [wordTimestamps, setWordTimestamps] = useState(true);
  const [hideTimestamps, setHideTimestamps] = useState(false);
  const [parallelDiarization, setParallelDiarization] = useState<boolean>(false);
  const [parallelDefault, setParallelDefault] = useState<boolean>(false);
  const [multitrack, setMultitrack] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isDragOverWatch, setIsDragOverWatch] = useState(false);
  const [logExpanded, setLogExpanded] = useState(false);

  // 4.6 — first-run hint state
  const manualImportCountRef = useRef(0);
  const [showWatchHint, setShowWatchHint] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const admin = useAdminStatus();
  const activeModel: string | null =
    admin.status?.config?.main_transcriber?.model ??
    admin.status?.config?.transcription?.model ??
    null;
  const { backendType } = useLanguages(activeModel);
  const supportsExplicitWordTimestampToggle = activeModel
    ? supportsExplicitWordTimestampToggleForModel(activeModel)
    : backendType !== 'vibevoice_asr';

  // Fetch downloads path and hideTimestamps setting on mount
  useEffect(() => {
    const init = async () => {
      const electronAPI = (window as any).electronAPI;

      getConfig<boolean>('output.hideTimestamps').then((v) => setHideTimestamps(v ?? false));

      // Try to load persisted output dir from config
      const savedDir = await getConfig('sessionImport.outputDir');
      if (typeof savedDir === 'string' && savedDir) {
        setOutputDir(savedDir);
        return;
      }

      // Fall back to downloads path
      if (electronAPI?.fileIO) {
        try {
          const downloadsPath = await electronAPI.fileIO.getDownloadsPath();
          setOutputDir(downloadsPath);
        } catch {
          // Ignore — user can set manually
        }
      }
    };
    init();
  }, []);

  // 4.6 — load manual import count and hint state on mount
  useEffect(() => {
    Promise.all([
      getConfig<number>('stats.manualImportCount'),
      getConfig<boolean>('stats.watchFolderHintShown'),
    ]).then(([count, hintShown]) => {
      manualImportCountRef.current = count ?? 0;
      if (!hintShown && (count ?? 0) >= 3 && !sessionWatchPath) {
        setShowWatchHint(true);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch parallel diarization default
  useEffect(() => {
    apiClient
      .getAdminStatus()
      .then((status) => {
        const val = status.config?.diarization?.parallel ?? false;
        setParallelDefault(val);
        setParallelDiarization(val);
      })
      .catch(() => {});
  }, []);

  // Sync per-tab settings to the unified Zustand store. Folder Watch jobs read
  // these in handleFilesDetected so auto-imported files honor the user's UI
  // toggles (Issue #93). Raw values are stored — derivation rules
  // (multitrack ? false : enableDiarization, etc.) live in the store handler.
  useEffect(() => {
    updateSessionConfig({
      outputDir,
      diarizedFormat,
      hideTimestamps,
      enableDiarization: diarization,
      enableWordTimestamps: wordTimestamps,
      parallelDiarization,
      multitrack,
    });
  }, [
    outputDir,
    diarizedFormat,
    hideTimestamps,
    diarization,
    wordTimestamps,
    parallelDiarization,
    multitrack,
    updateSessionConfig,
  ]);

  useEffect(() => {
    if (!supportsExplicitWordTimestampToggle) {
      setWordTimestamps(true);
    }
  }, [supportsExplicitWordTimestampToggle]);

  // Hide hint once a watch path is selected
  useEffect(() => {
    if (sessionWatchPath && showWatchHint) {
      setShowWatchHint(false);
    }
  }, [sessionWatchPath, showWatchHint]);

  const handleDiarizationChange = useCallback((enabled: boolean) => {
    setDiarization(enabled);
    if (enabled) {
      setWordTimestamps(true);
      setMultitrack(false);
    }
  }, []);

  const handleTimestampsChange = useCallback(
    (enabled: boolean) => {
      if (!supportsExplicitWordTimestampToggle) {
        setWordTimestamps(true);
        return;
      }
      setWordTimestamps(enabled);
      if (!enabled) setDiarization(false);
    },
    [supportsExplicitWordTimestampToggle],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      addFiles(Array.from(files), 'session-normal', {
        enable_diarization: multitrack ? false : diarization,
        enable_word_timestamps: supportsExplicitWordTimestampToggle ? wordTimestamps : true,
        parallel_diarization: diarization && !multitrack ? parallelDiarization : undefined,
        multitrack: multitrack || undefined,
      });

      // 4.6 — track manual import count and possibly show hint
      const newCount = manualImportCountRef.current + files.length;
      manualImportCountRef.current = newCount;
      void setConfig('stats.manualImportCount', newCount);
      if (newCount >= 3 && !sessionWatchPath && !showWatchHint) {
        getConfig<boolean>('stats.watchFolderHintShown').then((shown) => {
          if (!shown) setShowWatchHint(true);
        });
      }
    },
    [
      addFiles,
      diarization,
      multitrack,
      parallelDiarization,
      supportsExplicitWordTimestampToggle,
      wordTimestamps,
      sessionWatchPath,
      showWatchHint,
    ],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const handleSelectFolder = useCallback(async () => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.fileIO) return;

    const selected = await electronAPI.fileIO.selectFolder();
    if (selected) {
      setOutputDir(selected);
      await setConfig('sessionImport.outputDir', selected);
    }
  }, []);

  const handleSelectWatchFolder = useCallback(async () => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.fileIO) return;
    const selected = await electronAPI.fileIO.selectFolder();
    if (selected) {
      await setWatchPath(selected);
    }
  }, [setWatchPath]);

  // 4.4 — drag a folder onto the watch path input area
  const handleWatchFolderDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOverWatch(false);
      const file = e.dataTransfer.files[0];
      if (!file) return;
      // Electron exposes the native filesystem path on dropped items
      const folderPath = (file as any).path as string | undefined;
      if (folderPath) {
        await setWatchPath(folderPath);
      }
    },
    [setWatchPath],
  );

  const handleOpenOutputPath = useCallback((filePath: string) => {
    const electronAPI = (window as any).electronAPI;
    if (electronAPI?.app?.openPath) {
      // Open the containing directory
      const dir = filePath.substring(0, filePath.lastIndexOf('/'));
      electronAPI.app.openPath(dir);
    }
  }, []);

  const dismissWatchHint = useCallback(async () => {
    setShowWatchHint(false);
    await setConfig('stats.watchFolderHintShown', true);
  }, []);

  const statusIcon = (job: UnifiedImportJob) => {
    switch (job.status) {
      case 'pending':
        return <Clock size={14} className="text-slate-400" />;
      case 'processing':
        return <Loader2 size={14} className="text-accent-cyan animate-spin" />;
      case 'writing':
        return <FileText size={14} className="text-accent-cyan animate-pulse" />;
      case 'success':
        return <Check size={14} className="text-green-400" />;
      case 'error':
        return <AlertCircle size={14} className="text-red-400" />;
    }
  };

  const statusLabel = (job: UnifiedImportJob) => {
    switch (job.status) {
      case 'pending':
        return 'Queued';
      case 'processing': {
        const progress = (admin.status?.models as any)?.job_tracker?.progress;
        if (progress?.total > 0) {
          return `Chunk ${progress.current}/${progress.total}`;
        }
        return 'Processing...';
      }
      case 'writing':
        return 'Saving file...';
      case 'success':
        return job.outputFilename ? `Done — ${job.outputFilename}` : 'Done';
      case 'error':
        return job.error ?? 'Failed';
    }
  };

  const hasElectronApi =
    typeof window !== 'undefined' && Boolean((window as any).electronAPI?.fileIO);

  return (
    <div className="mx-auto mt-10 max-w-2xl space-y-8">
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

      {/* Drop Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`group flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-12 text-center transition-all ${
          isDragOver
            ? 'border-accent-cyan bg-accent-cyan/10 scale-[1.02]'
            : 'hover:border-accent-cyan/50 hover:bg-accent-cyan/5 border-white/20'
        }`}
      >
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-white/5 transition-transform group-hover:scale-110">
          <Upload size={32} className="group-hover:text-accent-cyan text-slate-300" />
        </div>
        <h3 className="mb-2 text-xl font-semibold text-white">Drag & Drop Audio Files</h3>
        <p className="mb-6 text-sm text-slate-400">
          Supports MP3, WAV, M4A, FLAC, OGG, WebM, Opus — multiple files OK
        </p>
        <Button variant="primary">Browse Files</Button>
      </div>

      {/* 4.6 — First-run hint: suggest watch folder after 3+ manual imports */}
      {showWatchHint && hasElectronApi && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2.5">
          <Info size={14} className="mt-0.5 shrink-0 text-amber-400" />
          <p className="flex-1 text-xs text-amber-300">
            Tip: Use <strong>Folder Watch</strong> below to automatically process new files without
            dragging them in each time.
          </p>
          <button
            onClick={dismissWatchHint}
            className="shrink-0 text-slate-500 transition-colors hover:text-slate-400"
            title="Dismiss"
          >
            <XCircle size={14} />
          </button>
        </div>
      )}

      {/* Output Location */}
      {hasElectronApi && (
        <GlassCard title="Output Location">
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={outputDir}
              readOnly
              className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300 outline-none"
              placeholder="Select output folder..."
            />
            <button
              onClick={handleSelectFolder}
              className="hover:bg-accent-cyan/10 hover:text-accent-cyan flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-400 transition-colors"
            >
              <FolderOpen size={14} />
              Browse
            </button>
          </div>
        </GlassCard>
      )}

      {/* Folder Watch */}
      {hasElectronApi && (
        <GlassCard title="Folder Watch">
          <div className="space-y-4">
            {/* 4.4 — drag-to-watch: drop a folder onto the path row */}
            <div
              className={`flex items-center gap-3 rounded-lg border border-dashed transition-colors ${
                isDragOverWatch ? 'border-accent-cyan/50 bg-accent-cyan/5' : 'border-transparent'
              }`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOverWatch(true);
              }}
              onDragLeave={() => setIsDragOverWatch(false)}
              onDrop={handleWatchFolderDrop}
            >
              <input
                type="text"
                value={sessionWatchPath}
                readOnly
                className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300 outline-none"
                placeholder={isDragOverWatch ? 'Drop folder here…' : 'Select folder to watch…'}
              />
              <button
                onClick={handleSelectWatchFolder}
                className="hover:bg-accent-cyan/10 hover:text-accent-cyan flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-400 transition-colors"
              >
                <FolderOpen size={14} />
                Browse
              </button>
            </div>

            {/* 4.1 — folder inaccessible indicator */}
            {sessionWatchActive && !sessionWatchAccessible && (
              <div className="flex items-center gap-2 text-xs text-amber-400">
                <AlertCircle size={12} />
                Folder is inaccessible — check that the drive is connected
              </div>
            )}

            {/* 4.2 — server offline indicator */}
            {sessionWatchActive && !watcherServerConnected && (
              <div className="flex items-center gap-2 text-xs text-amber-400">
                <WifiOff size={12} />
                Server is offline — file discovery paused
              </div>
            )}

            {watchConflict && (
              <p className="text-xs text-red-400">
                This folder is already used by the Notebook watcher. Choose a different folder.
              </p>
            )}

            <AppleSwitch
              checked={sessionWatchActive}
              onChange={setSessionWatchActive}
              label="Auto-Watch"
              description={
                !sessionWatchPath
                  ? 'Select a folder to enable watching'
                  : watchConflict
                    ? 'Resolve the folder conflict above to enable'
                    : sessionWatchActive && !sessionWatchAccessible
                      ? 'Folder unreachable — waiting for drive to reconnect'
                      : sessionWatchActive && !watcherServerConnected
                        ? 'Watching paused — server offline'
                        : sessionWatchActive
                          ? 'Watching for new audio files'
                          : 'Watch is paused'
              }
              disabled={!sessionWatchPath || Boolean(watchConflict)}
            />

            {/* 4.3 — activity log (collapsible) */}
            {watchLog.length > 0 && (
              <div>
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => setLogExpanded((v) => !v)}
                    className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-400"
                  >
                    <ChevronDown
                      size={12}
                      className={`transition-transform ${logExpanded ? 'rotate-180' : ''}`}
                    />
                    Activity log ({watchLog.length})
                  </button>
                  {logExpanded && (
                    <button
                      onClick={clearWatchLog}
                      className="text-xs text-slate-600 transition-colors hover:text-slate-500"
                    >
                      Clear
                    </button>
                  )}
                </div>
                {logExpanded && (
                  <div className="mt-2 max-h-32 space-y-1 overflow-y-auto">
                    {[...watchLog].reverse().map((entry, i) => (
                      <div
                        key={i}
                        className={`text-xs ${entry.level === 'warn' ? 'text-amber-400' : 'text-slate-500'}`}
                      >
                        <span className="text-slate-600">
                          {new Date(entry.ts).toLocaleTimeString()}
                        </span>{' '}
                        {entry.message}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </GlassCard>
      )}

      {/* Queue List */}
      {jobs.length > 0 && (
        <GlassCard
          title={`Import Queue${isProcessing ? ' — Processing' : ''}`}
          action={
            <div className="flex items-center gap-3 text-xs text-slate-400">
              {completedCount > 0 && <span className="text-green-400">{completedCount} done</span>}
              {pendingCount > 0 && (
                <span>
                  {pendingCount} pending
                  {/* 4.5 — time estimate */}
                  {avgProcessingMs > 0 && (
                    <span className="ml-1 text-slate-500">
                      (~{formatTimeEst(pendingCount * avgProcessingMs)})
                    </span>
                  )}
                </span>
              )}
              {errorCount > 0 && <span className="text-red-400">{errorCount} failed</span>}
              <button
                onClick={isPaused ? resumeQueue : pauseQueue}
                className="ml-1 text-slate-500 transition-colors hover:text-white"
                title={isPaused ? 'Resume queue' : 'Pause queue'}
              >
                {isPaused ? <Play size={18} /> : <Pause size={18} />}
              </button>
              {(completedCount > 0 || errorCount > 0) && (
                <button
                  onClick={clearFinished}
                  className="ml-1 text-slate-500 transition-colors hover:text-white"
                  title="Clear finished"
                >
                  <Trash2 size={18} />
                </button>
              )}
            </div>
          }
        >
          <div className="max-h-60 space-y-2 overflow-y-auto">
            {jobs.map((job) => (
              <div
                key={job.id}
                className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2 transition-colors hover:bg-white/8"
              >
                {statusIcon(job)}
                {(job.type === 'session-auto' || job.type === 'notebook-auto') && (
                  <span title="Auto-watch">
                    <Eye size={14} className="shrink-0 text-slate-500" />
                  </span>
                )}
                <span className="flex-1 truncate text-sm text-white">
                  {typeof job.file === 'string' ? job.file.split('/').pop() : job.file.name}
                </span>
                <span
                  className={`text-xs whitespace-nowrap ${
                    job.status === 'success' && job.outputPath
                      ? 'cursor-pointer text-green-400 hover:text-green-300'
                      : 'text-slate-400'
                  }`}
                  onClick={
                    job.status === 'success' && job.outputPath
                      ? () => handleOpenOutputPath(job.outputPath!)
                      : undefined
                  }
                  title={job.status === 'success' && job.outputPath ? 'Open folder' : undefined}
                >
                  {statusLabel(job)}
                </span>
                {job.status === 'error' && (
                  <button
                    onClick={() => retryJob(job.id)}
                    className="hover:text-accent-cyan p-1 text-slate-400 transition-colors"
                    title="Retry"
                  >
                    <RotateCcw size={18} />
                  </button>
                )}
                {job.status !== 'processing' && job.status !== 'writing' && (
                  <button
                    onClick={() => removeJob(job.id)}
                    className="p-1 text-slate-500 transition-colors hover:text-red-400"
                    title="Remove"
                  >
                    <XCircle size={18} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Info Note */}
      <div className="flex items-start gap-2 rounded-lg bg-white/5 px-3 py-2.5">
        <Info size={14} className="mt-0.5 shrink-0 text-slate-500" />
        <p className="text-xs leading-relaxed text-slate-500">
          {hideTimestamps
            ? 'Transcriptions are saved as .txt (plain text) to the output folder. Timestamp output is disabled in Settings.'
            : 'Transcriptions are saved as .txt (plain text) or .srt/.ass (subtitles with speaker labels when diarization is enabled) to the output folder.'}
        </p>
      </div>

      {/* Import Options */}
      <GlassCard title="Import Options">
        <div className="space-y-4">
          <AppleSwitch
            checked={diarization}
            onChange={handleDiarizationChange}
            label="Speaker Diarization"
            description={
              hideTimestamps
                ? 'Identify distinct speakers — output saved as .txt (timestamps disabled in Settings)'
                : 'Identify distinct speakers — output saved as a subtitle file with speaker labels'
            }
          />
          {diarization && (
            <>
              <div className="h-px bg-white/5"></div>
              <div className="flex items-center justify-between gap-4 pl-1">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white">Output Format</p>
                  <p className="text-xs text-slate-400">Subtitle format for diarized output</p>
                </div>
                <select
                  value={diarizedFormat}
                  onChange={(e) => setDiarizedFormat(e.target.value as 'srt' | 'ass')}
                  className="focus:border-accent-cyan/50 shrink-0 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-sm text-white scheme-dark outline-none"
                >
                  <option value="srt">.srt</option>
                  <option value="ass">.ass</option>
                </select>
              </div>
              <div className="h-px bg-white/5"></div>
              <div className="pl-1">
                <AppleSwitch
                  checked={parallelDiarization}
                  onChange={setParallelDiarization}
                  label="Parallel Processing"
                  description={
                    parallelDiarization === parallelDefault ? 'Using server default' : 'Override'
                  }
                />
              </div>
            </>
          )}
          <div className="h-px bg-white/5"></div>
          <AppleSwitch
            checked={multitrack}
            onChange={(enabled) => {
              setMultitrack(enabled);
              if (enabled) setDiarization(false);
            }}
            label="Multitrack Mode"
            description="Separate channels into individual speaker tracks — ideal for podcast, film, or panel recordings with isolated mics"
          />
          <div className="h-px bg-white/5"></div>
          <AppleSwitch
            checked={wordTimestamps}
            onChange={handleTimestampsChange}
            label="Word-level Timestamps"
            description={
              supportsExplicitWordTimestampToggle
                ? 'Generate precise timestamps for every word'
                : 'Required by the current model and managed automatically'
            }
            disabled={!supportsExplicitWordTimestampToggle}
          />
        </div>
      </GlassCard>
    </div>
  );
};
