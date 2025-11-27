import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  IconButton,
  Grid,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Switch,
  FormControlLabel,
  Chip,
  CircularProgress,
  Slider,
  Alert,
  LinearProgress,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  TextField,
} from '@mui/material';
import {
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Replay10 as Replay10Icon,
  Forward10 as Forward10Icon,
  Search as BrowseIcon,
} from '@mui/icons-material';
import DeleteOutlined from '@mui/icons-material/DeleteOutlined';
import EditCalendar from '@mui/icons-material/EditCalendar';
import AddIcon from '@mui/icons-material/Add';
import CloseIcon from '@mui/icons-material/Close';
import dayjs, { Dayjs } from 'dayjs';
import { Howl } from 'howler';
import { api } from '../services/api';
import { Recording, Transcription, Word } from '../types';

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
    mouseX: number;
    mouseY: number;
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
        // Sort by oldest first (earliest recorded_at)
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

  // Open HTML file picker
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
    // Reset file input for re-selection
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
        // Start the animation loop when audio actually starts playing
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
    const maxAttempts = 120; // 10 minutes at 5 second intervals
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
          // Still processing, poll again
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
      
      // Get the next available minute for this hour slot
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
      
      // Calculate the recorded_at timestamp from the selected date, hour, and next available minute
      // Use .format() instead of .toISOString() to avoid UTC conversion - we want local time
      const recordedAt = newEntryHour !== null 
        ? currentDate.hour(newEntryHour).minute(nextMinute).second(nextSecond).format('YYYY-MM-DDTHH:mm:ss')
        : currentDate.format('YYYY-MM-DDTHH:mm:ss');
      
      if (newEntryFile) {
        // Upload file directly with the user-selected date/time
        response = await api.uploadFile(newEntryFile, enableDiarization, enableWordTimestamps, recordedAt);
      } else {
        // Use server-side file path
        response = await api.importFile(newEntryFilePath, true, enableDiarization, enableWordTimestamps);
      }
      // Start polling for transcription status
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

  // Context menu handlers
  const handleContextMenu = (event: React.MouseEvent, rec: RecordingWithTranscription) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      mouseX: event.clientX,
      mouseY: event.clientY,
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
      // Parse the current recorded_at to pre-fill the dialog
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
      // Combine date and time into ISO string
      // Use .format() instead of .toISOString() to avoid UTC conversion - we want local time
      const newDateTime = dayjs(`${newDate}T${newTime}`);
      if (!newDateTime.isValid()) {
        setChangeDateError('Invalid date or time');
        setChangeDateLoading(false);
        return;
      }
      
      await api.updateRecordingDate(changeDateRecording.id, newDateTime.format('YYYY-MM-DDTHH:mm:ss'));
      setChangeDateDialogOpen(false);
      setChangeDateRecording(null);
      
      // If the new date is different from the current date, the recording will disappear from this view
      // Reload to reflect changes
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
      <Paper
        key={slot.hour}
        elevation={1}
        sx={{
          p: 1.5,
          mb: 1,
          bgcolor: 'background.paper',
          border: '1px solid',
          borderColor: 'divider',
          position: 'relative',
        }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="body2" fontWeight={hasRecordings ? 'bold' : 'normal'}>
            {formatHour(slot.hour)}
          </Typography>
          {hasRecordings && (
            <Chip
              size="small"
              label={slot.recordings.length}
              color="error"
              sx={{ height: 20, minWidth: 20, '& .MuiChip-label': { px: 0.5 } }}
            />
          )}
        </Box>
        
        {/* Recordings row with adaptive width */}
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'stretch', minHeight: 48 }}>
          {/* Visible recordings */}
          {visibleRecordings.map((rec) => (
            <Paper
              key={rec.id}
              elevation={3}
              onClick={(e) => handleRecordingClick(rec, e)}
              onContextMenu={(e) => handleContextMenu(e, rec)}
              sx={{
                flex: '1 1 auto',
                minWidth: 0,
                p: 1,
                cursor: 'pointer',
                bgcolor: 'primary.dark',
                border: '2px solid',
                borderColor: 'primary.main',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s',
                '&:hover': {
                  bgcolor: 'primary.main',
                  transform: 'scale(1.02)',
                },
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  color: 'primary.contrastText',
                  textAlign: 'center',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {rec.filename || 'Recording'}
              </Typography>
            </Paper>
          ))}
          
          {/* "More" indicator if there are hidden recordings */}
          {hiddenCount > 0 && (
            <Box
              sx={{
                flex: `0 0 auto`,
                display: 'flex',
                alignItems: 'center',
                px: 0.5,
              }}
            >
              <Typography variant="caption" color="text.secondary">
                +{hiddenCount}
              </Typography>
            </Box>
          )}
          
          {/* Add button - always visible */}
          <Paper
            elevation={1}
            onClick={(e) => handleAddClick(slot.hour, e)}
            sx={{
              flex: '0 0 auto',
              width: 48,
              p: 1,
              cursor: 'pointer',
              bgcolor: 'background.default',
              border: '2px dashed',
              borderColor: 'divider',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
              opacity: 0.6,
              '&:hover': {
                opacity: 1,
                borderColor: 'primary.main',
                bgcolor: 'action.hover',
              },
            }}
          >
            <AddIcon fontSize="small" />
          </Paper>
        </Box>
      </Paper>
    );
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {/* Day navigation */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          mb: 3,
        }}
      >
        <IconButton onClick={handlePreviousDay}>
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="h4" sx={{ mx: 3, minWidth: 300, textAlign: 'center' }}>
          {currentDate.format('dddd, MMMM D, YYYY')}
        </Typography>
        <IconButton
          onClick={handleNextDay}
          disabled={currentDate.isSame(dayjs(), 'day')}
        >
          <ChevronRightIcon />
        </IconButton>
      </Box>

      <Button
        variant="outlined"
        onClick={() => navigate('/')}
        sx={{ mb: 2 }}
      >
        Back to Calendar
      </Button>

      {/* Two-column hour grid */}
      <Grid container spacing={3}>
        {/* Morning (0:00 - 11:00) */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 2, textAlign: 'center' }}>
              Morning (12 AM - 11 AM)
            </Typography>
            {morning.map(slot => renderHourSlot(slot))}
          </Paper>
        </Grid>

        {/* Afternoon/Evening (12:00 - 23:00) */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 2, textAlign: 'center' }}>
              Afternoon/Evening (12 PM - 11 PM)
            </Typography>
            {afternoon.map(slot => renderHourSlot(slot))}
          </Paper>
        </Grid>
      </Grid>

      {/* Selected Recording Dialog */}
      <Dialog 
        open={!!selectedRecording} 
        onClose={handleCloseRecording}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: { maxHeight: '90vh' }
        }}
      >
        {selectedRecording && (
          <>
            <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="h5" component="span">{selectedRecording.filename}</Typography>
              <IconButton onClick={handleCloseRecording} size="small">
                <CloseIcon />
              </IconButton>
            </DialogTitle>
            <DialogContent dividers>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Recorded: {new Date(selectedRecording.recorded_at).toLocaleString()} | 
                Duration: {formatTime(selectedRecording.duration_seconds)} | 
                Words: {selectedRecording.word_count}
                {selectedRecording.has_diarization && (
                  <Chip label="Diarization" size="small" sx={{ ml: 1 }} />
                )}
              </Typography>

              {/* Audio player */}
              <Paper sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <IconButton onClick={() => seekTo(Math.max(0, currentTime - 10))}>
                    <Replay10Icon />
                  </IconButton>
                  <IconButton onClick={togglePlayPause} size="large">
                    {playing ? <PauseIcon fontSize="large" /> : <PlayIcon fontSize="large" />}
                  </IconButton>
                  <IconButton onClick={() => seekTo(Math.min(duration, currentTime + 10))}>
                    <Forward10Icon />
                  </IconButton>
                  <Typography variant="body2" sx={{ minWidth: 80 }}>
                    {formatTime(currentTime)}
                  </Typography>
                  <Slider
                    value={currentTime}
                    max={duration || 100}
                    onChange={(_, value) => seekTo(value as number)}
                    sx={{ mx: 2 }}
                  />
                  <Typography variant="body2" sx={{ minWidth: 80 }}>
                    {formatTime(duration)}
                  </Typography>
                </Box>
              </Paper>

              {/* Transcript */}
              {selectedRecording.transcription && (
                <Box>
                  <Typography variant="h6" sx={{ mb: 2 }}>
                    Transcript
                  </Typography>
                  {selectedRecording.transcription.segments.map((segment, segIndex) => (
                    <Box key={segIndex} sx={{ mb: 2 }}>
                      {segment.speaker && (
                        <Chip
                          label={segment.speaker}
                          size="small"
                          color="primary"
                          sx={{ mb: 1 }}
                        />
                      )}
                      <Box sx={{ lineHeight: 2 }}>
                        {segment.words ? (
                          segment.words.map((word, wordIndex) => (
                            <Typography
                              key={`${segIndex}-${wordIndex}`}
                              component="span"
                              onClick={() => handleWordClick(word)}
                              sx={{
                                cursor: 'pointer',
                                px: 0.3,
                                borderRadius: 0.5,
                                bgcolor: isWordActive(word) ? 'primary.main' : 'transparent',
                                color: isWordActive(word) ? 'primary.contrastText' : 'text.primary',
                                '&:hover': {
                                  bgcolor: isWordActive(word) ? 'primary.dark' : 'action.hover',
                                },
                              }}
                            >
                              {word.word}{' '}
                            </Typography>
                          ))
                        ) : (
                          <Typography>{segment.text}</Typography>
                        )}
                      </Box>
                    </Box>
                  ))}
                </Box>
              )}
            </DialogContent>
          </>
        )}
      </Dialog>

      {/* Hidden file input for web fallback */}
      <input
        ref={fileInputRef}
        type="file"
        accept="audio/*,.mp3,.wav,.opus,.ogg,.flac,.m4a,.wma,.aac"
        style={{ display: 'none' }}
        onChange={handleFileInputChange}
      />

      {/* New Entry Dialog */}
      <Dialog open={dialogOpen} onClose={() => !importLoading && setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          New Recording Entry - {newEntryHour !== null && formatHour(newEntryHour)}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            {/* File picker button */}
            <Button
              variant="contained"
              size="large"
              startIcon={<BrowseIcon />}
              onClick={openFilePicker}
              disabled={importLoading}
              sx={{ py: 2, px: 4, mb: 2, width: '100%' }}
            >
              Browse for Audio File
            </Button>

            {/* Show selected file */}
            {newEntryFilePath && (
              <Paper sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
                <Typography variant="body2" color="text.secondary">
                  Selected file:
                </Typography>
                <Typography variant="body1" sx={{ wordBreak: 'break-all' }}>
                  {newEntryFilePath}
                </Typography>
              </Paper>
            )}

            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Supported formats: MP3, WAV, OPUS, OGG, FLAC, M4A, WMA, AAC
            </Typography>

            <FormControlLabel
              control={
                <Switch
                  checked={enableWordTimestamps}
                  onChange={(e) => setEnableWordTimestamps(e.target.checked)}
                  disabled={importLoading}
                />
              }
              label="Enable word-level timestamps"
            />
            
            <FormControlLabel
              control={
                <Switch
                  checked={enableDiarization}
                  onChange={(e) => setEnableDiarization(e.target.checked)}
                  disabled={importLoading}
                />
              }
              label="Enable speaker diarization"
            />

            {importProgress && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  {importProgress}
                </Typography>
                <LinearProgress />
              </Box>
            )}

            {importError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {importError}
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setDialogOpen(false); setNewEntryFile(null); setNewEntryFilePath(''); }} disabled={importLoading}>Cancel</Button>
          <Button
            onClick={handleCreateEntry}
            variant="contained"
            disabled={importLoading || (!newEntryFile && !newEntryFilePath.trim())}
          >
            {importLoading ? <CircularProgress size={24} /> : 'Create & Transcribe'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Context Menu */}
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu !== null
            ? { top: contextMenu.mouseY, left: contextMenu.mouseX }
            : undefined
        }
      >
        <MenuItem onClick={handleChangeDateClick}>
          <ListItemIcon>
            <EditCalendar fontSize="small" />
          </ListItemIcon>
          <ListItemText>Change Date & Time</ListItemText>
        </MenuItem>
        <MenuItem onClick={handleDeleteClick} sx={{ color: 'error.main' }}>
          <ListItemIcon>
            <DeleteOutlined fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Delete Recording</ListItemText>
        </MenuItem>
      </Menu>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => !deleteLoading && setDeleteDialogOpen(false)}>
        <DialogTitle>Delete Recording?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete "{deleteRecording?.filename}"?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            This will permanently delete the audio file and its transcription.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} disabled={deleteLoading}>
            Cancel
          </Button>
          <Button
            onClick={handleConfirmDelete}
            color="error"
            variant="contained"
            disabled={deleteLoading}
          >
            {deleteLoading ? <CircularProgress size={24} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Change Date Dialog */}
      <Dialog open={changeDateDialogOpen} onClose={() => !changeDateLoading && setChangeDateDialogOpen(false)}>
        <DialogTitle>Change Date & Time</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Recording: {changeDateRecording?.filename}
            </Typography>
            <TextField
              label="Date"
              type="date"
              value={newDate}
              onChange={(e) => setNewDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
              disabled={changeDateLoading}
            />
            <TextField
              label="Time"
              type="time"
              value={newTime}
              onChange={(e) => setNewTime(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
              disabled={changeDateLoading}
            />
            {changeDateError && (
              <Alert severity="error">{changeDateError}</Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChangeDateDialogOpen(false)} disabled={changeDateLoading}>
            Cancel
          </Button>
          <Button
            onClick={handleConfirmChangeDate}
            variant="contained"
            disabled={changeDateLoading || !newDate || !newTime}
          >
            {changeDateLoading ? <CircularProgress size={24} /> : 'Update'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
