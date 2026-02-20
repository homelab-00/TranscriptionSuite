/**
 * AudioCapture — manages microphone/system audio capture via Web Audio API.
 *
 * Creates an AudioContext + AudioWorklet pipeline that:
 * 1. Captures audio from a selected input device
 * 2. Resamples to 16kHz PCM Int16 via the AudioWorklet processor
 * 3. Provides an AnalyserNode for real-time frequency visualization
 * 4. Delivers PCM chunks via a callback for WebSocket streaming
 *
 * Usage:
 *   const capture = new AudioCapture(chunk => socket.sendAudio(chunk));
 *   await capture.start(deviceId);
 *   capture.mute();
 *   capture.unmute();
 *   capture.stop();
 */

export type AudioChunkCallback = (pcmInt16: Int16Array) => void;

export interface AudioCaptureOptions {
  /** Device ID from navigator.mediaDevices.enumerateDevices() */
  deviceId?: string;
  /** Whether to capture system audio instead of microphone */
  systemAudio?: boolean;
  /** Desktop source ID from desktopCapturer (required when systemAudio=true) */
  desktopSourceId?: string;
}

export class AudioCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private gainNode: GainNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private analyserNode: AnalyserNode | null = null;
  private onChunk: AudioChunkCallback;
  private _muted = false;

  constructor(onChunk: AudioChunkCallback) {
    this.onChunk = onChunk;
  }

  /** Start capturing audio from the specified device. */
  async start(options: AudioCaptureOptions = {}): Promise<void> {
    // Stop any existing capture
    this.stop();

    // 1. Get media stream — microphone or system audio
    let constraints: MediaStreamConstraints;

    if (options.systemAudio && options.desktopSourceId) {
      // System audio capture via Electron desktopCapturer
      // Note: 'loopback' audio requires Chromium/Electron flags on Linux
      constraints = {
        audio: {
          mandatory: {
            chromeMediaSource: 'desktop',
            chromeMediaSourceId: options.desktopSourceId,
          },
        } as MediaTrackConstraints,
        video: {
          mandatory: {
            chromeMediaSource: 'desktop',
            chromeMediaSourceId: options.desktopSourceId,
            maxWidth: 1,
            maxHeight: 1,
            maxFrameRate: 1,
          },
        } as MediaTrackConstraints,
      };
    } else {
      // Standard microphone capture
      constraints = {
        audio: {
          ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          sampleRate: 16000, // Hint — browser may ignore
          channelCount: 1,
        },
      };
    }
    this.stream = await navigator.mediaDevices.getUserMedia(constraints);

    // For system audio, we only need the audio track
    if (options.systemAudio) {
      this.stream.getVideoTracks().forEach((t) => t.stop());
    }

    // 2. Create AudioContext
    this.ctx = new AudioContext({
      sampleRate: this.stream.getAudioTracks()[0].getSettings().sampleRate || 48000,
    });

    // 3. Register the AudioWorklet processor
    await this.ctx.audioWorklet.addModule('./audio-worklet-processor.js');

    // 4. Create nodes
    this.sourceNode = this.ctx.createMediaStreamSource(this.stream);

    this.gainNode = this.ctx.createGain();
    this.gainNode.gain.value = 1;

    this.analyserNode = this.ctx.createAnalyser();
    this.analyserNode.fftSize = 2048;
    this.analyserNode.smoothingTimeConstant = 0.8;

    this.workletNode = new AudioWorkletNode(this.ctx, 'pcm-processor');

    // 5. Handle PCM chunks from the worklet
    this.workletNode.port.onmessage = (ev: MessageEvent) => {
      if (ev.data?.type === 'audio' && !this._muted) {
        const int16 = new Int16Array(ev.data.data);
        this.onChunk(int16);
      }
    };

    // 6. Wire the graph:
    //    source → gain → analyser → worklet → (silence — worklet has no output)
    //    Gain is set to 0 when muted so the visualiser also flatlines.
    this.sourceNode.connect(this.gainNode);
    this.gainNode.connect(this.analyserNode);
    this.analyserNode.connect(this.workletNode);
    // Don't connect worklet to destination — we don't want to play back the mic
  }

  /** Stop capturing and release all resources. */
  stop(): void {
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.gainNode) {
      this.gainNode.disconnect();
      this.gainNode = null;
    }
    if (this.analyserNode) {
      this.analyserNode.disconnect();
      this.analyserNode = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.ctx) {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
    this._muted = false;
  }

  /** Mute — stops sending audio chunks and silences the visualiser. */
  mute(): void {
    this._muted = true;
    if (this.gainNode) this.gainNode.gain.value = 0;
  }

  /** Unmute — resumes sending audio chunks and restores the visualiser. */
  unmute(): void {
    this._muted = false;
    if (this.gainNode) this.gainNode.gain.value = 1;
  }

  get isMuted(): boolean {
    return this._muted;
  }

  /** The AnalyserNode for visualization (available after start()). */
  get analyser(): AnalyserNode | null {
    return this.analyserNode;
  }

  /** Whether capture is currently active. */
  get isCapturing(): boolean {
    return this.ctx !== null && this.ctx.state === 'running';
  }

  /** The actual sample rate the browser chose. */
  get sampleRate(): number {
    return this.ctx?.sampleRate ?? 0;
  }
}
