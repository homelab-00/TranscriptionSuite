import { useState, useRef } from 'react';
import { Upload, FileAudio, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { api } from '../services/api';
import { ImportJob } from '../types';
import { Toggle, Alert, ProgressBar } from '../components/ui';

export default function ImportView() {
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Open HTML file picker
  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const pollJobStatus = async (recordingId: number) => {
    const maxAttempts = 120; // 10 minutes at 5 second intervals
    let attempts = 0;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        updateJobStatus(recordingId, 'failed', undefined, 'Transcription timed out');
        return;
      }

      try {
        const status = await api.getTranscriptionStatus(recordingId);
        
        updateJobStatus(
          recordingId,
          status.status as ImportJob['status'],
          status.progress,
          status.message
        );

        if (status.status === 'transcribing' || status.status === 'pending') {
          attempts++;
          setTimeout(poll, 5000);
        }
      } catch (err) {
        updateJobStatus(recordingId, 'failed', undefined, 'Failed to check status');
      }
    };

    poll();
  };

  const updateJobStatus = (
    id: number,
    status: ImportJob['status'],
    progress?: number,
    message?: string
  ) => {
    setJobs(prev =>
      prev.map(job =>
        job.id === id
          ? { ...job, status, progress, message }
          : job
      )
    );
  };

  const getStatusIcon = (status: ImportJob['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="text-green-400" size={20} />;
      case 'failed':
        return <XCircle className="text-red-400" size={20} />;
      case 'transcribing':
        return <Loader2 className="text-blue-400 animate-spin" size={20} />;
      default:
        return <FileAudio className="text-gray-400" size={20} />;
    }
  };

  // Handle drag events for the drop zone
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      await handleFiles(files);
    }
  };

  const handleFiles = async (files: FileList) => {
    setError(null);

    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadFile(file, enableDiarization, enableWordTimestamps);
        
        const newJob: ImportJob = {
          id: response.recording_id,
          filename: file.name,
          status: 'transcribing',
          message: response.message,
        };
        
        setJobs(prev => [newJob, ...prev]);
        
        // Start polling for status
        pollJobStatus(newJob.id);
        
      } catch (err: any) {
        setError(`Failed to upload ${file.name}: ${err.response?.data?.detail || err.message}`);
      }
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Import Recordings</h1>

      {/* Drag and drop zone */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={openFilePicker}
        className={`
          card p-6 mb-6 border-2 border-dashed cursor-pointer transition-all duration-200
          ${dragActive 
            ? 'border-primary bg-primary/5' 
            : 'border-gray-700 hover:border-gray-600'
          }
        `}
      >
        <div className="flex flex-col items-center py-8">
          <Upload 
            size={48} 
            className={`mb-4 ${dragActive ? 'text-primary' : 'text-gray-500'}`} 
          />
          <h3 className="text-lg font-medium text-white mb-2">
            {dragActive ? 'Drop files here' : 'Drag & drop audio files here'}
          </h3>
          <p className="text-sm text-gray-400 mb-4">or click to browse</p>
          <p className="text-xs text-gray-500">
            Supported: MP3, WAV, OPUS, OGG, FLAC, M4A, WMA, AAC
          </p>
        </div>
        
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="audio/*,.mp3,.wav,.opus,.ogg,.flac,.m4a,.wma,.aac"
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </div>

      {/* Options */}
      <div className="card p-4 mb-6">
        <h2 className="text-lg font-medium text-white mb-4">Transcription Options</h2>
        <div className="space-y-3">
          <Toggle
            checked={enableWordTimestamps}
            onChange={setEnableWordTimestamps}
            label="Enable word-level timestamps (clickable words in transcript)"
          />
          <Toggle
            checked={enableDiarization}
            onChange={setEnableDiarization}
            label="Enable speaker diarization (requires separate Python 3.11 environment)"
          />
        </div>
      </div>

      {/* Error alert */}
      {error && (
        <Alert severity="error" className="mb-6" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Import jobs list */}
      {jobs.length > 0 && (
        <div className="card p-4">
          <h2 className="text-lg font-medium text-white mb-4">Import Queue</h2>
          
          <div className="space-y-3">
            {jobs.map((job) => (
              <div 
                key={job.id}
                className="flex items-start gap-3 p-3 bg-surface-light rounded-lg"
              >
                <div className="flex-shrink-0 mt-0.5">
                  {getStatusIcon(job.status)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">
                    {job.filename}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {job.message || job.status}
                  </p>
                  {job.status === 'transcribing' && job.progress !== undefined && (
                    <ProgressBar value={job.progress * 100} className="mt-2" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
