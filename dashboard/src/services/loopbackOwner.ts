/**
 * loopbackOwner — single renderer-side owner of the Linux PulseAudio/PipeWire
 * loopback module lifecycle (GH-230).
 *
 * The pactl `module-remap-source` module that backs system-audio capture holds
 * an uncorked recording stream ALL BY ITSELF — a leaked module keeps the KDE
 * "microphone in use" indicator lit forever, even after the getUserMedia
 * stream is stopped. Before GH-230 the module was created by SessionView ahead
 * of the session and removed by three UI handlers; every teardown that
 * bypassed those handlers (WS drop, server error, tray stop, reconnect)
 * leaked it.
 *
 * Ownership inversion: the capture that consumes the module owns its
 * lifetime. AudioCapture calls acquire() before opening the device and
 * release() when it stops. Release is deferred by a short grace window so a
 * quick WebSocket reconnect or a live-mode host retarget reuses the module
 * instead of racing a pactl unload/reload cycle; a generation token makes any
 * stale grace timer a no-op after a newer acquire.
 *
 * All IPC (create + remove) flows through one internal promise chain so the
 * two operations can never interleave.
 */

export const LOOPBACK_DEVICE_LABEL = 'TranscriptionSuite_Loopback';
export const LOOPBACK_RELEASE_GRACE_MS = 5000;

type VolumeListener = (pct: number | null) => void;

interface AcquireResult {
  /** Device label AudioCapture polls enumerateDevices for. */
  label: string;
  /** Effective source volume (diagnostic), null when unknown. */
  volumePct: number | null;
}

class LoopbackOwner {
  /** Number of captures currently holding the module. */
  private holdCount = 0;
  /** Whether the module is believed to exist in the audio server. */
  private moduleActive = false;
  private activeSinkName: string | null = null;
  /** Bumped on every acquire — invalidates stale grace timers. */
  private generation = 0;
  private releaseTimer: ReturnType<typeof setTimeout> | null = null;
  /** Serializes create/remove IPC so pactl operations never interleave. */
  private ipcChain: Promise<unknown> = Promise.resolve();
  private lastVolumePct: number | null = null;
  private volumeListeners = new Set<VolumeListener>();

  /** Hold the loopback module for `sinkName`, creating it if needed. */
  async acquire(sinkName: string): Promise<AcquireResult> {
    if (this.releaseTimer !== null) {
      clearTimeout(this.releaseTimer);
      this.releaseTimer = null;
    }
    this.generation++;
    const needsCreate = !this.moduleActive || this.activeSinkName !== sinkName;
    this.holdCount++;
    if (needsCreate) {
      const create = window.electronAPI?.audio?.createMonitorLoopback;
      if (!create) {
        this.holdCount--;
        throw new Error('Monitor loopback IPC unavailable');
      }
      try {
        // Main unloads any previous module before loading the new one, so a
        // sink switch during grace is a plain re-create.
        const result = await this.enqueue(() => create(sinkName));
        this.moduleActive = true;
        this.activeSinkName = sinkName;
        this.notifyVolume(result?.volumePct ?? null);
      } catch (err) {
        // Main nulls its tracked id before loading — a failed load means no
        // module exists, so the next acquire retries from a clean slate.
        this.holdCount--;
        this.moduleActive = false;
        this.activeSinkName = null;
        throw err;
      }
    }
    return { label: LOOPBACK_DEVICE_LABEL, volumePct: this.lastVolumePct };
  }

  /**
   * Drop one hold. When the last hold drops, schedule the module unload after
   * the grace window (a re-acquire within the window cancels it).
   */
  release(): void {
    if (this.holdCount === 0) return;
    this.holdCount--;
    if (this.holdCount > 0 || !this.moduleActive) return;

    const gen = this.generation;
    if (this.releaseTimer !== null) clearTimeout(this.releaseTimer);
    this.releaseTimer = setTimeout(() => {
      this.releaseTimer = null;
      // A newer acquire owns the module now — this timer is stale.
      if (gen !== this.generation) return;
      this.moduleActive = false;
      this.activeSinkName = null;
      const remove = window.electronAPI?.audio?.removeMonitorLoopback;
      if (remove) {
        void this.enqueue(() => remove()).catch(() => {
          // Best-effort: main's handler is idempotent and the will-quit /
          // shutdown safety nets sweep anything that slips through.
        });
      }
      this.notifyVolume(null);
    }, LOOPBACK_RELEASE_GRACE_MS);
  }

  /**
   * Subscribe to the diagnostic volume readout: pct after a create, null when
   * a scheduled removal actually executes. Returns an unsubscribe function.
   */
  subscribeVolumePct(cb: VolumeListener): () => void {
    this.volumeListeners.add(cb);
    return () => {
      this.volumeListeners.delete(cb);
    };
  }

  /** Test-only: reset singleton state between tests. */
  _resetForTests(): void {
    if (this.releaseTimer !== null) {
      clearTimeout(this.releaseTimer);
      this.releaseTimer = null;
    }
    this.holdCount = 0;
    this.moduleActive = false;
    this.activeSinkName = null;
    this.generation = 0;
    this.ipcChain = Promise.resolve();
    this.lastVolumePct = null;
    this.volumeListeners.clear();
  }

  private enqueue<T>(op: () => Promise<T>): Promise<T> {
    const run = this.ipcChain.then(op, op);
    this.ipcChain = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }

  private notifyVolume(pct: number | null): void {
    this.lastVolumePct = pct;
    for (const cb of this.volumeListeners) cb(pct);
  }
}

export const loopbackOwner = new LoopbackOwner();
