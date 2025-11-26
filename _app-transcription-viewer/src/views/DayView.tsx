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
  TextField,
  Switch,
  FormControlLabel,
  Chip,
  CircularProgress,
  Slider,
  InputAdornment,
  Alert,
} from '@mui/material';
import {
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Replay10 as Replay10Icon,
  Forward10 as Forward10Icon,
  Folder as FolderIcon,
} from '@mui/icons-material';
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
  const [newEntryTitle, setNewEntryTitle] = useState('');
  const [newEntryFilePath, setNewEntryFilePath] = useState('');
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

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
      const hourRecordings = recordings.filter(rec => {
        const recordedAt = dayjs(rec.recorded_at);
        return recordedAt.hour() === hour;
      });

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

  const handleHourClick = (hour: number, recordings: RecordingWithTranscription[]) => {
    if (recordings.length > 0) {
      setSelectedRecording(recordings[0]);
      loadAudio(recordings[0].id);
    } else {
      setNewEntryHour(hour);
      setNewEntryTitle(`Recording ${getRecordingNumberForHour(hour)}`);
      setDialogOpen(true);
    }
  };

  const getRecordingNumberForHour = (_hour: number): number => {
    // Count existing recordings for the day and add 1
    return recordings.length + 1;
  };

  const loadAudio = async (recordingId: number) => {
    if (soundRef.current) {
      soundRef.current.unload();
    }
    
    const audioUrl = api.getAudioUrl(recordingId);
    soundRef.current = new Howl({
      src: [audioUrl],
      html5: true,
      onload: () => {
        setDuration(soundRef.current?.duration() || 0);
      },
      onend: () => {
        setPlaying(false);
      },
    });
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

  const handleCreateEntry = async () => {
    if (!newEntryFilePath.trim()) {
      setImportError('Please provide an audio file path');
      return;
    }

    setImportLoading(true);
    setImportError(null);

    try {
      await api.importFile(newEntryFilePath, true, enableDiarization, enableWordTimestamps);
      setDialogOpen(false);
      setNewEntryFilePath('');
      setNewEntryTitle('');
      // Reload recordings
      await loadRecordingsForDay();
    } catch (err: any) {
      setImportError(err.response?.data?.detail || 'Failed to import file');
    } finally {
      setImportLoading(false);
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

  const { morning, afternoon } = getHourSlots();

  const renderHourSlot = (slot: HourSlot) => {
    const hasRecordings = slot.recordings.length > 0;
    
    return (
      <Paper
        key={slot.hour}
        elevation={hasRecordings ? 3 : 1}
        onClick={() => handleHourClick(slot.hour, slot.recordings)}
        sx={{
          p: 1.5,
          mb: 1,
          cursor: 'pointer',
          bgcolor: hasRecordings ? 'primary.dark' : 'background.paper',
          border: hasRecordings ? '2px solid' : '1px solid',
          borderColor: hasRecordings ? 'primary.main' : 'divider',
          transition: 'all 0.2s',
          '&:hover': {
            bgcolor: hasRecordings ? 'primary.main' : 'action.hover',
            transform: 'scale(1.02)',
          },
          position: 'relative',
        }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
        {hasRecordings && (
          <Box sx={{ mt: 1 }}>
            {slot.recordings.map((rec, idx) => (
              <Typography
                key={rec.id}
                variant="caption"
                sx={{ display: 'block', color: 'primary.contrastText' }}
              >
                {rec.filename || `Recording ${idx + 1}`}
              </Typography>
            ))}
          </Box>
        )}
        {!hasRecordings && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 0.5, opacity: 0.3 }}>
            <AddIcon fontSize="small" />
          </Box>
        )}
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

      {/* Selected Recording View */}
      {selectedRecording && (
        <Paper sx={{ p: 3, mt: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h5">{selectedRecording.filename}</Typography>
            <IconButton onClick={handleCloseRecording}>
              <CloseIcon />
            </IconButton>
          </Box>
          
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
        </Paper>
      )}

      {/* New Entry Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          New Recording Entry - {newEntryHour !== null && formatHour(newEntryHour)}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <TextField
              fullWidth
              label="Title"
              value={newEntryTitle}
              onChange={(e) => setNewEntryTitle(e.target.value)}
              sx={{ mb: 3 }}
            />
            
            <TextField
              fullWidth
              label="Audio File Path"
              placeholder="/path/to/audio.mp3"
              value={newEntryFilePath}
              onChange={(e) => setNewEntryFilePath(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <FolderIcon sx={{ color: 'text.secondary' }} />
                  </InputAdornment>
                ),
              }}
              sx={{ mb: 2 }}
            />

            <FormControlLabel
              control={
                <Switch
                  checked={enableWordTimestamps}
                  onChange={(e) => setEnableWordTimestamps(e.target.checked)}
                />
              }
              label="Enable word-level timestamps"
            />
            
            <FormControlLabel
              control={
                <Switch
                  checked={enableDiarization}
                  onChange={(e) => setEnableDiarization(e.target.checked)}
                />
              }
              label="Enable speaker diarization"
            />

            {importError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {importError}
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateEntry}
            variant="contained"
            disabled={importLoading}
          >
            {importLoading ? <CircularProgress size={24} /> : 'Create & Transcribe'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
