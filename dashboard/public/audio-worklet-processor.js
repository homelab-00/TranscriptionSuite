/**
 * AudioWorklet processor — runs in the audio rendering thread.
 *
 * Collects Float32 samples from the microphone, resamples from the browser's
 * native sample rate (typically 48kHz) to 16kHz, converts to Int16 PCM,
 * and posts chunks to the main thread at ~100ms intervals.
 *
 * Registered as 'pcm-processor'.
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    /** @type {Float32Array[]} */
    this._buffer = [];
    this._bufferLength = 0;

    // Receive target sample rate from main thread
    this._targetRate = 16000;
    this._sourceRate = sampleRate; // AudioWorklet global `sampleRate`
    this._ratio = this._sourceRate / this._targetRate;

    // Emit chunks of ~100ms at 16kHz = 1600 samples
    this._chunkSize = 1600;
  }

  /**
   * @param {Float32Array[][]} inputs
   * @param {Float32Array[][]} _outputs
   * @param {Record<string, Float32Array>} _parameters
   * @returns {boolean}
   */
  process(inputs, _outputs, _parameters) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) return true;

    // Take channel 0 (mono)
    const samples = input[0];
    this._buffer.push(new Float32Array(samples));
    this._bufferLength += samples.length;

    // Check if we have enough samples for one chunk at the target rate
    const neededSourceSamples = this._chunkSize * this._ratio;
    while (this._bufferLength >= neededSourceSamples) {
      // Concatenate buffered samples
      const full = this._concatenate(this._buffer, this._bufferLength);
      const consumeCount = Math.ceil(this._chunkSize * this._ratio);

      // Downsample the consumed portion
      const sourceSlice = full.subarray(0, consumeCount);
      const downsampled = this._downsample(sourceSlice, this._ratio);

      // Convert float32 [-1,1] to int16
      const int16 = this._floatToInt16(downsampled);

      // Post to main thread
      this.port.postMessage({ type: 'audio', data: int16.buffer }, [int16.buffer]);

      // Keep remainder in buffer
      const remainder = full.subarray(consumeCount);
      this._buffer = remainder.length > 0 ? [new Float32Array(remainder)] : [];
      this._bufferLength = remainder.length;
    }

    return true;
  }

  /**
   * Simple linear interpolation downsample.
   * @param {Float32Array} samples
   * @param {number} ratio - source/target sample rate ratio
   * @returns {Float32Array}
   */
  _downsample(samples, ratio) {
    const outLen = Math.floor(samples.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcIdx = i * ratio;
      const lo = Math.floor(srcIdx);
      const hi = Math.min(lo + 1, samples.length - 1);
      const frac = srcIdx - lo;
      out[i] = samples[lo] * (1 - frac) + samples[hi] * frac;
    }
    return out;
  }

  /**
   * @param {Float32Array} float32
   * @returns {Int16Array}
   */
  _floatToInt16(float32) {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
  }

  /**
   * @param {Float32Array[]} buffers
   * @param {number} totalLength
   * @returns {Float32Array}
   */
  _concatenate(buffers, totalLength) {
    const result = new Float32Array(totalLength);
    let offset = 0;
    for (const buf of buffers) {
      result.set(buf, offset);
      offset += buf.length;
    }
    return result;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
