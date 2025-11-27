import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  IconButton,
  Slider,
  CircularProgress,
  Chip,
  Button,
} from '@mui/material';
import {
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Replay10 as Replay10Icon,
  Forward10 as Forward10Icon,
  ChevronLeft as ArrowBackIcon,
  CalendarMonth as CalendarIcon,
} from '@mui/icons-material';
import { Howl } from 'howler';
import dayjs from 'dayjs';
import { api } from '../services/api';
import { Recording, Transcription, Word } from '../types';

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

  useEffect(() => {
    if (id) {
      loadRecording(parseInt(id));
    }
    return () => {
      // Cleanup
      if (soundRef.current) {
        soundRef.current.unload();
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
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

  const handleSliderChange = (_: Event, value: number | number[]) => {
    seekTo(value as number);
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

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!recording || !transcription) {
    return (
      <Typography color="error">Failed to load recording</Typography>
    );
  }

  return (
    <Box>
      {/* Back button */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate(-1)}
        sx={{ mb: 2 }}
      >
        Back
      </Button>

      {/* Recording info */}
      <Paper sx={{ p: 3, mb: 2 }}>
        <Typography variant="h5" sx={{ mb: 2 }}>{recording.filename}</Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, color: 'text.secondary' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <CalendarIcon fontSize="small" />
            <Typography variant="body2">
              {dayjs(recording.recorded_at).format('MMMM D, YYYY')}
            </Typography>
          </Box>
          <Typography variant="body2">
            Duration: {formatTime(recording.duration_seconds)}
          </Typography>
          <Typography variant="body2">
            {recording.word_count} words
          </Typography>
          {recording.has_diarization && (
            <Chip label="Speaker Diarization" size="small" color="primary" variant="outlined" />
          )}
        </Box>
      </Paper>


      {/* Audio player */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
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
            max={duration}
            onChange={handleSliderChange}
            sx={{ mx: 2 }}
          />
          <Typography variant="body2" sx={{ minWidth: 80 }}>
            {formatTime(duration)}
          </Typography>
        </Box>
      </Paper>

      {/* Transcript with clickable words */}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Transcript
        </Typography>
        {transcription.segments.map((segment, segIndex) => (
          <Box key={segIndex} sx={{ mb: 2 }}>
            {segment.speaker && (
              <Chip
                label={segment.speaker}
                size="small"
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
      </Paper>
    </Box>
  );
}
