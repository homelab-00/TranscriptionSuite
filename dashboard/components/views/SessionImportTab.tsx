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
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { useSessionImportQueue } from '../../src/hooks/useSessionImportQueue';
import type {
  SessionImportJob,
  UseSessionImportQueueReturn,
} from '../../src/hooks/useSessionImportQueue';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useLanguages } from '../../src/hooks/useLanguages';
import { apiClient } from '../../src/api/client';
import type { AdminStatus } from '../../src/api/types';
import { supportsExplicitWordTimestampToggle as supportsExplicitWordTimestampToggleForModel } from '../../src/utils/transcriptionBackend';
import { getConfig, setConfig } from '../../src/config/store';

export const SessionImportTab: React.FC = () => {
  const [outputDir, setOutputDir] = useState('');
  const [diarization, setDiarization] = useState(true);
  const [wordTimestamps, setWordTimestamps] = useState(true);
  const [parallelDiarization, setParallelDiarization] = useState<boolean>(false);
  const [parallelDefault, setParallelDefault] = useState<boolean>(false);
  const [isDragOver, setIsDragOver] = useState(false);
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

  const queue = useSessionImportQueue({ outputDir });

  // Fetch downloads path on mount
  useEffect(() => {
    const init = async () => {
      const electronAPI = (window as any).electronAPI;

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

  useEffect(() => {
    if (!supportsExplicitWordTimestampToggle) {
      setWordTimestamps(true);
    }
  }, [supportsExplicitWordTimestampToggle]);

  const handleDiarizationChange = useCallback((enabled: boolean) => {
    setDiarization(enabled);
    if (enabled) setWordTimestamps(true);
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
      queue.addFiles(Array.from(files), {
        enable_diarization: diarization,
        enable_word_timestamps: supportsExplicitWordTimestampToggle ? wordTimestamps : true,
        parallel_diarization: diarization ? parallelDiarization : undefined,
      });
    },
    [diarization, parallelDiarization, queue, supportsExplicitWordTimestampToggle, wordTimestamps],
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

  const handleOpenOutputPath = useCallback((filePath: string) => {
    const electronAPI = (window as any).electronAPI;
    if (electronAPI?.app?.openPath) {
      // Open the containing directory
      const dir = filePath.substring(0, filePath.lastIndexOf('/'));
      electronAPI.app.openPath(dir);
    }
  }, []);

  const statusIcon = (job: SessionImportJob) => {
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

  const statusLabel = (job: SessionImportJob) => {
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

      {/* Queue List */}
      {queue.jobs.length > 0 && (
        <GlassCard
          title={`Import Queue${queue.isProcessing ? ' — Processing' : ''}`}
          action={
            <div className="flex items-center gap-3 text-xs text-slate-400">
              {queue.completedCount > 0 && (
                <span className="text-green-400">{queue.completedCount} done</span>
              )}
              {queue.pendingCount > 0 && <span>{queue.pendingCount} pending</span>}
              {queue.errorCount > 0 && (
                <span className="text-red-400">{queue.errorCount} failed</span>
              )}
              {(queue.completedCount > 0 || queue.errorCount > 0) && (
                <button
                  onClick={queue.clearFinished}
                  className="ml-1 text-slate-500 transition-colors hover:text-white"
                  title="Clear finished"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          }
        >
          <div className="max-h-60 space-y-2 overflow-y-auto">
            {queue.jobs.map((job) => (
              <div
                key={job.id}
                className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2 transition-colors hover:bg-white/8"
              >
                {statusIcon(job)}
                <span className="flex-1 truncate text-sm text-white">{job.file.name}</span>
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
                    onClick={() => queue.retryJob(job.id)}
                    className="hover:text-accent-cyan p-1 text-slate-400 transition-colors"
                    title="Retry"
                  >
                    <RotateCcw size={12} />
                  </button>
                )}
                {job.status !== 'processing' && job.status !== 'writing' && (
                  <button
                    onClick={() => queue.removeJob(job.id)}
                    className="p-1 text-slate-500 transition-colors hover:text-red-400"
                    title="Remove"
                  >
                    <XCircle size={12} />
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
          Transcriptions are saved as .txt (plain text) or .srt (subtitles with speaker labels when
          diarization is enabled) to the output folder.
        </p>
      </div>

      {/* Import Options */}
      <GlassCard title="Import Options">
        <div className="space-y-4">
          <AppleSwitch
            checked={diarization}
            onChange={handleDiarizationChange}
            label="Speaker Diarization"
            description="Identify distinct speakers — output saved as .srt with speaker labels"
          />
          {diarization && (
            <>
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
