import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  ChevronLeft,
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Calendar as CalendarIcon,
  Loader2,
  Bot,
  Sparkles,
  X,
  RefreshCw,
  MessageSquare,
} from 'lucide-react';
import { Howl } from 'howler';
import dayjs from 'dayjs';
import { api } from '../services/api';
import { Recording, Transcription, Word, LLMStatus } from '../types';
import ChatPanel from '../components/ChatPanel';

export default function RecordingView() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [recording, setRecording] = useState<Recording | null>(null);
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const soundRef = useRef<Howl | null>(null);
  const animationRef = useRef<number | null>(null);

  // LLM state
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmSummary, setLlmSummary] = useState('');
  const [llmError, setLlmError] = useState<string | null>(null);
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const summaryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const summaryDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamingSummaryRef = useRef<string>('');

  // Chat panel state
  const [isChatPanelOpen, setIsChatPanelOpen] = useState(false);

  useEffect(() => {
    if (id) {
      loadRecording(parseInt(id));
    }
    // Check LLM status on mount
    checkLLMStatus();
    
    return () => {
      // Cleanup
      if (soundRef.current) {
        soundRef.current.unload();
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      // Abort any ongoing LLM request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (summaryDebounceRef.current) {
        clearTimeout(summaryDebounceRef.current);
      }
    };
  }, [id]);

  useEffect(() => {
    // Handle initial time from URL parameter
    const startTime = searchParams.get('t');
    if (startTime && soundRef.current) {
      const time = parseFloat(startTime);
      soundRef.current.seek(time);
      setCurrentTime(time);
    }
  }, [searchParams, duration]);

  const loadRecording = async (recordingId: number) => {
    setLoading(true);
    try {
      const [rec, trans] = await Promise.all([
        api.getRecording(recordingId),
        api.getTranscription(recordingId),
      ]);
      setRecording(rec);
      setTranscription(trans);
      // Load existing summary if available
      setLlmSummary(rec.summary || '');
      setLlmError(null);

      // Load audio
      const audioUrl = api.getAudioUrl(recordingId);
      soundRef.current = new Howl({
        src: [audioUrl],
        html5: true,
        onload: () => {
          setDuration(soundRef.current?.duration() || 0);
          // Seek to initial time if provided
          const startTime = searchParams.get('t');
          if (startTime) {
            const time = parseFloat(startTime);
            soundRef.current?.seek(time);
            setCurrentTime(time);
          }
        },
        onend: () => {
          setPlaying(false);
        },
      });
    } catch (error) {
      console.error('Failed to load recording:', error);
    } finally {
      setLoading(false);
    }
  };

  const updateTime = () => {
    if (soundRef.current && playing) {
      setCurrentTime(soundRef.current.seek() as number);
      animationRef.current = requestAnimationFrame(updateTime);
    }
  };

  const togglePlayPause = () => {
    if (!soundRef.current) return;

    if (playing) {
      soundRef.current.pause();
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    } else {
      soundRef.current.play();
      animationRef.current = requestAnimationFrame(updateTime);
    }
    setPlaying(!playing);
  };

  const seekTo = (time: number) => {
    if (soundRef.current) {
      soundRef.current.seek(time);
      setCurrentTime(time);
    }
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    seekTo(parseFloat(e.target.value));
  };

  const handleWordClick = (word: Word) => {
    seekTo(word.start);
    if (!playing) {
      togglePlayPause();
    }
  };

  const formatTime = (seconds: number): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const isWordActive = (word: Word): boolean => {
    return currentTime >= word.start && currentTime < word.end;
  };

  // LLM Functions
  const checkLLMStatus = async () => {
    try {
      const status = await api.getLLMStatus();
      setLlmStatus(status);
    } catch {
      setLlmStatus({ available: false, base_url: '', model: null, error: 'Failed to check status' });
    }
  };

  // Save summary to database
  const saveSummary = async (summary: string) => {
    if (!recording) return;
    try {
      await api.updateSummary(recording.id, summary || null);
      // Update local recording state
      setRecording(prev => prev ? { ...prev, summary } : null);
    } catch (error) {
      console.error('Failed to save summary:', error);
    }
  };

  const handleSummarize = async () => {
    if (!transcription || !recording) return;

    // Abort any previous request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    setLlmLoading(true);
    setLlmError(null);
    setLlmSummary('');
    setIsEditingSummary(false);
    streamingSummaryRef.current = '';

    // First check LLM status if we haven't already
    if (!llmStatus) {
      try {
        const status = await api.getLLMStatus();
        setLlmStatus(status);
        if (!status.available) {
          setLlmError(status.error || 'LM Studio is not available. Please start LM Studio and load a model.');
          setLlmLoading(false);
          return;
        }
      } catch {
        setLlmError('Cannot connect to backend. Please restart the application.');
        setLlmLoading(false);
        return;
      }
    } else if (!llmStatus.available) {
      setLlmError(llmStatus.error || 'LM Studio is not available. Please start LM Studio and load a model.');
      setLlmLoading(false);
      return;
    }

    // Build full text from segments
    const fullText = transcription.segments
      .map((seg) =>
        seg.speaker
          ? `[${seg.speaker}]: ${seg.text}`
          : seg.text
      )
      .join('\n');

    const recordingId = recording.id;

    try {
      abortControllerRef.current = await api.processWithLLMStream(
        { transcription_text: fullText },
        (content) => {
          streamingSummaryRef.current += content;
          setLlmSummary((prev) => prev + content);
        },
        async () => {
          setLlmLoading(false);
          // Save the complete summary to database
          if (streamingSummaryRef.current) {
            try {
              await api.updateSummary(recordingId, streamingSummaryRef.current);
              setRecording(prev => prev ? { ...prev, summary: streamingSummaryRef.current } : null);
            } catch (error) {
              console.error('Failed to auto-save summary:', error);
            }
          }
        },
        (error) => {
          setLlmError(error);
          setLlmLoading(false);
        }
      );
    } catch (err) {
      setLlmError((err as Error).message || 'Failed to process with LLM');
      setLlmLoading(false);
    }
  };

  const handleSummaryChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setLlmSummary(newValue);
    
    // Auto-resize textarea
    if (summaryTextareaRef.current) {
      summaryTextareaRef.current.style.height = 'auto';
      summaryTextareaRef.current.style.height = summaryTextareaRef.current.scrollHeight + 'px';
    }

    // Debounced auto-save
    if (summaryDebounceRef.current) {
      clearTimeout(summaryDebounceRef.current);
    }
    summaryDebounceRef.current = setTimeout(() => {
      saveSummary(newValue);
    }, 1000);
  };

  const handleSummaryBlur = () => {
    setIsEditingSummary(false);
    // Save immediately on blur
    if (summaryDebounceRef.current) {
      clearTimeout(summaryDebounceRef.current);
    }
    saveSummary(llmSummary);
  };

  const handleClearSummary = async () => {
    setLlmSummary('');
    setLlmError(null);
    await saveSummary('');
  };

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setLlmLoading(false);
  };

  if (loading) {
    return (
      <div className="flex justify-center mt-12">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  if (!recording || !transcription) {
    return (
      <p className="text-red-400">Failed to load recording</p>
    );
  }

  return (
    <div>
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="btn-ghost mb-4"
      >
        <ChevronLeft size={20} />
        Back
      </button>

      {/* Recording info */}
      <div className="card p-4 mb-4">
        <h1 className="text-xl font-semibold text-white mb-3">{recording.filename}</h1>
        <div className="flex flex-wrap gap-4 text-sm text-gray-400">
          <span className="flex items-center gap-1.5">
            <CalendarIcon size={16} />
            {dayjs(recording.recorded_at).format('MMMM D, YYYY')}
          </span>
          <span>Duration: {formatTime(recording.duration_seconds)}</span>
          <span>{recording.word_count} words</span>
          {recording.has_diarization && (
            <span className="chip-primary">Speaker Diarization</span>
          )}
        </div>
      </div>

      {/* Audio player */}
      <div className="card p-4 mb-4">
        <div className="flex items-center gap-2">
          <button 
            onClick={() => seekTo(Math.max(0, currentTime - 10))}
            className="btn-icon"
          >
            <RotateCcw size={20} />
          </button>
          <button 
            onClick={togglePlayPause} 
            className="btn-icon p-3"
          >
            {playing ? <Pause size={28} /> : <Play size={28} />}
          </button>
          <button 
            onClick={() => seekTo(Math.min(duration, currentTime + 10))}
            className="btn-icon"
          >
            <RotateCw size={20} />
          </button>
          <span className="text-sm text-gray-400 min-w-[60px]">
            {formatTime(currentTime)}
          </span>
          <input
            type="range"
            min={0}
            max={duration}
            value={currentTime}
            onChange={handleSliderChange}
            className="flex-1 h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-primary mx-2"
          />
          <span className="text-sm text-gray-400 min-w-[60px] text-right">
            {formatTime(duration)}
          </span>
        </div>
      </div>

      {/* AI Summary Panel - Shows above transcript when there's content */}
      {(llmSummary || llmLoading || llmError) && (
        <div className="card p-4 mb-4 border border-purple-500/30 bg-purple-950/20">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Sparkles size={18} className="text-purple-400" />
              <h2 className="text-lg font-medium text-white">AI Summary</h2>
              {llmStatus?.model && (
                <span className="text-xs text-gray-500 ml-2">
                  {llmStatus.model}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {llmLoading ? (
                <button
                  onClick={handleStopGeneration}
                  className="btn-ghost text-red-400 hover:text-red-300 text-sm"
                >
                  <X size={16} className="mr-1" />
                  Stop
                </button>
              ) : (
                <>
                  <button
                    onClick={handleSummarize}
                    className="btn-ghost text-purple-400 hover:text-purple-300 text-sm"
                    title="Regenerate summary"
                  >
                    <RefreshCw size={16} />
                  </button>
                  <button
                    onClick={handleClearSummary}
                    className="btn-ghost text-gray-400 hover:text-gray-300 text-sm"
                    title="Clear summary"
                  >
                    <X size={16} />
                  </button>
                </>
              )}
            </div>
          </div>

          {llmError && (
            <div className="text-red-400 text-sm mb-3 p-2 bg-red-950/30 rounded">
              {llmError}
            </div>
          )}

          {(llmSummary || llmLoading) && (
            <div className="relative">
              {isEditingSummary ? (
                <textarea
                  ref={summaryTextareaRef}
                  value={llmSummary}
                  onChange={handleSummaryChange}
                  onBlur={handleSummaryBlur}
                  className="w-full bg-transparent text-gray-200 resize-none outline-none border border-purple-500/50 rounded p-2 min-h-[100px]"
                  autoFocus
                />
              ) : (
                <div
                  onClick={() => !llmLoading && setIsEditingSummary(true)}
                  className={`text-gray-200 whitespace-pre-wrap cursor-text hover:bg-purple-950/30 rounded p-2 -m-2 transition-colors ${
                    llmLoading ? 'cursor-wait' : ''
                  }`}
                >
                  {llmSummary}
                  {llmLoading && (
                    <span className="inline-block w-2 h-4 bg-purple-400 ml-0.5 animate-pulse" />
                  )}
                </div>
              )}
              {!llmLoading && !isEditingSummary && (
                <p className="text-xs text-gray-500 mt-2">
                  Click to edit
                </p>
              )}
            </div>
          )}

          {llmLoading && !llmSummary && (
            <div className="flex items-center gap-2 text-gray-400">
              <Loader2 size={16} className="animate-spin" />
              <span>Generating summary...</span>
            </div>
          )}
        </div>
      )}

      {/* Transcript with clickable words */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Transcript</h2>
          
          <div className="flex items-center gap-2">
            {/* Legacy Summarize Button - shows when there's no summary and chat panel is closed */}
            {!llmSummary && !llmLoading && !isChatPanelOpen && (
              <button
                onClick={handleSummarize}
                className="btn-ghost text-purple-400 hover:text-purple-300 flex items-center gap-2"
                disabled={llmLoading}
              >
                <Bot size={18} />
                <span>Quick Summary</span>
              </button>
            )}
            
            {/* Chat with AI Button */}
            <button
              onClick={() => setIsChatPanelOpen(true)}
              className="btn-ghost text-purple-400 hover:text-purple-300 flex items-center gap-2"
            >
              <MessageSquare size={18} />
              <span>Chat with AI</span>
            </button>
          </div>
        </div>
        {transcription.segments.map((segment, segIndex) => (
          <div key={segIndex} className="mb-4">
            {segment.speaker && (
              <span className="chip-primary mb-2 inline-block">
                {segment.speaker}
              </span>
            )}
            <div className="leading-8">
              {segment.words ? (
                segment.words.map((word, wordIndex) => (
                  <span
                    key={`${segIndex}-${wordIndex}`}
                    onClick={() => handleWordClick(word)}
                    className={`
                      cursor-pointer px-0.5 rounded transition-colors
                      ${isWordActive(word)
                        ? 'bg-primary text-gray-900'
                        : 'text-white hover:bg-surface-light'
                      }
                    `}
                  >
                    {word.word}{' '}
                  </span>
                ))
              ) : (
                <p className="text-white">{segment.text}</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Chat Panel */}
      {recording && (
        <ChatPanel
          recordingId={recording.id}
          isOpen={isChatPanelOpen}
          onClose={() => setIsChatPanelOpen(false)}
        />
      )}
    </div>
  );
}
