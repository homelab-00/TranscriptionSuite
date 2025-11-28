import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
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
} from 'lucide-react';
import dayjs, { Dayjs } from 'dayjs';
import { Howl } from 'howler';
import { api } from '../services/api';
import { Recording, Transcription, Word } from '../types';
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
  
  // HTML file input ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadRecordingsForDay();
    return () => {
      if (soundRef.current) {
        soundRef.current.unload();
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
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
    if (soundRef.current) {
      soundRef.current.unload();
    }
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    }
    setPlaying(false);
    setCurrentTime(0);
    
    const audioUrl = api.getAudioUrl(recordingId);
    soundRef.current = new Howl({
      src: [audioUrl],
      html5: true,
      onload: () => {
        setDuration(soundRef.current?.duration() || 0);
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
    loadAudio(rec.id);
  };

  const handleAddClick = (hour: number, event: React.MouseEvent) => {
    event.stopPropagation();
    setNewEntryHour(hour);
    setDialogOpen(true);
  };

  const renderHourSlot = (slot: HourSlot) => {
    const hasRecordings = slot.recordings.length > 0;
    const maxVisible = 4;
    const visibleRecordings = slot.recordings.slice(0, maxVisible);
    const hiddenCount = Math.max(0, slot.recordings.length - maxVisible);
    
    return (
      <div
        key={slot.hour}
        className="p-3 mb-2 bg-surface rounded-lg border border-gray-800"
      >
        <div className="flex justify-between items-center mb-2">
          <span className={`text-sm ${hasRecordings ? 'font-semibold text-white' : 'text-gray-400'}`}>
            {formatHour(slot.hour)}
          </span>
          {hasRecordings && (
            <span className="chip-error text-xs">
              {slot.recordings.length}
            </span>
          )}
        </div>
        
        <div className="flex gap-1.5 items-stretch min-h-[48px]">
          {visibleRecordings.map((rec) => (
            <div
              key={rec.id}
              onClick={(e) => handleRecordingClick(rec, e)}
              onContextMenu={(e) => handleContextMenu(e, rec)}
              className="flex-1 min-w-0 p-2 cursor-pointer bg-primary/20 border-2 border-primary rounded-lg flex items-center justify-center transition-all duration-200 hover:bg-primary/30 hover:scale-[1.02]"
            >
              <span className="text-xs text-primary text-center truncate">
                {rec.filename || 'Recording'}
              </span>
            </div>
          ))}
          
          {hiddenCount > 0 && (
            <div className="flex items-center px-1 text-xs text-gray-500">
              +{hiddenCount}
            </div>
          )}
          
          <button
            onClick={(e) => handleAddClick(slot.hour, e)}
            className="flex-shrink-0 w-12 p-2 border-2 border-dashed border-gray-700 rounded-lg flex items-center justify-center opacity-60 hover:opacity-100 hover:border-primary hover:bg-surface-light transition-all"
          >
            <Plus size={16} className="text-gray-400" />
          </button>
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
    <div>
      {/* Day navigation */}
      <div className="flex items-center justify-center mb-6">
        <button onClick={handlePreviousDay} className="btn-icon">
          <ChevronLeft size={24} />
        </button>
        <h2 className="mx-4 min-w-[280px] text-center text-xl font-semibold text-white">
          {currentDate.format('dddd, MMMM D, YYYY')}
        </h2>
        <button
          onClick={handleNextDay}
          disabled={isNextDisabled}
          className={`btn-icon ${isNextDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <ChevronRight size={24} />
        </button>
      </div>

      <button
        onClick={() => navigate('/')}
        className="btn-outline mb-4"
      >
        Back to Calendar
      </button>

      {/* Two-column hour grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Morning */}
        <div className="card p-4">
          <h3 className="text-lg font-medium text-white text-center mb-4">
            Morning (12 AM - 11 AM)
          </h3>
          {morning.map(slot => renderHourSlot(slot))}
        </div>

        {/* Afternoon/Evening */}
        <div className="card p-4">
          <h3 className="text-lg font-medium text-white text-center mb-4">
            Afternoon/Evening (12 PM - 11 PM)
          </h3>
          {afternoon.map(slot => renderHourSlot(slot))}
        </div>
      </div>

      {/* Selected Recording Modal */}
      <Modal
        open={!!selectedRecording}
        onClose={handleCloseRecording}
        title={selectedRecording?.filename}
        maxWidth="lg"
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

            {/* Transcript */}
            {selectedRecording.transcription && (
              <div>
                <h3 className="text-lg font-medium text-white mb-3">Transcript</h3>
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
