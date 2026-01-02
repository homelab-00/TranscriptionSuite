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
  
  const onAudioDataRef = useRef(onAudioData);
  const onErrorRef = useRef(onError);
  onAudioDataRef.current = onAudioData;
  onErrorRef.current = onError;

  const sendAccumulatedAudio = useCallback(() => {
    if (audioBufferRef.current.length === 0) return;

    const totalLength = audioBufferRef.current.reduce((sum, arr) => sum + arr.length, 0);
    const combined = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of audioBufferRef.current) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }
    audioBufferRef.current = [];

    let resampled = combined;
    if (audioContextRef.current && audioContextRef.current.sampleRate !== sampleRate) {
      const ratio = sampleRate / audioContextRef.current.sampleRate;
      const newLength = Math.round(combined.length * ratio);
      resampled = new Float32Array(newLength);
      
      for (let i = 0; i < newLength; i++) {
        const srcIdx = i / ratio;
        const srcIdxFloor = Math.floor(srcIdx);
        const srcIdxCeil = Math.min(srcIdxFloor + 1, combined.length - 1);
        const t = srcIdx - srcIdxFloor;
        resampled[i] = combined[srcIdxFloor] * (1 - t) + combined[srcIdxCeil] * t;
      }
    }

    const pcmData = new Int16Array(resampled.length);
    for (let i = 0; i < resampled.length; i++) {
      const s = Math.max(-1, Math.min(1, resampled[i]));
      pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    const metadata = JSON.stringify({
      sample_rate: sampleRate,
      timestamp_ns: Date.now() * 1000000,
      sequence: Date.now(),
    });
    const metadataBytes = new TextEncoder().encode(metadata);
    
    const buffer = new ArrayBuffer(4 + metadataBytes.length + pcmData.byteLength);
    const view = new DataView(buffer);
    
    view.setUint32(0, metadataBytes.length, true);
    new Uint8Array(buffer, 4, metadataBytes.length).set(metadataBytes);
    new Uint8Array(buffer, 4 + metadataBytes.length).set(new Uint8Array(pcmData.buffer));

    onAudioDataRef.current?.(buffer);
  }, [sampleRate]);

  const startRecording = useCallback(async () => {
    setError(null);
    setDuration(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      streamRef.current = stream;

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      const bufferSize = 4096;
      const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        audioBufferRef.current.push(new Float32Array(inputData));
      };

      source.connect(processor);
      processor.connect(audioContext.destination);

      setIsRecording(true);
      startTimeRef.current = Date.now();

      timerRef.current = window.setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);

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
    sendAccumulatedAudio();

    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (chunkTimerRef.current) {
      clearInterval(chunkTimerRef.current);
      chunkTimerRef.current = null;
    }

    audioBufferRef.current = [];
    setDuration(0);
    setIsRecording(false);
  }, [sendAccumulatedAudio]);

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
