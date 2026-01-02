import { useState, useCallback, useEffect, useRef } from 'react';
import { Mic, Square, Loader2, Upload, FileAudio } from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useRawAudioRecorder } from '../hooks/useRawAudioRecorder';
import { TranscriptionResult, HistoryEntry } from '../types';

// API base URL
const API_BASE_URL = import.meta.env.DEV 
  ? 'http://localhost:8000/api' 
  : `${window.location.origin}/api`;

export default function RecordView() {
  const [realtimeText, setRealtimeText] = useState('');
  const [currentResult, setCurrentResult] = useState<TranscriptionResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [language, setLanguage] = useState<string>('');
  
  // File upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploadTranscribing, setIsUploadTranscribing] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFinalResult = useCallback((result: TranscriptionResult) => {
    setCurrentResult(result);
    setRealtimeText('');
    
    setHistory(prev => [{
      id: crypto.randomUUID(),
      text: result.text,
      duration: result.duration,
      timestamp: new Date(),
      type: 'recording',
    }, ...prev]);
  }, []);

  const handleError = useCallback((error: string) => {
    console.error('WebSocket error:', error);
  }, []);

  const {
    status,
    error: wsError,
    isConnected,
    isReady,
    isRecording: wsRecording,
    isTranscribing,
    connect,
    disconnect,
    startRecording: wsStartRecording,
    stopRecording: wsStopRecording,
    sendAudioData,
  } = useWebSocket({
    onRealtimeText: setRealtimeText,
    onFinalResult: handleFinalResult,
    onError: handleError,
  });

  const {
    isRecording,
    formattedDuration,
    error: recorderError,
    startRecording,
    stopRecording,
  } = useRawAudioRecorder({
    onAudioData: (buffer) => {
      sendAudioData(buffer);
    },
  });

  useEffect(() => {
    connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStartRecording = useCallback(async () => {
    if (!isReady) {
      connect();
      return;
    }

    const started = wsStartRecording(language || undefined);
    if (started) {
      await startRecording();
      setCurrentResult(null);
    }
  }, [isReady, connect, wsStartRecording, language, startRecording]);

  const handleStopRecording = useCallback(() => {
    stopRecording();
    wsStopRecording();
  }, [stopRecording, wsStopRecording]);

  // File upload handlers
  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setUploadError(null);
    }
  }, []);

  const handleFileTranscribe = useCallback(async () => {
    if (!selectedFile) return;
    
    setIsUploadTranscribing(true);
    setUploadError(null);
    
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      if (language) {
        formData.append('language', language);
      }
      
      const response = await fetch(`${API_BASE_URL}/transcribe/quick`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Transcription failed: ${response.status}`);
      }
      
      const data = await response.json();
      
      // Create result from response
      const result: TranscriptionResult = {
        text: data.text || '',
        duration: data.duration || 0,
        language: data.language,
        is_final: true,
      };
      
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
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Transcription failed');
    } finally {
      setIsUploadTranscribing(false);
    }
  }, [selectedFile, language]);

  const error = wsError || recorderError || uploadError;
  const showRecording = isRecording || wsRecording;

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString(undefined, { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  const formatDurationDisplay = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Main recording area */}
      <div className="flex-1 flex flex-col">
        <h1 className="text-2xl font-semibold text-white mb-6">Record</h1>

        {/* Connection status */}
        <div className="mb-4 flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            isConnected ? 'bg-success' : 'bg-error'
          }`} />
          <span className="text-sm text-gray-400">
            {status === 'connecting' && 'Connecting...'}
            {status === 'authenticating' && 'Authenticating...'}
            {status === 'ready' && 'Connected'}
            {status === 'recording' && 'Recording...'}
            {status === 'transcribing' && 'Transcribing...'}
            {status === 'disconnected' && 'Disconnected'}
            {status === 'busy' && 'Server busy'}
            {status === 'error' && 'Error'}
          </span>
          {!isConnected && (
            <button
              onClick={connect}
              className="ml-2 text-sm text-primary hover:text-primary-dark"
            >
              Reconnect
            </button>
          )}
        </div>

        {/* Language selector */}
        <div className="mb-6">
          <label className="label">Language (optional)</label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={showRecording}
            className="input w-48"
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

        {/* Main content area with two columns */}
        <div className="flex-1 flex gap-8">
          {/* Long Form Recording Section */}
          <div className="flex-1 flex flex-col items-center justify-center border-r border-gray-800 pr-8">
            <h2 className="text-lg font-medium text-gray-400 mb-6">Long Form Recording</h2>
            <button
              onClick={showRecording ? handleStopRecording : handleStartRecording}
              disabled={!isConnected || isTranscribing || isUploadTranscribing}
              className={`w-28 h-28 rounded-full flex items-center justify-center transition-all
                ${showRecording 
                  ? 'bg-error hover:bg-red-700' 
                  : 'bg-primary hover:bg-primary-dark'}
                ${(!isConnected || isTranscribing || isUploadTranscribing) && 'opacity-50 cursor-not-allowed'}
              `}
            >
              {showRecording ? (
                <Square size={40} className="text-white" />
              ) : (
                <Mic size={40} className="text-gray-900" />
              )}
            </button>

            <div className="mt-4 text-center">
              {showRecording ? (
                <div className="text-2xl font-mono text-error">{formattedDuration}</div>
              ) : isTranscribing ? (
                <div className="flex items-center gap-2 text-primary">
                  <Loader2 className="animate-spin" size={20} />
                  Transcribing...
                </div>
              ) : (
                <div className="text-gray-400 text-sm">
                  {isReady ? 'Click to start recording' : 'Connecting...'}
                </div>
              )}
            </div>
          </div>

          {/* File Upload Section */}
          <div className="flex-1 flex flex-col items-center justify-center pl-8">
            <h2 className="text-lg font-medium text-gray-400 mb-6">Transcribe File</h2>
            
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*,video/*"
              onChange={handleFileSelect}
              className="hidden"
              disabled={isUploadTranscribing || showRecording}
            />
            
            {!selectedFile ? (
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploadTranscribing || showRecording}
                className={`w-28 h-28 rounded-full flex flex-col items-center justify-center transition-all
                  bg-surface-light hover:bg-gray-700 border-2 border-dashed border-gray-600
                  ${(isUploadTranscribing || showRecording) && 'opacity-50 cursor-not-allowed'}
                `}
              >
                <Upload size={32} className="text-gray-400" />
              </button>
            ) : (
              <button
                onClick={handleFileTranscribe}
                disabled={isUploadTranscribing}
                className={`w-28 h-28 rounded-full flex flex-col items-center justify-center transition-all
                  bg-primary hover:bg-primary-dark
                  ${isUploadTranscribing && 'opacity-50 cursor-not-allowed'}
                `}
              >
                {isUploadTranscribing ? (
                  <Loader2 size={32} className="text-gray-900 animate-spin" />
                ) : (
                  <FileAudio size={32} className="text-gray-900" />
                )}
              </button>
            )}

            <div className="mt-4 text-center">
              {isUploadTranscribing ? (
                <div className="flex items-center gap-2 text-primary">
                  <Loader2 className="animate-spin" size={16} />
                  Transcribing...
                </div>
              ) : selectedFile ? (
                <div className="space-y-2">
                  <div className="text-sm text-gray-300 truncate max-w-[200px]">
                    {selectedFile.name}
                  </div>
                  <div className="text-xs text-gray-500">
                    Click to transcribe or{' '}
                    <button
                      onClick={() => {
                        setSelectedFile(null);
                        if (fileInputRef.current) fileInputRef.current.value = '';
                      }}
                      className="text-primary hover:underline"
                    >
                      choose another
                    </button>
                  </div>
                </div>
              ) : (
                <div className="text-gray-400 text-sm">
                  Click to select a file
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Error display */}
        {error && (
          <div className="mt-4 p-3 bg-error/20 border border-error rounded-lg">
            <p className="text-error text-sm">{error}</p>
          </div>
        )}

        {/* Realtime preview */}
        {realtimeText && (
          <div className="mt-4 p-4 card">
            <div className="text-sm text-gray-400 mb-1">Live preview:</div>
            <div className="text-gray-200 italic">{realtimeText}</div>
          </div>
        )}

        {/* Transcription result */}
        {currentResult && (
          <div className="mt-4 card p-4">
            <h3 className="text-sm font-medium text-gray-400 mb-2">Result</h3>
            <p className="text-white whitespace-pre-wrap">{currentResult.text}</p>
            <div className="mt-2 flex gap-4 text-sm text-gray-500">
              <span>Duration: {formatDurationDisplay(currentResult.duration)}</span>
              {currentResult.language && (
                <span>Language: {currentResult.language}</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* History sidebar */}
      <div className="w-80 border-l border-gray-800 pl-6">
        <h2 className="text-lg font-medium text-white mb-4">Session History</h2>
        
        {history.length === 0 ? (
          <p className="text-gray-500 text-sm">No recordings yet</p>
        ) : (
          <div className="space-y-3 overflow-y-auto max-h-[calc(100vh-200px)]">
            {history.map((entry) => (
              <button
                key={entry.id}
                onClick={() => {
                  setCurrentResult({
                    text: entry.text,
                    duration: entry.duration,
                    is_final: true,
                  });
                }}
                className="w-full text-left card-hover p-3"
              >
                <div className="flex justify-between items-start mb-1">
                  <span className="text-xs text-gray-500">
                    {formatTime(entry.timestamp)}
                  </span>
                  <span className="text-xs text-gray-500">
                    {formatDurationDisplay(entry.duration)}
                  </span>
                </div>
                <p className="text-sm text-gray-300 line-clamp-2">
                  {entry.text}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
