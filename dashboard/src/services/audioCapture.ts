/**
 * AudioCapture — manages microphone/system audio capture via Web Audio API.
 *
 * Creates an AudioContext + AudioWorklet pipeline that:
 * 1. Captures audio from a selected input device
 * 2. Resamples to a target PCM rate (16kHz/24kHz) via the AudioWorklet processor
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

import { loopbackOwner } from './loopbackOwner';

export type AudioChunkCallback = (pcmInt16: Int16Array) => void;

/**
 * Thrown when stop() lands while start() is still awaiting (device acquire,
 * getUserMedia, worklet load). Callers treat it as a clean no-op — the stop
 * already put the UI in its final state (GH-230). `name` is 'AbortError' so
 * generic handlers can filter it without importing this class.
 */
export class AudioCaptureAbortedError extends Error {
  constructor() {
    super('Audio capture start aborted by stop()');
    this.name = 'AbortError';
  }
}

export interface AudioCaptureOptions {
  /** Device ID from navigator.mediaDevices.enumerateDevices() */
  deviceId?: string;
  /** Whether to capture system audio instead of microphone */
  systemAudio?: boolean;
  /**
   * When set, the Linux monitor-source path is used: acquire the loopback
   * module for this sink via loopbackOwner (GH-230 — the capture owns the
   * module lifetime), find the virtual input by label, and capture via
   * getUserMedia (no xdg-desktop-portal picker).
   *
   * If unset while systemAudio=true, the Windows/macOS getDisplayMedia path
   * is used instead.
   */
  monitorSinkName?: string;
  /**
   * When systemAudio is also set, capture the microphone alongside the
   * system audio and mix both into the same stream (e.g. narrating over a
   * call). Ignored for plain microphone capture.
   */
  mixMicWithSystem?: boolean;
  /** Device ID for the mixed-in microphone. Falls back to the default mic. */
  mixMicDeviceId?: string;
  /** Target PCM sample rate emitted by the worklet (e.g. 16000 or 24000) */
  targetSampleRateHz?: number;
}

export class AudioCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  /** Secondary mic stream mixed in alongside system audio (mixMicWithSystem). */
  private secondaryStream: MediaStream | null = null;
  private secondarySourceNode: MediaStreamAudioSourceNode | null = null;
  private gainNode: GainNode | null = null;
  /**
   * Fixed-at-1.0 gain stage for the mixed-in mic (mixMicWithSystem). Kept
   * separate from `gainNode` so the "Capture Gain" slider — which scales
   * `gainNode` and is documented/intended as a system-audio-only control —
   * does not also amplify (and clip) the user's own voice.
   */
  private micGainNode: GainNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private analyserNode: AnalyserNode | null = null;
  private onChunk: AudioChunkCallback;
  private _muted = false;
  private _gain = 1;
  /**
   * True while THIS capture holds a loopbackOwner acquisition (GH-230).
   * Flag-based so the defensive stop() at the top of start() on a fresh
   * instance never releases another capture's hold, and double stop() is safe.
   */
  private holdsLoopback = false;
  /**
   * Bumped by every stop(). start() snapshots it after its own defensive
   * stop() and re-checks after every await — an external stop() landing
   * mid-start would otherwise be a silent no-op (nothing built yet), letting
   * the orphaned start() run to completion holding the loopback module
   * forever and pumping audio into a dead session (GH-230 review finding).
   */
  private stopEpoch = 0;

  constructor(onChunk: AudioChunkCallback) {
    this.onChunk = onChunk;
  }

  /** Start capturing audio from the specified device. */
  async start(options: AudioCaptureOptions = {}): Promise<void> {
    // Stop any existing capture
    this.stop();
    // Snapshot AFTER the defensive stop above — any later mismatch means an
    // external stop() landed while we were awaiting.
    const epoch = this.stopEpoch;

    try {
      // 1. Get media stream — microphone or system audio
      if (options.systemAudio && options.monitorSinkName) {
        // Linux path: acquire the virtual input created from the selected
        // sink's PulseAudio/PipeWire monitor source via module-remap-source
        // (loopbackOwner owns create/remove — GH-230), then find it by label
        // and capture with plain getUserMedia — no xdg-desktop-portal, no
        // screen picker.
        const { label } = await loopbackOwner.acquire(options.monitorSinkName);
        // Take the hold BEFORE the abort check so the catch-path stop()
        // releases it exactly once when an external stop() raced the acquire.
        this.holdsLoopback = true;
        this.assertNotStopped(epoch);
        // The module may have been created just now — allow longer than the
        // generic default for the virtual device to reach enumerateDevices.
        const deviceId = await AudioCapture.waitForDevice(label, 7000);
        this.assertNotStopped(epoch);
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: { exact: deviceId },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            channelCount: 1,
          },
        });
      } else if (options.systemAudio) {
        // Windows / macOS path: getDisplayMedia with loopback handler.
        // The main process registers setDisplayMediaRequestHandler with
        // { audio: 'loopback' } before we reach here.
        const displayStream = await navigator.mediaDevices.getDisplayMedia({
          audio: true,
          video: true, // video required by spec; tracks dropped immediately
        });
        displayStream.getVideoTracks().forEach((t) => t.stop());
        this.stream = displayStream;
      } else {
        // Standard microphone capture
        const constraints: MediaStreamConstraints = {
          audio: {
            ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            sampleRate: options.targetSampleRateHz ?? 16000, // Hint — browser may ignore
            channelCount: 1,
          },
        };
        this.stream = await navigator.mediaDevices.getUserMedia(constraints);
      }
      // The stream is assigned before this check so the catch-path stop()
      // can release its tracks when the start was aborted mid-getUserMedia.
      this.assertNotStopped(epoch);

      // 1b. Also acquire the mixed-in microphone now, alongside the primary
      //     stream and before anything downstream exists. This getUserMedia
      //     call is an await of unbounded duration (OS permission prompt,
      //     NotReadableError if the device is busy, NotFoundError on a
      //     system-audio-only box with no mic) — acquiring it here means a
      //     failure fails the whole start() cleanly, before the worklet is
      //     wired up and streaming, instead of tearing down an otherwise-
      //     healthy, already-live session for want of an optional extra.
      if (options.systemAudio && options.mixMicWithSystem) {
        this.secondaryStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            ...(options.mixMicDeviceId ? { deviceId: { exact: options.mixMicDeviceId } } : {}),
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            channelCount: 1,
          },
        });
        this.assertNotStopped(epoch);
      }

      // 2. Create AudioContext
      this.ctx = new AudioContext({
        sampleRate: this.stream.getAudioTracks()[0].getSettings().sampleRate || 48000,
      });

      // 3. Register the AudioWorklet processor
      await this.ctx.audioWorklet.addModule('./audio-worklet-processor.js');
      this.assertNotStopped(epoch);

      // 4. Create nodes
      this.sourceNode = this.ctx.createMediaStreamSource(this.stream);

      this.gainNode = this.ctx.createGain();
      this.gainNode.gain.value = this._gain;

      this.analyserNode = this.ctx.createAnalyser();
      this.analyserNode.fftSize = 2048;
      this.analyserNode.smoothingTimeConstant = 0.8;

      this.workletNode = new AudioWorkletNode(this.ctx, 'pcm-processor', {
        processorOptions: {
          targetSampleRateHz: options.targetSampleRateHz ?? 16000,
        },
      });

      if (this.secondaryStream) {
        this.secondarySourceNode = this.ctx.createMediaStreamSource(this.secondaryStream);
        // Fixed at 1.0, independent of `gainNode` and the user's Capture
        // Gain slider — see the micGainNode field comment.
        this.micGainNode = this.ctx.createGain();
        this.micGainNode.gain.value = 1;
      }

      // 5. Handle PCM chunks from the worklet
      this.workletNode.port.onmessage = (ev: MessageEvent) => {
        if (ev.data?.type === 'audio' && !this._muted) {
          const int16 = new Int16Array(ev.data.data);
          this.onChunk(int16);
        }
      };

      // 6. Wire the graph:
      //    source → gain ─────────┐
      //                            ├→ analyser → worklet → (silence — worklet has no output)
      //    secondarySource → micGain ┘
      //    Both gain stages feed the analyser, which sums them — kept
      //    separate so the Capture Gain slider (which scales `gainNode`,
      //    see setGain) never touches the mixed-in mic. mute()/unmute()
      //    zero and restore both stages together.
      this.sourceNode.connect(this.gainNode);
      this.secondarySourceNode?.connect(this.micGainNode!);
      this.gainNode.connect(this.analyserNode);
      this.micGainNode?.connect(this.analyserNode);
      this.analyserNode.connect(this.workletNode);
      // Don't connect worklet to destination — we don't want to play back the mic
    } catch (err) {
      // A partial start must not leak: stop() tears down whatever was already
      // grabbed — stream tracks, the AudioContext, and the loopback hold
      // (GH-230: waitForDevice timeout / getUserMedia denial / addModule
      // failure previously stranded the pactl module and kept the KDE
      // microphone indicator lit).
      this.stop();
      throw err;
    }
  }

  /** Stop capturing and release all resources. */
  stop(): void {
    // Abort any start() still in flight (checked after each of its awaits).
    this.stopEpoch++;
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.secondarySourceNode) {
      this.secondarySourceNode.disconnect();
      this.secondarySourceNode = null;
    }
    if (this.secondaryStream) {
      this.secondaryStream.getTracks().forEach((t) => t.stop());
      this.secondaryStream = null;
    }
    if (this.micGainNode) {
      this.micGainNode.disconnect();
      this.micGainNode = null;
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
    this.releaseLoopback();
    this._muted = false;
  }

  /** Drop this capture's loopbackOwner hold exactly once (GH-230). */
  private releaseLoopback(): void {
    if (this.holdsLoopback) {
      this.holdsLoopback = false;
      loopbackOwner.release();
    }
  }

  /** Throw AbortError when an external stop() landed since `epoch`. */
  private assertNotStopped(epoch: number): void {
    if (epoch !== this.stopEpoch) {
      throw new AudioCaptureAbortedError();
    }
  }

  /** Mute — stops sending audio chunks and silences the visualiser. */
  mute(): void {
    this._muted = true;
    if (this.gainNode) this.gainNode.gain.value = 0;
    // micGainNode feeds the analyser through a path independent of
    // gainNode (see the field comment) — it must be zeroed too, or the
    // mixed-in mic keeps animating the visualiser while "muted".
    if (this.micGainNode) this.micGainNode.gain.value = 0;
  }

  /** Unmute — resumes sending audio chunks and restores the visualiser. */
  unmute(): void {
    this._muted = false;
    if (this.gainNode) this.gainNode.gain.value = this._gain;
    if (this.micGainNode) this.micGainNode.gain.value = 1;
  }

  /**
   * Set the capture gain (amplification).
   * Values >1 boost quiet sources; values <1 attenuate.
   * Clamped to [0, 10].  The value is remembered and re-applied on unmute.
   */
  setGain(value: number): void {
    this._gain = Math.max(0, Math.min(10, value));
    if (this.gainNode && !this._muted) {
      this.gainNode.gain.value = this._gain;
    }
  }

  /** Current capture gain multiplier. */
  get gain(): number {
    return this._gain;
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

  /**
   * Poll enumerateDevices until a device whose label contains `substring`
   * appears.  Returns its deviceId.  Throws after `timeoutMs`.
   */
  private static async waitForDevice(substring: string, timeoutMs = 3000): Promise<string> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const match = devices.find((d) => d.kind === 'audioinput' && d.label.includes(substring));
      if (match) return match.deviceId;
      await new Promise((r) => setTimeout(r, 200));
    }
    throw new Error(`System audio device "${substring}" did not appear in time`);
  }
}
