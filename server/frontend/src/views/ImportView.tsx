import { useState, useRef } from 'react';
import { Upload, FileAudio, CheckCircle, XCircle, Loader2, Play, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { ImportJob } from '../types';
import { Toggle, Alert, ProgressBar } from '../components/ui';

interface QueuedFile {
  id: number;
  file: File;
  filename: string;
}

export default function ImportView() {
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Open HTML file picker
  const openFilePicker = () => {
    fileInputRef.current?.click();
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

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      addFilesToQueue(files);
    }
  };

  const addFilesToQueue = (files: FileList) => {
    setError(null);
    const newFiles: QueuedFile[] = Array.from(files).map((file) => ({
      id: Date.now() + Math.random(),
      file,
      filename: file.name,
    }));
    setQueuedFiles(prev => [...prev, ...newFiles]);
  };

  const removeFromQueue = (id: number) => {
    setQueuedFiles(prev => prev.filter(f => f.id !== id));
  };

  const clearQueue = () => {
    setQueuedFiles([]);
  };

  const processQueue = async () => {
    if (queuedFiles.length === 0 || isProcessing) return;
    
    setIsProcessing(true);
    setError(null);

    // Process files one at a time
    for (const queuedFile of queuedFiles) {
      // Add job as 'transcribing'
      const pendingJob: ImportJob = {
        id: queuedFile.id,
        filename: queuedFile.filename,
        status: 'transcribing',
        message: 'Uploading and transcribing...',
      };
      setJobs(prev => [pendingJob, ...prev]);
      
      // Remove from queue
      setQueuedFiles(prev => prev.filter(f => f.id !== queuedFile.id));

      try {
        // Upload and transcribe
        const response = await api.uploadFile(queuedFile.file, enableDiarization, enableWordTimestamps);
        
        // Update job to completed
        setJobs(prev => prev.map(job => 
          job.id === queuedFile.id 
            ? { ...job, id: response.recording_id, status: 'completed', message: response.message }
            : job
        ));
        
      } catch (err: any) {
        // Update job to failed
        setJobs(prev => prev.map(job =>
          job.id === queuedFile.id
            ? { ...job, status: 'failed', message: err.response?.data?.detail || err.message }
            : job
        ));
        setError(`Failed to upload ${queuedFile.filename}: ${err.response?.data?.detail || err.message}`);
      }
    }

    setIsProcessing(false);
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
          onChange={(e) => {
            if (e.target.files) addFilesToQueue(e.target.files);
            e.target.value = '';  // Reset to allow re-selecting same file
          }}
        />
      </div>

      {/* File Queue */}
      {queuedFiles.length > 0 && (
        <div className="card p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium text-white">Files to Import ({queuedFiles.length})</h2>
            <button
              onClick={clearQueue}
              className="text-sm text-gray-400 hover:text-red-400 transition-colors"
              disabled={isProcessing}
            >
              Clear All
            </button>
          </div>
          
          <div className="space-y-2 mb-4 max-h-48 overflow-y-auto">
            {queuedFiles.map((qf) => (
              <div 
                key={qf.id}
                className="flex items-center gap-3 p-2 bg-surface-light rounded-lg"
              >
                <FileAudio className="text-gray-400 flex-shrink-0" size={18} />
                <span className="text-sm text-white truncate flex-1">{qf.filename}</span>
                <button
                  onClick={() => removeFromQueue(qf.id)}
                  className="p-1 text-gray-400 hover:text-red-400 transition-colors"
                  disabled={isProcessing}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
          
          <button
            onClick={processQueue}
            disabled={isProcessing}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {isProcessing ? (
              <>
                <Loader2 className="animate-spin" size={18} />
                Processing...
              </>
            ) : (
              <>
                <Play size={18} />
                Transcribe All Files
              </>
            )}
          </button>
        </div>
      )}

      {/* Options */}
      <div className="card p-4 mb-6">
        <h2 className="text-lg font-medium text-white mb-4">Transcription Options</h2>
        <div className="space-y-3">
          <Toggle
            checked={enableWordTimestamps}
            onChange={setEnableWordTimestamps}
            label="Enable word-level timestamps (clickable words in transcript)"
            disabled={isProcessing}
          />
          <Toggle
            checked={enableDiarization}
            onChange={setEnableDiarization}
            label="Enable speaker diarization (identify who spoke when)"
            disabled={isProcessing}
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
