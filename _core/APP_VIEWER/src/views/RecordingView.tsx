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
} from 'lucide-react';
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

      {/* Transcript with clickable words */}
      <div className="card p-4">
        <h2 className="text-lg font-medium text-white mb-4">Transcript</h2>
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
    </div>
  );
}
