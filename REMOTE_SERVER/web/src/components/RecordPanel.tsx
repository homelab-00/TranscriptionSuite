import { useState, useCallback, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { TranscriptionResult, HistoryEntry } from '../types';
import { TranscriptionDisplay } from './TranscriptionDisplay';
import { SessionHistory } from './SessionHistory';

export function RecordPanel() {
  const [realtimeText, setRealtimeText] = useState('');
  const [currentResult, setCurrentResult] = useState<TranscriptionResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [language, setLanguage] = useState<string>('');

  const handleFinalResult = useCallback((result: TranscriptionResult) => {
    setCurrentResult(result);
    setRealtimeText('');
    
    // Add to history
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
  } = useAudioRecorder({
    onDataAvailable: async (blob) => {
      // Convert blob to ArrayBuffer and send
      const buffer = await blob.arrayBuffer();
      sendAudioData(buffer);
    },
  });

  // Connect WebSocket when component mounts (empty deps = run once)
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

    // Start WebSocket recording session
    const started = wsStartRecording(language || undefined);
    if (started) {
      // Start local audio capture
      await startRecording();
      setCurrentResult(null);
    }
  }, [isReady, connect, wsStartRecording, language, startRecording]);

  const handleStopRecording = useCallback(() => {
    // Stop local audio capture
    stopRecording();
    // Tell server to process
    wsStopRecording();
  }, [stopRecording, wsStopRecording]);

  const error = wsError || recorderError;
  const showRecording = isRecording || wsRecording;

  return (
    <div className="flex gap-6 h-full">
      {/* Main recording area */}
      <div className="flex-1 flex flex-col">
        {/* Connection status */}
        <div className="mb-4 flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            isConnected ? 'bg-green-500' : 'bg-red-500'
          }`} />
          <span className="text-sm text-slate-400">
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
              className="ml-2 text-sm text-primary-400 hover:text-primary-300"
            >
              Reconnect
            </button>
          )}
        </div>

        {/* Language selector */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Language (optional)
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={showRecording}
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

        {/* Record button */}
        <div className="flex-1 flex flex-col items-center justify-center">
          <button
            onClick={showRecording ? handleStopRecording : handleStartRecording}
            disabled={!isConnected || isTranscribing}
            className={`w-32 h-32 rounded-full flex items-center justify-center transition-all
              ${showRecording 
                ? 'bg-red-600 hover:bg-red-700 recording-pulse' 
                : 'bg-primary-600 hover:bg-primary-700'}
              ${(!isConnected || isTranscribing) && 'opacity-50 cursor-not-allowed'}
            `}
          >
            {showRecording ? (
              <svg className="w-12 h-12 text-white" fill="currentColor" viewBox="0 0 24 24">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            ) : (
              <svg className="w-12 h-12 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                  d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            )}
          </button>

          <div className="mt-4 text-center">
            {showRecording ? (
              <div className="text-2xl font-mono text-red-400">{formattedDuration}</div>
            ) : isTranscribing ? (
              <div className="flex items-center gap-2 text-primary-400">
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Transcribing...
              </div>
            ) : (
              <div className="text-slate-400">
                {isReady ? 'Click to start recording' : 'Connecting...'}
              </div>
            )}
          </div>
        </div>

        {/* Error display */}
        {error && (
          <div className="mt-4 p-3 bg-red-900/50 border border-red-700 rounded-lg">
            <p className="text-red-300 text-sm">{error}</p>
          </div>
        )}

        {/* Realtime preview */}
        {realtimeText && (
          <div className="mt-4 p-4 bg-slate-700/50 rounded-lg border border-slate-600">
            <div className="text-sm text-slate-400 mb-1">Live preview:</div>
            <div className="text-slate-200 italic">{realtimeText}</div>
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
