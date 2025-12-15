import { useState, useCallback } from 'react';
import { api } from '../api/client';
import { TranscriptionResult, HistoryEntry } from '../types';
import { TranscriptionDisplay } from './TranscriptionDisplay';
import { SessionHistory } from './SessionHistory';

export function FileUploadPanel() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [language, setLanguage] = useState<string>('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentResult, setCurrentResult] = useState<TranscriptionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setError(null);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) {
      setSelectedFile(file);
      setError(null);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  }, []);

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);
    setCurrentResult(null);

    try {
      const result = await api.transcribeFile(
        selectedFile,
        language || undefined,
        setUploadProgress
      );

      setCurrentResult(result);
      
      // Add to history
      setHistory(prev => [{
        id: crypto.randomUUID(),
        text: result.text,
        duration: result.duration,
        timestamp: new Date(),
        type: 'file',
      }, ...prev]);

      // Clear file selection
      setSelectedFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  }, [selectedFile, language]);

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Main upload area */}
      <div className="flex-1 flex flex-col">
        {/* Language selector */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Language (optional)
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={isUploading}
            className="w-48 px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg 
                     text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">Auto-detect</option>
            <option value="en">English</option>
            <option value="el">Greek</option>
            <option value="es">Spanish</option>
            <option value="fr">French</option>
            <option value="de">German</option>
            <option value="it">Italian</option>
            <option value="pt">Portuguese</option>
            <option value="ru">Russian</option>
            <option value="zh">Chinese</option>
            <option value="ja">Japanese</option>
            <option value="ko">Korean</option>
          </select>
        </div>

        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className={`flex-1 border-2 border-dashed rounded-xl flex flex-col items-center 
                    justify-center p-8 transition-colors
            ${selectedFile 
              ? 'border-primary-500 bg-primary-900/20' 
              : 'border-slate-600 hover:border-slate-500 bg-slate-800/50'
            }
            ${isUploading ? 'pointer-events-none opacity-50' : ''}
          `}
        >
          {selectedFile ? (
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 bg-primary-900/50 rounded-full 
                            flex items-center justify-center">
                <svg className="w-8 h-8 text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                </svg>
              </div>
              <div className="text-white font-medium mb-1">{selectedFile.name}</div>
              <div className="text-sm text-slate-400 mb-4">
                {formatFileSize(selectedFile.size)}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={handleUpload}
                  disabled={isUploading}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white 
                           rounded-lg transition-colors"
                >
                  {isUploading ? 'Transcribing...' : 'Transcribe'}
                </button>
                <button
                  onClick={() => setSelectedFile(null)}
                  disabled={isUploading}
                  className="px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white 
                           rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 bg-slate-700 rounded-full 
                            flex items-center justify-center">
                <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <div className="text-white mb-2">Drop audio/video file here</div>
              <div className="text-sm text-slate-400 mb-4">
                or click to browse
              </div>
              <input
                type="file"
                accept="audio/*,video/*"
                onChange={handleFileSelect}
                className="hidden"
                id="file-input"
              />
              <label
                htmlFor="file-input"
                className="px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white 
                         rounded-lg transition-colors cursor-pointer inline-block"
              >
                Select File
              </label>
              <div className="mt-4 text-xs text-slate-500">
                Supports: MP3, WAV, FLAC, OGG, M4A, MP4, MKV, etc.
              </div>
            </div>
          )}
        </div>

        {/* Upload progress */}
        {isUploading && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-sm text-slate-400 mb-2">
              <span>Uploading & Transcribing...</span>
              <span>{Math.round(uploadProgress)}%</span>
            </div>
            <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
              <div 
                className="h-full bg-primary-500 transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="mt-4 p-3 bg-red-900/50 border border-red-700 rounded-lg">
            <p className="text-red-300 text-sm">{error}</p>
          </div>
        )}

        {/* Transcription result */}
        {currentResult && (
          <div className="mt-4">
            <TranscriptionDisplay result={currentResult} />
          </div>
        )}
      </div>

      {/* History sidebar */}
      <div className="w-80 border-l border-slate-700 pl-6">
        <SessionHistory 
          entries={history} 
          onSelect={(entry) => {
            setCurrentResult({
              text: entry.text,
              duration: entry.duration,
              is_final: true,
            });
          }}
        />
      </div>
    </div>
  );
}
