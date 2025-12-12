import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ChevronLeft,
  ChevronRight,
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Search,
  Trash2,
  CalendarDays,
  Plus,
  Loader2,
  Clock,
  Bot,
  Sparkles,
  X,
  RefreshCw,
  Power,
} from 'lucide-react';
import dayjs, { Dayjs } from 'dayjs';
import { Howl } from 'howler';
import { api } from '../services/api';
import { Recording, Transcription, Word, LLMStatus } from '../types';
import { Modal, Toggle, ContextMenu, ContextMenuItem, Alert, ProgressBar } from '../components/ui';

interface RecordingWithTranscription extends Recording {
  transcription?: Transcription;
}

interface HourSlot {
  hour: number;
  recordings: RecordingWithTranscription[];
}

export default function DayView() {
  const { date } = useParams<{ date: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [currentDate, setCurrentDate] = useState<Dayjs>(date ? dayjs(date) : dayjs());
  const [recordings, setRecordings] = useState<RecordingWithTranscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRecording, setSelectedRecording] = useState<RecordingWithTranscription | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newEntryHour, setNewEntryHour] = useState<number | null>(null);
  
  // Audio player state
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const soundRef = useRef<Howl | null>(null);
  const animationRef = useRef<number | null>(null);

  // New entry form state
  const [newEntryFilePath, setNewEntryFilePath] = useState('');
  const [newEntryFile, setNewEntryFile] = useState<File | null>(null);
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importProgress, setImportProgress] = useState<string | null>(null);
  
  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    recording: RecordingWithTranscription;
  } | null>(null);
  
  // Change date dialog state
  const [changeDateDialogOpen, setChangeDateDialogOpen] = useState(false);
  const [changeDateRecording, setChangeDateRecording] = useState<RecordingWithTranscription | null>(null);
  const [newDate, setNewDate] = useState('');
  const [newTime, setNewTime] = useState('');
  const [changeDateLoading, setChangeDateLoading] = useState(false);
  const [changeDateError, setChangeDateError] = useState<string | null>(null);
  
  // Delete confirmation dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteRecording, setDeleteRecording] = useState<RecordingWithTranscription | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  
  // LLM state
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmSummary, setLlmSummary] = useState('');
  const [llmError, setLlmError] = useState<string | null>(null);
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const summaryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const summaryDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamingSummaryRef = useRef<string>(''); // Tracks summary during streaming
  
  // HTML file input ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadRecordingsForDay();
    checkLLMStatus();
    return () => {
      if (soundRef.current) {
        soundRef.current.unload();
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (summaryDebounceRef.current) {
        clearTimeout(summaryDebounceRef.current);
      }
    };
  }, [currentDate]);

  useEffect(() => {
    if (date) {
      setCurrentDate(dayjs(date));
    }
  }, [date]);

  const loadRecordingsForDay = async () => {
    setLoading(true);
    try {
      const dateStr = currentDate.format('YYYY-MM-DD');
      const data = await api.getRecordingsByDateRange(dateStr, dateStr);
      const dayRecordings = data[dateStr] || [];
      
      // Load transcriptions for each recording
      const recordingsWithTranscriptions = await Promise.all(
        dayRecordings.map(async (rec) => {
          try {
            const transcription = await api.getTranscription(rec.id);
            return { ...rec, transcription };
          } catch {
            return rec;
          }
        })
      );
      
      setRecordings(recordingsWithTranscriptions);
      
      // Check for search params to open a specific recording
      const recordingParam = searchParams.get('recording');
      const timeParam = searchParams.get('t');
      
      if (recordingParam) {
        const recordingId = parseInt(recordingParam);
        const rec = recordingsWithTranscriptions.find(r => r.id === recordingId);
        if (rec) {
          setSelectedRecording(rec);
          setLlmSummary(rec.summary || '');
          setLlmError(null);
          loadAudioWithSeek(rec.id, timeParam ? parseFloat(timeParam) : null);
          // Clear the search params after using them
          setSearchParams({});
        }
      }
    } catch (error) {
      console.error('Failed to load recordings:', error);
    } finally {
      setLoading(false);
    }
  };

  const handlePreviousDay = () => {
    const newDate = currentDate.subtract(1, 'day');
    setCurrentDate(newDate);
    navigate(`/day/${newDate.format('YYYY-MM-DD')}`);
  };

  const handleNextDay = () => {
    const newDate = currentDate.add(1, 'day');
    if (newDate.isBefore(dayjs(), 'day') || newDate.isSame(dayjs(), 'day')) {
      setCurrentDate(newDate);
      navigate(`/day/${newDate.format('YYYY-MM-DD')}`);
    }
  };

  const getHourSlots = (): { morning: HourSlot[]; afternoon: HourSlot[] } => {
    const morning: HourSlot[] = [];
    const afternoon: HourSlot[] = [];

    for (let hour = 0; hour < 24; hour++) {
      const hourRecordings = recordings
        .filter(rec => {
          const recordedAt = dayjs(rec.recorded_at);
          return recordedAt.hour() === hour;
        })
        .sort((a, b) => dayjs(a.recorded_at).valueOf() - dayjs(b.recorded_at).valueOf());

      const slot: HourSlot = { hour, recordings: hourRecordings };
      
      if (hour < 12) {
        morning.push(slot);
      } else {
        afternoon.push(slot);
      }
    }

    return { morning, afternoon };
  };

  const formatHour = (hour: number): string => {
    if (hour === 0) return '12 AM';
    if (hour === 12) return '12 PM';
    if (hour < 12) return `${hour} AM`;
    return `${hour - 12} PM`;
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleFileInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      const file = files[0];
      setNewEntryFile(file);
      setNewEntryFilePath(file.name);
      setImportError(null);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const loadAudio = async (recordingId: number) => {
    loadAudioWithSeek(recordingId, null);
  };

  const loadAudioWithSeek = async (recordingId: number, seekTime: number | null) => {
    if (soundRef.current) {
      soundRef.current.unload();
    }
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    setPlaying(false);
    setCurrentTime(seekTime || 0);
    
    const audioUrl = api.getAudioUrl(recordingId);
    soundRef.current = new Howl({
      src: [audioUrl],
      html5: true,
      onload: () => {
        setDuration(soundRef.current?.duration() || 0);
        // Seek to the specified time after loading
        if (seekTime !== null && soundRef.current) {
          soundRef.current.seek(seekTime);
          setCurrentTime(seekTime);
        }
      },
      onplay: () => {
        const animate = () => {
          if (soundRef.current && soundRef.current.playing()) {
            const seek = soundRef.current.seek();
            if (typeof seek === 'number') {
              setCurrentTime(seek);
            }
            animationRef.current = requestAnimationFrame(animate);
          }
        };
        animate();
      },
      onpause: () => {
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current);
          animationRef.current = null;
        }
      },
      onend: () => {
        setPlaying(false);
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current);
          animationRef.current = null;
        }
      },
    });
  };

  const togglePlayPause = () => {
    if (!soundRef.current) return;

    if (playing) {
      soundRef.current.pause();
    } else {
      soundRef.current.play();
    }
    setPlaying(!playing);
  };

  const seekTo = (time: number) => {
    if (soundRef.current) {
      soundRef.current.seek(time);
      setCurrentTime(time);
    }
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
  const [llmStarting, setLlmStarting] = useState(false);

  const checkLLMStatus = async () => {
    try {
      const status = await api.getLLMStatus();
      setLlmStatus(status);
    } catch {
      setLlmStatus({ available: false, base_url: '', model: null, error: 'Failed to check status' });
    }
  };

  const handleStartLLM = async () => {
    setLlmStarting(true);
    setLlmError(null);
    try {
      // Start server (will also auto-load model from config)
      const serverResult = await api.startLMStudioServer();
      if (!serverResult.success && !serverResult.message.includes('already running') && !serverResult.message.includes('loaded')) {
        setLlmError(serverResult.message);
        setLlmStarting(false);
        return;
      }
      // Refresh status
      await checkLLMStatus();
    } catch (error) {
      setLlmError((error as Error).message);
    } finally {
      setLlmStarting(false);
    }
  };

  const handleSummarize = async () => {
    if (!selectedRecording?.transcription) return;

    // Abort any previous request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    setLlmLoading(true);
    setLlmError(null);
    setLlmSummary('');
    setIsEditingSummary(false);
    streamingSummaryRef.current = ''; // Reset streaming ref

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
    const fullText = selectedRecording.transcription.segments
      .map((seg) =>
        seg.speaker
          ? `[${seg.speaker}]: ${seg.text}`
          : seg.text
      )
      .join('\n');

    // Keep track of recording ID for the save callback
    const recordingId = selectedRecording.id;

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
              // Update the recording in state
              setRecordings(prev => prev.map(rec => 
                rec.id === recordingId ? { ...rec, summary: streamingSummaryRef.current } : rec
              ));
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

  // Save summary to database
  const saveSummary = async (summary: string) => {
    if (!selectedRecording) return;
    try {
      await api.updateSummary(selectedRecording.id, summary || null);
      // Update the recording in state with the new summary
      setRecordings(prev => prev.map(rec => 
        rec.id === selectedRecording.id ? { ...rec, summary } : rec
      ));
    } catch (error) {
      console.error('Failed to save summary:', error);
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
    }, 1000); // Save 1 second after user stops typing
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
    // Clear in database too
    await saveSummary('');
  };

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setLlmLoading(false);
  };

  const pollJobStatus = async (recordingId: number) => {
    const maxAttempts = 120;
    let attempts = 0;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        setImportError('Transcription timed out');
        setImportLoading(false);
        return;
      }

      try {
        const status = await api.getTranscriptionStatus(recordingId);
        setImportProgress(status.message || `Status: ${status.status}`);

        if (status.status === 'completed') {
          setImportLoading(false);
          setImportProgress(null);
          setDialogOpen(false);
          setNewEntryFilePath('');
          setNewEntryFile(null);
          await loadRecordingsForDay();
        } else if (status.status === 'failed') {
          setImportError(status.message || 'Transcription failed');
          setImportLoading(false);
          setImportProgress(null);
        } else {
          attempts++;
          setTimeout(poll, 5000);
        }
      } catch (err) {
        setImportError('Failed to check transcription status');
        setImportLoading(false);
        setImportProgress(null);
      }
    };

    poll();
  };

  const handleCreateEntry = async () => {
    if (!newEntryFile && !newEntryFilePath.trim()) {
      setImportError('Please select an audio file');
      return;
    }

    setImportLoading(true);
    setImportError(null);
    setImportProgress('Starting transcription...');

    try {
      let response;
      
      let nextMinute = 1;
      let nextSecond = 0;
      if (newEntryHour !== null) {
        try {
          const result = await api.getNextAvailableMinute(currentDate.format('YYYY-MM-DD'), newEntryHour);
          nextMinute = result.next_minute;
          nextSecond = result.next_second ?? 0;
        } catch (err: any) {
          if (err?.response?.status === 400) {
            setImportError(err?.response?.data?.detail || 'Hour block is full');
            setImportLoading(false);
            return;
          }
          console.warn('Failed to get next minute, using 1:', err);
        }
      }
      
      const recordedAt = newEntryHour !== null 
        ? currentDate.hour(newEntryHour).minute(nextMinute).second(nextSecond).format('YYYY-MM-DDTHH:mm:ss')
        : currentDate.format('YYYY-MM-DDTHH:mm:ss');
      
      if (newEntryFile) {
        response = await api.uploadFile(newEntryFile, enableDiarization, enableWordTimestamps, recordedAt);
      } else {
        response = await api.importFile(newEntryFilePath, true, enableDiarization, enableWordTimestamps);
      }
      pollJobStatus(response.recording_id);
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      setImportError(error.response?.data?.detail || 'Failed to import file');
      setImportLoading(false);
      setImportProgress(null);
    }
  };

  const handleCloseRecording = () => {
    setSelectedRecording(null);
    if (soundRef.current) {
      soundRef.current.unload();
    }
    setPlaying(false);
    setCurrentTime(0);
    setDuration(0);
    // Clear LLM state
    setLlmSummary('');
    setLlmError(null);
    setLlmLoading(false);
    setIsEditingSummary(false);
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  const handleContextMenu = (event: React.MouseEvent, rec: RecordingWithTranscription) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      recording: rec,
    });
  };

  const handleCloseContextMenu = () => {
    setContextMenu(null);
  };

  const handleDeleteClick = () => {
    if (contextMenu) {
      setDeleteRecording(contextMenu.recording);
      setDeleteDialogOpen(true);
    }
    handleCloseContextMenu();
  };

  const handleChangeDateClick = () => {
    if (contextMenu) {
      const rec = contextMenu.recording;
      setChangeDateRecording(rec);
      const recordedAt = dayjs(rec.recorded_at);
      setNewDate(recordedAt.format('YYYY-MM-DD'));
      setNewTime(recordedAt.format('HH:mm'));
      setChangeDateDialogOpen(true);
      setChangeDateError(null);
    }
    handleCloseContextMenu();
  };

  const handleConfirmDelete = async () => {
    if (!deleteRecording) return;
    
    setDeleteLoading(true);
    try {
      await api.deleteRecording(deleteRecording.id);
      setDeleteDialogOpen(false);
      setDeleteRecording(null);
      await loadRecordingsForDay();
    } catch (err) {
      console.error('Failed to delete recording:', err);
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleConfirmChangeDate = async () => {
    if (!changeDateRecording || !newDate || !newTime) return;
    
    setChangeDateLoading(true);
    setChangeDateError(null);
    
    try {
      const newDateTime = dayjs(`${newDate}T${newTime}`);
      if (!newDateTime.isValid()) {
        setChangeDateError('Invalid date or time');
        setChangeDateLoading(false);
        return;
      }
      
      await api.updateRecordingDate(changeDateRecording.id, newDateTime.format('YYYY-MM-DDTHH:mm:ss'));
      setChangeDateDialogOpen(false);
      setChangeDateRecording(null);
      await loadRecordingsForDay();
    } catch (err) {
      console.error('Failed to update recording date:', err);
      setChangeDateError('Failed to update recording date');
    } finally {
      setChangeDateLoading(false);
    }
  };

  const { morning, afternoon } = getHourSlots();

  const handleRecordingClick = (rec: RecordingWithTranscription, event: React.MouseEvent) => {
    event.stopPropagation();
    setSelectedRecording(rec);
    // Load existing summary if available
    setLlmSummary(rec.summary || '');
    setLlmError(null);
    loadAudio(rec.id);
  };

  const handleAddClick = (hour: number, event: React.MouseEvent) => {
    event.stopPropagation();
    setNewEntryHour(hour);
    setDialogOpen(true);
  };

  const formatDuration = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.round(seconds / 60);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    const remainingMins = mins % 60;
    return remainingMins > 0 ? `${hours}h ${remainingMins}m` : `${hours}h`;
  };

  const formatRecordingTime = (dateStr: string): string => {
    return dayjs(dateStr).format('h:mm A');
  };

  const renderHourSlot = (slot: HourSlot) => {
    const visibleRecordings = slot.recordings.slice(0, 4);
    const hasMore = slot.recordings.length > 4;
    
    return (
      <div key={slot.hour} className="flex group h-20 mb-2">
        <div className="w-16 text-right pr-4 pt-2 text-sm text-gray-500 font-mono shrink-0">
          {formatHour(slot.hour)}
        </div>
        <div className="flex-1 border-l border-gray-800 pl-4 relative">
          {/* Timeline dot */}
          <div className="absolute left-[-5px] top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-gray-800 group-hover:bg-primary/50 transition-colors z-10" />
          
          {/* Recordings Row */}
          <div className="flex items-center gap-2 h-full w-full">
            {visibleRecordings.map(rec => (
              <div 
                key={rec.id}
                onClick={(e) => handleRecordingClick(rec, e)}
                onContextMenu={(e) => handleContextMenu(e, rec)}
                className="flex-1 min-w-0 flex flex-col p-2 bg-surface border border-gray-700 hover:border-primary/50 hover:bg-gray-800 rounded-lg cursor-pointer transition-all group overflow-hidden h-full"
              >
                <div className="flex items-center justify-between mb-1 min-w-0">
                  <span className="font-medium text-white text-sm group-hover:text-primary truncate mr-1">
                    {rec.filename}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-auto">
                  <div className="flex items-center text-[10px] text-gray-500 truncate">
                    <Clock size={10} className="mr-1 shrink-0" />
                    {formatRecordingTime(rec.recorded_at)}
                  </div>
                  <span className="text-[10px] text-gray-600 bg-black/20 px-1.5 rounded shrink-0">
                    {formatDuration(rec.duration_seconds)}
                  </span>
                </div>
              </div>
            ))}
            
            {hasMore && (
              <div className="w-8 shrink-0 flex items-center justify-center text-xs text-gray-500 font-medium bg-surface border border-gray-800 rounded-lg h-full">
                +{slot.recordings.length - 4}
              </div>
            )}

            {/* Add button */}
            <button
              onClick={(e) => handleAddClick(slot.hour, e)}
              className="w-12 shrink-0 h-full border border-dashed border-gray-800 rounded-lg hover:border-gray-600 hover:bg-gray-900/50 cursor-pointer flex items-center justify-center transition-all"
            >
              <Plus size={18} className="text-gray-600 hover:text-gray-400" />
            </button>
          </div>
        </div>
      </div>
    );
  };

  const isNextDisabled = currentDate.isSame(dayjs(), 'day');

  if (loading) {
    return (
      <div className="flex justify-center mt-12">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-8 w-full">
        <div className="flex items-center space-x-4">
          <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-white">
            ← Month
          </button>
          <h1 className="text-2xl sm:text-3xl font-bold text-white">
            {currentDate.format('dddd, MMM D')}
          </h1>
        </div>
        <div className="flex space-x-2">
          <button onClick={handlePreviousDay} className="p-2 rounded-full hover:bg-gray-800 text-gray-400 hover:text-white">
            <ChevronLeft size={24} />
          </button>
          <button 
            onClick={handleNextDay} 
            disabled={isNextDisabled}
            className="p-2 rounded-full hover:bg-gray-800 text-gray-400 hover:text-white disabled:opacity-30"
          >
            <ChevronRight size={24} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-8 flex-1 overflow-auto w-full">
        {/* Morning Column */}
        <div className="w-full">
          <h2 className="text-lg font-semibold text-primary mb-6 border-b border-gray-800 pb-2">Morning</h2>
          <div className="space-y-1">
            {morning.map((slot) => renderHourSlot(slot))}
          </div>
        </div>

        {/* Afternoon Column */}
        <div className="w-full">
          <h2 className="text-lg font-semibold text-pink-400 mb-6 border-b border-gray-800 pb-2">Afternoon & Evening</h2>
          <div className="space-y-1">
            {afternoon.map((slot) => renderHourSlot(slot))}
          </div>
        </div>
      </div>

      {/* Selected Recording Modal */}
      <Modal
        open={!!selectedRecording}
        onClose={handleCloseRecording}
        title={selectedRecording?.filename}
        maxWidth="3xl"
      >
        {selectedRecording && (
          <div>
            <p className="text-sm text-gray-400 mb-4">
              Recorded: {new Date(selectedRecording.recorded_at).toLocaleString()} | 
              Duration: {formatTime(selectedRecording.duration_seconds)} | 
              Words: {selectedRecording.word_count}
              {selectedRecording.has_diarization && (
                <span className="chip-primary ml-2">Diarization</span>
              )}
            </p>

            {/* Audio player */}
            <div className="bg-surface-light rounded-lg p-4 mb-4">
              <div className="flex items-center gap-2">
                <button onClick={() => seekTo(Math.max(0, currentTime - 10))} className="btn-icon">
                  <RotateCcw size={20} />
                </button>
                <button onClick={togglePlayPause} className="btn-icon p-3">
                  {playing ? <Pause size={28} /> : <Play size={28} />}
                </button>
                <button onClick={() => seekTo(Math.min(duration, currentTime + 10))} className="btn-icon">
                  <RotateCw size={20} />
                </button>
                <span className="text-sm text-gray-400 min-w-[60px]">
                  {formatTime(currentTime)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={duration || 100}
                  value={currentTime}
                  onChange={(e) => seekTo(parseFloat(e.target.value))}
                  className="flex-1 h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-primary mx-2"
                />
                <span className="text-sm text-gray-400 min-w-[60px] text-right">
                  {formatTime(duration)}
                </span>
              </div>
            </div>

            {/* AI Summary Panel - Shows above transcript when there's content */}
            {(llmSummary || llmLoading || llmError) && (
              <div className="rounded-lg p-4 mb-4 border border-purple-500/30 bg-purple-950/20">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Sparkles size={18} className="text-purple-400" />
                    <h3 className="text-lg font-medium text-white">AI Summary</h3>
                    {llmStatus?.model && (
                      <span className="text-xs text-gray-500 ml-2">
                        {llmStatus.model}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Start LLM button when not available */}
                    {!llmStatus?.available && !llmLoading && (
                      <button
                        onClick={handleStartLLM}
                        className="btn-ghost text-green-400 hover:text-green-300 text-sm flex items-center gap-1"
                        disabled={llmStarting}
                      >
                        {llmStarting ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Power size={14} />
                        )}
                        Start LLM
                      </button>
                    )}
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

            {/* Transcript */}
            {selectedRecording.transcription && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-lg font-medium text-white">Transcript</h3>
                  
                  {/* AI Buttons */}
                  {!llmSummary && !llmLoading && (
                    <div className="flex items-center gap-2">
                      {!llmStatus?.available ? (
                        <button
                          onClick={handleStartLLM}
                          className="btn-ghost text-green-400 hover:text-green-300 flex items-center gap-2"
                          disabled={llmStarting}
                        >
                          {llmStarting ? (
                            <Loader2 size={18} className="animate-spin" />
                          ) : (
                            <Power size={18} />
                          )}
                          <span>Start LLM</span>
                        </button>
                      ) : (
                        <button
                          onClick={handleSummarize}
                          className="btn-ghost text-purple-400 hover:text-purple-300 flex items-center gap-2"
                          disabled={llmLoading}
                        >
                          <Bot size={18} />
                          <span>Summarize with AI</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
                {selectedRecording.transcription.segments.map((segment, segIndex) => (
                  <div key={segIndex} className="mb-3">
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
            )}
          </div>
        )}
      </Modal>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="audio/*,.mp3,.wav,.opus,.ogg,.flac,.m4a,.wma,.aac"
        className="hidden"
        onChange={handleFileInputChange}
      />

      {/* New Entry Modal */}
      <Modal
        open={dialogOpen}
        onClose={() => !importLoading && setDialogOpen(false)}
        title={`New Recording Entry - ${newEntryHour !== null ? formatHour(newEntryHour) : ''}`}
        disableBackdropClick={importLoading}
        footer={
          <>
            <button
              onClick={() => { setDialogOpen(false); setNewEntryFile(null); setNewEntryFilePath(''); }}
              disabled={importLoading}
              className="btn-ghost"
            >
              Cancel
            </button>
            <button
              onClick={handleCreateEntry}
              disabled={importLoading || (!newEntryFile && !newEntryFilePath.trim())}
              className="btn-primary"
            >
              {importLoading ? <Loader2 className="animate-spin" size={20} /> : 'Create & Transcribe'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <button
            onClick={openFilePicker}
            disabled={importLoading}
            className="btn-primary w-full py-3"
          >
            <Search size={20} />
            Browse for Audio File
          </button>

          {newEntryFilePath && (
            <div className="bg-surface-light rounded-lg p-3">
              <p className="text-xs text-gray-400">Selected file:</p>
              <p className="text-sm text-white break-all">{newEntryFilePath}</p>
            </div>
          )}

          <p className="text-xs text-gray-500">
            Supported formats: MP3, WAV, OPUS, OGG, FLAC, M4A, WMA, AAC
          </p>

          <Toggle
            checked={enableWordTimestamps}
            onChange={setEnableWordTimestamps}
            label="Enable word-level timestamps"
            disabled={importLoading}
          />
          
          <Toggle
            checked={enableDiarization}
            onChange={setEnableDiarization}
            label="Enable speaker diarization"
            disabled={importLoading}
          />

          {importProgress && (
            <div>
              <p className="text-sm text-gray-400 mb-2">{importProgress}</p>
              <ProgressBar indeterminate />
            </div>
          )}

          {importError && (
            <Alert severity="error">{importError}</Alert>
          )}
        </div>
      </Modal>

      {/* Context Menu */}
      <ContextMenu
        open={contextMenu !== null}
        onClose={handleCloseContextMenu}
        position={contextMenu ? { x: contextMenu.x, y: contextMenu.y } : null}
      >
        <ContextMenuItem onClick={handleChangeDateClick} icon={<CalendarDays size={16} />}>
          Change Date & Time
        </ContextMenuItem>
        <ContextMenuItem onClick={handleDeleteClick} icon={<Trash2 size={16} />} danger>
          Delete Recording
        </ContextMenuItem>
      </ContextMenu>

      {/* Delete Confirmation Modal */}
      <Modal
        open={deleteDialogOpen}
        onClose={() => !deleteLoading && setDeleteDialogOpen(false)}
        title="Delete Recording?"
        disableBackdropClick={deleteLoading}
        footer={
          <>
            <button
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteLoading}
              className="btn-ghost"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmDelete}
              disabled={deleteLoading}
              className="btn-danger"
            >
              {deleteLoading ? <Loader2 className="animate-spin" size={20} /> : 'Delete'}
            </button>
          </>
        }
      >
        <p className="text-white">
          Are you sure you want to delete "{deleteRecording?.filename}"?
        </p>
        <p className="text-sm text-gray-400 mt-2">
          This will permanently delete the audio file and its transcription.
        </p>
      </Modal>

      {/* Change Date Modal */}
      <Modal
        open={changeDateDialogOpen}
        onClose={() => !changeDateLoading && setChangeDateDialogOpen(false)}
        title="Change Date & Time"
        disableBackdropClick={changeDateLoading}
        footer={
          <>
            <button
              onClick={() => setChangeDateDialogOpen(false)}
              disabled={changeDateLoading}
              className="btn-ghost"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmChangeDate}
              disabled={changeDateLoading || !newDate || !newTime}
              className="btn-primary"
            >
              {changeDateLoading ? <Loader2 className="animate-spin" size={20} /> : 'Update'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-400">
            Recording: {changeDateRecording?.filename}
          </p>
          <div>
            <label className="label">Date</label>
            <input
              type="date"
              className="input"
              value={newDate}
              onChange={(e) => setNewDate(e.target.value)}
              disabled={changeDateLoading}
            />
          </div>
          <div>
            <label className="label">Time</label>
            <input
              type="time"
              className="input"
              value={newTime}
              onChange={(e) => setNewTime(e.target.value)}
              disabled={changeDateLoading}
            />
          </div>
          {changeDateError && (
            <Alert severity="error">{changeDateError}</Alert>
          )}
        </div>
      </Modal>
    </div>
  );
}
