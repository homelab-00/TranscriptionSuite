/**
 * DownloadHub - the single main-process registry of in-flight downloads
 * (GH-318).
 *
 * Every download source reports here: image pulls, the bootstrap log parser,
 * server startup events (model weights, dependency installs), host-side model
 * fetches, the app updater and file exports. The hub owns throttling, speed
 * and ETA derivation, and a short-lived snapshot so a renderer reload
 * mid-download recovers the live state.
 *
 * Deliberately free of any `electron` import: the IPC broadcaster is injected
 * (see main.ts), which keeps this module unit-testable under plain node.
 *
 * A percent is never invented. An item is determinate only when the source
 * supplies bytes (`bytesDone` / `bytesTotal`) or an honest coarse fraction
 * (`percent`, e.g. finished layers or packages); otherwise it renders as an
 * indeterminate bar.
 */

export type DownloadKind =
  | 'server-image'
  | 'sidecar-image'
  | 'server-deps'
  | 'feature-deps'
  | 'model'
  | 'live-model'
  | 'diarization-model'
  | 'alignment-model'
  | 'ggml-model'
  | 'whisper-server'
  | 'app-update'
  | 'export';

export type DownloadStatus = 'active' | 'complete' | 'error' | 'cancelled';

/** Where the bytes are being fetched: by this app, or inside the server process. */
export type DownloadSource = 'app' | 'server';

export interface DownloadItem {
  /** Stable source key, e.g. `server-image:latest`. One running item per id. */
  id: string;
  /** Unique per run of an id - the identity of the history row it leaves behind. */
  runId: string;
  kind: DownloadKind;
  source: DownloadSource;
  label: string;
  detail?: string;
  status: DownloadStatus;
  bytesDone?: number;
  bytesTotal?: number;
  /** 0-100. Only for sources that cannot report bytes (layer / package fraction). */
  percent?: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
  cancellable: boolean;
  error?: string;
  startedAt: number;
  updatedAt: number;
  endedAt?: number;
  /** False where the caller already raises its own, richer failure toast. */
  errorToast: boolean;
}

export type DownloadChange =
  { type: 'upsert'; item: DownloadItem } | { type: 'remove'; runId: string };

export interface DownloadBeginOptions {
  id: string;
  kind: DownloadKind;
  label: string;
  source?: DownloadSource;
  detail?: string;
  /** Invoked by `DownloadHub.cancel(id)`; the source still reports the outcome. */
  cancel?: () => void;
  errorToast?: boolean;
}

export interface DownloadProgress {
  bytesDone?: number;
  bytesTotal?: number;
  percent?: number;
  detail?: string;
  label?: string;
  /** Speed measured by the source itself; overrides the hub's own estimate. */
  bytesPerSecond?: number;
}

export interface DownloadHandle {
  readonly id: string;
  update: (progress: DownloadProgress) => void;
  complete: (detail?: string) => void;
  fail: (error: string) => void;
  cancel: (detail?: string) => void;
  /** Drop the item without a terminal state or a history row (nothing was downloaded). */
  discard: () => void;
}

/** Minimum gap between two progress broadcasts of the same item. */
const BROADCAST_THROTTLE_MS = 250;
/** Minimum gap between two speed samples. */
const SPEED_SAMPLE_MS = 500;
const SPEED_EWMA_ALPHA = 0.3;
/** No ETA before the speed estimate has had time to settle. */
const ETA_MIN_ELAPSED_MS = 3_000;
const ETA_MAX_SECONDS = 24 * 60 * 60;
/** How long an ended item stays in `snapshot()` for a reloading renderer. */
const TERMINAL_RETENTION_MS = 30_000;

interface Entry {
  item: DownloadItem;
  cancel?: () => void;
  lastBroadcastAt: number;
  sampleAt?: number;
  sampleBytes?: number;
  /** True once the source supplied its own speed - the hub stops estimating. */
  externalSpeed: boolean;
}

function finiteNonNegative(value: number | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

export class DownloadHub {
  private readonly now: () => number;
  private broadcaster: ((change: DownloadChange) => void) | null = null;
  /** Running items keyed by source id. */
  private readonly running = new Map<string, Entry>();
  /** Recently ended items keyed by runId. */
  private readonly ended = new Map<string, DownloadItem>();
  private seq = 0;

  constructor(options: { now?: () => number } = {}) {
    this.now = options.now ?? Date.now;
  }

  setBroadcaster(broadcaster: ((change: DownloadChange) => void) | null): void {
    this.broadcaster = broadcaster;
  }

  /** Start tracking a download. Idempotent while a run with this id is active. */
  begin(options: DownloadBeginOptions): DownloadHandle {
    const existing = this.running.get(options.id);
    if (existing) return this.handleFor(existing);

    this.pruneEnded();
    const startedAt = this.now();
    this.seq += 1;
    const entry: Entry = {
      item: {
        id: options.id,
        runId: `${options.id}@${startedAt}.${this.seq}`,
        kind: options.kind,
        source: options.source ?? 'app',
        label: options.label,
        ...(options.detail ? { detail: options.detail } : {}),
        status: 'active',
        cancellable: options.cancel !== undefined,
        startedAt,
        updatedAt: startedAt,
        errorToast: options.errorToast ?? true,
      },
      cancel: options.cancel,
      lastBroadcastAt: Number.NEGATIVE_INFINITY,
      externalSpeed: false,
    };
    this.running.set(options.id, entry);
    this.emit({ type: 'upsert', item: { ...entry.item } });
    return this.handleFor(entry);
  }

  /** Handle for the running item with this id, if any. */
  active(id: string): DownloadHandle | undefined {
    const entry = this.running.get(id);
    return entry ? this.handleFor(entry) : undefined;
  }

  /** Running items plus those that ended recently enough to still matter to a reload. */
  snapshot(): DownloadItem[] {
    this.pruneEnded();
    return [
      ...[...this.running.values()].map((e) => ({ ...e.item })),
      ...[...this.ended.values()].map((item) => ({ ...item })),
    ];
  }

  /** Ask the source to cancel. Returns false when the id is unknown or not cancellable. */
  cancel(id: string): boolean {
    const entry = this.running.get(id);
    if (!entry?.cancel) return false;
    try {
      entry.cancel();
    } catch (err) {
      console.warn(`[DownloadHub] cancel callback for ${id} threw:`, err);
    }
    return true;
  }

  /** Mark every running item of one source as cancelled (e.g. the server stopped). */
  endAllFromSource(source: DownloadSource, reason: string): void {
    for (const entry of [...this.running.values()]) {
      if (entry.item.source === source) this.finish(entry, 'cancelled', { detail: reason });
    }
  }

  private handleFor(entry: Entry): DownloadHandle {
    // Bound to this run: once it ends, or a newer run reuses the id, every
    // call from this handle is a no-op.
    const live = (): boolean => this.running.get(entry.item.id) === entry;
    return {
      id: entry.item.id,
      update: (progress) => {
        if (live()) this.applyProgress(entry, progress);
      },
      complete: (detail) => {
        if (live()) this.finish(entry, 'complete', detail ? { detail } : {});
      },
      fail: (error) => {
        if (live()) this.finish(entry, 'error', { error });
      },
      cancel: (detail) => {
        if (live()) this.finish(entry, 'cancelled', detail ? { detail } : {});
      },
      discard: () => {
        if (!live()) return;
        this.running.delete(entry.item.id);
        this.emit({ type: 'remove', runId: entry.item.runId });
      },
    };
  }

  private applyProgress(entry: Entry, progress: DownloadProgress): void {
    const { item } = entry;
    const now = this.now();
    let urgent = false;

    if (progress.label !== undefined && progress.label !== item.label) {
      item.label = progress.label;
      urgent = true;
    }
    if (progress.detail !== undefined) item.detail = progress.detail;

    const bytesTotal = finiteNonNegative(progress.bytesTotal);
    if (bytesTotal !== undefined && bytesTotal > 0) item.bytesTotal = bytesTotal;

    const bytesDone = finiteNonNegative(progress.bytesDone);
    if (bytesDone !== undefined) {
      item.bytesDone = bytesDone;
      if (!entry.externalSpeed) this.sampleSpeed(entry, bytesDone, now);
    }

    const percent = finiteNonNegative(progress.percent);
    if (percent !== undefined) item.percent = Math.min(100, percent);

    const externalSpeed = finiteNonNegative(progress.bytesPerSecond);
    if (externalSpeed !== undefined) {
      entry.externalSpeed = true;
      item.bytesPerSecond = externalSpeed;
    }

    item.etaSeconds = this.estimateEta(item, now);
    item.updatedAt = now;

    if (urgent || now - entry.lastBroadcastAt >= BROADCAST_THROTTLE_MS) {
      entry.lastBroadcastAt = now;
      this.emit({ type: 'upsert', item: { ...item } });
    }
  }

  private sampleSpeed(entry: Entry, bytesDone: number, now: number): void {
    // The first byte count is only a baseline: a resumed download can report
    // a large starting value that says nothing about the current speed.
    if (entry.sampleAt === undefined || entry.sampleBytes === undefined) {
      entry.sampleAt = now;
      entry.sampleBytes = bytesDone;
      return;
    }
    const elapsedMs = now - entry.sampleAt;
    if (elapsedMs < SPEED_SAMPLE_MS) return;
    const instant = Math.max(0, bytesDone - entry.sampleBytes) / (elapsedMs / 1000);
    const previous = entry.item.bytesPerSecond;
    entry.item.bytesPerSecond =
      previous === undefined
        ? instant
        : SPEED_EWMA_ALPHA * instant + (1 - SPEED_EWMA_ALPHA) * previous;
    entry.sampleAt = now;
    entry.sampleBytes = bytesDone;
  }

  private estimateEta(item: DownloadItem, now: number): number | undefined {
    const { bytesDone, bytesTotal, bytesPerSecond } = item;
    if (bytesDone === undefined || bytesTotal === undefined) return undefined;
    if (bytesPerSecond === undefined || bytesPerSecond <= 0) return undefined;
    if (now - item.startedAt < ETA_MIN_ELAPSED_MS) return undefined;
    const eta = Math.max(0, bytesTotal - bytesDone) / bytesPerSecond;
    return eta < ETA_MAX_SECONDS ? Math.round(eta) : undefined;
  }

  private finish(
    entry: Entry,
    status: Exclude<DownloadStatus, 'active'>,
    patch: { detail?: string; error?: string },
  ): void {
    const now = this.now();
    this.running.delete(entry.item.id);
    const item: DownloadItem = {
      ...entry.item,
      ...patch,
      status,
      cancellable: false,
      updatedAt: now,
      endedAt: now,
    };
    delete item.etaSeconds;
    delete item.bytesPerSecond;
    this.ended.set(item.runId, item);
    this.emit({ type: 'upsert', item: { ...item } });
  }

  private pruneEnded(): void {
    const cutoff = this.now() - TERMINAL_RETENTION_MS;
    for (const [runId, item] of this.ended) {
      if ((item.endedAt ?? 0) < cutoff) this.ended.delete(runId);
    }
  }

  private emit(change: DownloadChange): void {
    if (!this.broadcaster) return;
    try {
      this.broadcaster(change);
    } catch (err) {
      // A broadcast failure (window gone mid-quit) must never break a download.
      console.warn('[DownloadHub] broadcast failed:', err);
    }
  }
}

/** Process-wide hub. main.ts injects the IPC broadcaster at startup. */
export const downloadHub = new DownloadHub();
