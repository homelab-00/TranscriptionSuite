import { useState, useRef, useCallback, useEffect } from 'react';

interface RawAudioRecorderOptions {
  onAudioData?: (data: ArrayBuffer) => void;
  onError?: (error: Error) => void;
  sampleRate?: number;
  chunkIntervalMs?: number;
}

const TARGET_SAMPLE_RATE = 16000;

/**
 * Hook for recording raw PCM audio data suitable for server-side transcription.
 * Uses AudioWorklet for efficient real-time audio processing.
 */
export function useRawAudioRecorder(options: RawAudioRecorderOptions = {}) {
  const {
    onAudioData,
    onError,
    sampleRate = TARGET_SAMPLE_RATE,
    chunkIntervalMs = 250,
  } = options;

  const [isRecording, setIsRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const timerRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const audioBufferRef = useRef<Float32Array[]>([]);
  const chunkTimerRef = useRef<number | null>(null);
  
  // Store callbacks in refs to avoid stale closures
  const onAudioDataRef = useRef(onAudioData);
  const onErrorRef = useRef(onError);
  onAudioDataRef.current = onAudioData;
  onErrorRef.current = onError;

  // Send accumulated audio chunks
  const sendAccumulatedAudio = useCallback(() => {
    if (audioBufferRef.current.length === 0) return;

    // Combine all buffered chunks
    const totalLength = audioBufferRef.current.reduce((sum, arr) => sum + arr.length, 0);
    const combined = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of audioBufferRef.current) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }
    audioBufferRef.current = [];

    // Resample if needed (browser typically captures at 44100 or 48000)
    let resampled = combined;
    if (audioContextRef.current && audioContextRef.current.sampleRate !== sampleRate) {
      const ratio = sampleRate / audioContextRef.current.sampleRate;
      const newLength = Math.round(combined.length * ratio);
      resampled = new Float32Array(newLength);
      
      // Simple linear interpolation resampling
      for (let i = 0; i < newLength; i++) {
        const srcIdx = i / ratio;
        const srcIdxFloor = Math.floor(srcIdx);
        const srcIdxCeil = Math.min(srcIdxFloor + 1, combined.length - 1);
        const t = srcIdx - srcIdxFloor;
        resampled[i] = combined[srcIdxFloor] * (1 - t) + combined[srcIdxCeil] * t;
      }
    }

    // Convert to Int16 PCM
    const pcmData = new Int16Array(resampled.length);
    for (let i = 0; i < resampled.length; i++) {
      // Clamp and convert
      const s = Math.max(-1, Math.min(1, resampled[i]));
      pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    // Create the binary message with metadata header
    const metadata = JSON.stringify({
      sample_rate: sampleRate,
      timestamp_ns: Date.now() * 1000000, // Convert ms to ns
      sequence: Date.now(),
    });
    const metadataBytes = new TextEncoder().encode(metadata);
    
    // Format: [4 bytes metadata length][metadata JSON][PCM data]
    const buffer = new ArrayBuffer(4 + metadataBytes.length + pcmData.byteLength);
    const view = new DataView(buffer);
    
    // Write metadata length (little-endian uint32)
    view.setUint32(0, metadataBytes.length, true);
    
    // Write metadata
    new Uint8Array(buffer, 4, metadataBytes.length).set(metadataBytes);
    
    // Write PCM data
    new Uint8Array(buffer, 4 + metadataBytes.length).set(new Uint8Array(pcmData.buffer));

    onAudioDataRef.current?.(buffer);
  }, [sampleRate]);

  const startRecording = useCallback(async () => {
    setError(null);
    setDuration(0);

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      streamRef.current = stream;

      // Create audio context
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      // Create source from stream
      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      // Use ScriptProcessorNode for audio processing
      // (AudioWorklet would be better but requires separate file)
      const bufferSize = 4096;
      const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        // Copy the data since the buffer will be reused
        audioBufferRef.current.push(new Float32Array(inputData));
      };

      // Connect the nodes
      source.connect(processor);
      processor.connect(audioContext.destination);

      setIsRecording(true);
      startTimeRef.current = Date.now();

      // Start duration timer
      timerRef.current = window.setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);

      // Start chunk sending timer
      chunkTimerRef.current = window.setInterval(() => {
        sendAccumulatedAudio();
      }, chunkIntervalMs);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to access microphone';
      setError(errorMessage);
      onErrorRef.current?.(new Error(errorMessage));
    }
  }, [chunkIntervalMs, sendAccumulatedAudio]);

  const stopRecording = useCallback(() => {
    // Send any remaining audio
    sendAccumulatedAudio();

    // Clean up processor
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    // Clean up source
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Stop stream tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    // Clear timers
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (chunkTimerRef.current) {
      clearInterval(chunkTimerRef.current);
      chunkTimerRef.current = null;
    }

    // Clear buffer
    audioBufferRef.current = [];

    // Reset duration for next recording
    setDuration(0);
    setIsRecording(false);
  }, [sendAccumulatedAudio]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (isRecording) {
        stopRecording();
      }
    };
  }, [isRecording, stopRecording]);

  const formatDuration = useCallback((seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }, []);

  return {
    isRecording,
    duration,
    formattedDuration: formatDuration(duration),
    error,
    startRecording,
    stopRecording,
  };
}
