/**
 * WatcherManager — cross-platform folder watcher for auto-processing audio files.
 *
 * Follows the TrayManager pattern: class with a `getWindow` callback.
 * Designed to run in the Electron main process.
 *
 * Features:
 *  - chokidar v5 (ESM) for inotify/FSEvents/ReadDirectoryChanges
 *  - chokidar `awaitWriteFinish` holds `add` until a file has stopped growing (GH-311)
 *  - Audio extension whitelist (7 extensions)
 *  - 3-second event batching for bursts of new files
 *  - xxhash fingerprint ledger (atomic write) recorded only after the renderer confirms an import (GH-311)
 *  - Depth 0 — watches only the top-level directory, not sub-directories
 */

import path from 'path';
import fs from 'fs';
import { app, BrowserWindow } from 'electron';
import { watch as chokidarWatch, type FSWatcher } from 'chokidar';
import xxhash, { type XXHashAPI } from 'xxhash-wasm';

// ─── Constants ───────────────────────────────────────────────────────────────

const AUDIO_EXTS = new Set(['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.webm', '.opus']);
const BATCH_DELAY_MS = 3_000;

/**
 * chokidar polls the size of a newly seen file and holds its `add` event until
 * the size has been unchanged for `stabilityThreshold` ms (GH-311). A file that
 * is still being copied or written (ffmpeg segments, slow disks, network
 * shares) therefore waits instead of being rejected. There is no upper bound:
 * a file that keeps growing keeps waiting.
 */
const AWAIT_WRITE_FINISH = { stabilityThreshold: 5_000, pollInterval: 500 };

const FINGERPRINT_SAMPLE_BYTES = 64 * 1024; // 64 KB — fast even for multi-GB files

// ─── Types ───────────────────────────────────────────────────────────────────

export type WatchType = 'session' | 'notebook';

export type FileSkipReason = 'empty' | 'unreadable' | 'already-imported' | 'already-queued';

export interface FileSkippedPayload {
  type: WatchType;
  path: string;
  reason: FileSkipReason;
}

export interface FileDetectedMeta {
  path: string;
  /** ISO timestamp — birthtime if available, mtime otherwise */
  createdAt: string;
}

export interface FilesDetectedPayload {
  type: WatchType;
  files: string[];
  count: number;
  fileMeta: FileDetectedMeta[];
}

export type ImportOutcome = 'imported' | 'failed' | 'dropped';

export interface ImportOutcomePayload {
  type: WatchType;
  path: string;
  outcome: ImportOutcome;
}

// ─── WatcherManager ──────────────────────────────────────────────────────────

export class WatcherManager {
  private getWindow: () => BrowserWindow | null;

  // Session watcher
  private sessionWatcher: FSWatcher | null = null;
  private sessionWatcherPath = '';
  private sessionLedger = new Set<string>();
  private sessionLedgerPath: string;
  private sessionBatchTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionBatch: string[] = [];
  /** Dispatched to the renderer but not yet acknowledged: path -> fingerprint (GH-311) */
  private sessionInFlight = new Map<string, string>();

  // Notebook watcher
  private notebookWatcher: FSWatcher | null = null;
  private notebookWatcherPath = '';
  private notebookLedger = new Set<string>();
  private notebookLedgerPath: string;
  private notebookBatchTimer: ReturnType<typeof setTimeout> | null = null;
  private notebookBatch: string[] = [];
  /** Dispatched to the renderer but not yet acknowledged: path -> fingerprint (GH-311) */
  private notebookInFlight = new Map<string, string>();

  // xxhash-wasm (initialized once asynchronously)
  private hasher: XXHashAPI | null = null;
  private hasherReady: Promise<void>;

  constructor(getWindow: () => BrowserWindow | null) {
    this.getWindow = getWindow;

    const userData = app.getPath('userData');
    this.sessionLedgerPath = path.join(userData, 'watch-ledger-session.json');
    this.notebookLedgerPath = path.join(userData, 'watch-ledger-notebook.json');

    // Initialize WASM hasher and load the session ledger once ready
    this.hasherReady = this.initHasher();
  }

  // ─── Public API ────────────────────────────────────────────────────────────

  async startSessionWatcher(folderPath: string): Promise<void> {
    await this.hasherReady;

    if (this.sessionWatcher) {
      await this.stopSessionWatcher();
    }

    // Duplicate-folder guard: refuse if same path as notebook watcher
    if (this.notebookWatcher && this.notebookWatcherPath === folderPath) {
      throw new Error('Session watch folder cannot be the same as the notebook watch folder.');
    }

    this.sessionWatcherPath = folderPath;
    this.loadLedger('session');

    this.sessionWatcher = chokidarWatch(folderPath, {
      depth: 0, // top-level directory only
      ignoreInitial: true, // don't fire on existing files
      persistent: true,
      awaitWriteFinish: AWAIT_WRITE_FINISH,
    });

    this.sessionWatcher.on('add', (filePath: string) => {
      const ext = path.extname(filePath).toLowerCase();
      if (!AUDIO_EXTS.has(ext)) return;
      // Guard + fingerprint check (chokidar already waited for writes to finish)
      this.handleNewFile(filePath, 'session').catch((err) => {
        console.warn('[WatcherManager] Error processing file:', filePath, err);
      });
    });

    this.sessionWatcher.on('error', (err) => {
      console.error('[WatcherManager] Session watcher error:', err);
    });

    console.log('[WatcherManager] Session watcher started:', folderPath);
  }

  async stopSessionWatcher(): Promise<void> {
    if (this.sessionBatchTimer) {
      clearTimeout(this.sessionBatchTimer);
      this.sessionBatchTimer = null;
    }
    this.sessionBatch = [];
    // Forget batched and dispatched-but-unacknowledged files alike: after a
    // renderer reload nothing will ever acknowledge them, and an ack that does
    // still arrive re-fingerprints the file (GH-311).
    this.sessionInFlight.clear();

    if (this.sessionWatcher) {
      await this.sessionWatcher.close();
      this.sessionWatcher = null;
    }
    this.sessionWatcherPath = '';

    console.log('[WatcherManager] Session watcher stopped.');
  }

  clearSessionLedger(): void {
    this.sessionLedger.clear();
    this.sessionInFlight.clear();
    this.saveLedger('session');
    console.log('[WatcherManager] Session ledger cleared.');
  }

  // ─── Notebook watcher ──────────────────────────────────────────────────────

  async startNotebookWatcher(folderPath: string): Promise<void> {
    await this.hasherReady;

    if (this.notebookWatcher) {
      await this.stopNotebookWatcher();
    }

    // Duplicate-folder guard: refuse if same path as session watcher
    if (this.sessionWatcher && this.sessionWatcherPath === folderPath) {
      throw new Error('Notebook watch folder cannot be the same as the session watch folder.');
    }

    this.notebookWatcherPath = folderPath;
    this.loadLedger('notebook');

    this.notebookWatcher = chokidarWatch(folderPath, {
      depth: 0,
      ignoreInitial: true,
      persistent: true,
      awaitWriteFinish: AWAIT_WRITE_FINISH,
    });

    this.notebookWatcher.on('add', (filePath: string) => {
      const ext = path.extname(filePath).toLowerCase();
      if (!AUDIO_EXTS.has(ext)) return;
      this.handleNewFile(filePath, 'notebook').catch((err) => {
        console.warn('[WatcherManager] Error processing notebook file:', filePath, err);
      });
    });

    this.notebookWatcher.on('error', (err) => {
      console.error('[WatcherManager] Notebook watcher error:', err);
    });

    console.log('[WatcherManager] Notebook watcher started:', folderPath);
  }

  async stopNotebookWatcher(): Promise<void> {
    if (this.notebookBatchTimer) {
      clearTimeout(this.notebookBatchTimer);
      this.notebookBatchTimer = null;
    }
    this.notebookBatch = [];
    // Forget batched and dispatched-but-unacknowledged files alike: after a
    // renderer reload nothing will ever acknowledge them, and an ack that does
    // still arrive re-fingerprints the file (GH-311).
    this.notebookInFlight.clear();

    if (this.notebookWatcher) {
      await this.notebookWatcher.close();
      this.notebookWatcher = null;
    }
    this.notebookWatcherPath = '';

    console.log('[WatcherManager] Notebook watcher stopped.');
  }

  clearNotebookLedger(): void {
    this.notebookLedger.clear();
    this.notebookInFlight.clear();
    this.saveLedger('notebook');
    console.log('[WatcherManager] Notebook ledger cleared.');
  }

  /**
   * Renderer acknowledgement for a dispatched file (GH-311). The fingerprint is
   * written to the ledger only on 'imported'; any other outcome forgets the
   * file so that putting it back into the folder imports it again.
   */
  reportImportOutcome(payload: ImportOutcomePayload): void {
    const { type, path: filePath, outcome } = payload;
    const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
    const known = inFlight.get(filePath);
    inFlight.delete(filePath);

    if (outcome !== 'imported') {
      console.log(`[WatcherManager] ${type} file ${outcome}, not recorded:`, filePath);
      return;
    }

    // A job retried from the queue after a failure is no longer in flight;
    // re-fingerprint the file so its eventual success is still recorded.
    const fingerprint = known ?? this.computeFingerprint(filePath);
    if (!fingerprint) {
      console.warn(
        '[WatcherManager] Imported file could not be fingerprinted, not recorded:',
        filePath,
      );
      return;
    }
    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    ledger.add(fingerprint);
    this.saveLedger(type);
    console.log(`[WatcherManager] Recorded ${type} import:`, filePath);
  }

  /** Stop all active watchers. Call from will-quit / gracefulShutdown. */
  async destroyAll(): Promise<void> {
    await Promise.all([this.stopSessionWatcher(), this.stopNotebookWatcher()]);
  }

  // ─── Private: Hasher init ──────────────────────────────────────────────────

  private async initHasher(): Promise<void> {
    this.hasher = await xxhash();
  }

  // ─── Private: Ledger I/O ───────────────────────────────────────────────────

  private loadLedger(type: WatchType): void {
    const ledgerPath = type === 'session' ? this.sessionLedgerPath : this.notebookLedgerPath;
    let ledger = new Set<string>();
    try {
      const data: unknown = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
      if (Array.isArray(data)) {
        ledger = new Set(data.filter((x): x is string => typeof x === 'string'));
      }
    } catch {
      // Missing or unreadable ledger: start fresh. Deleting the file while the
      // app runs must not keep stale fingerprints alive in memory (GH-311).
    }
    if (type === 'session') {
      this.sessionLedger = ledger;
    } else {
      this.notebookLedger = ledger;
    }
  }

  private saveLedger(type: WatchType): void {
    const ledgerPath = type === 'session' ? this.sessionLedgerPath : this.notebookLedgerPath;
    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    const tmp = `${ledgerPath}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify([...ledger]));
      fs.renameSync(tmp, ledgerPath);
    } catch (err) {
      console.warn(`[WatcherManager] Failed to save ${type} ledger:`, err);
    }
  }

  // ─── Private: Fingerprint ─────────────────────────────────────────────────

  /**
   * Compute a fast fingerprint from the first 64 KB of the file plus its size.
   * Avoids reading multi-GB files entirely while still being collision-resistant.
   */
  private computeFingerprint(filePath: string): string | null {
    if (!this.hasher) return null;
    let fd: number | undefined;
    try {
      fd = fs.openSync(filePath, 'r');
      const stat = fs.fstatSync(fd);
      const sampleLen = Math.min(stat.size, FINGERPRINT_SAMPLE_BYTES);
      const buf = Buffer.alloc(sampleLen);
      fs.readSync(fd, buf, 0, sampleLen, 0);
      fs.closeSync(fd);
      fd = undefined;
      // h64Raw takes Uint8Array; Buffer is a Uint8Array subclass — use explicit view
      const u8 = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
      const hash = this.hasher.h64Raw(u8);
      return `${stat.size}:${hash.toString(16)}`;
    } catch {
      if (fd !== undefined)
        try {
          fs.closeSync(fd);
        } catch {
          /* ignore */
        }
      return null;
    }
  }

  // ─── Private: Per-file processing ─────────────────────────────────────────

  private async handleNewFile(filePath: string, type: WatchType): Promise<void> {
    // chokidar already waited for the size to settle; this guard only turns
    // "nothing happened" into a visible skip notice.
    let size: number;
    try {
      size = fs.statSync(filePath).size;
    } catch {
      this.reportSkip(type, filePath, 'unreadable');
      return;
    }
    if (size === 0) {
      this.reportSkip(type, filePath, 'empty');
      return;
    }

    const fingerprint = this.computeFingerprint(filePath);
    if (!fingerprint) {
      this.reportSkip(type, filePath, 'unreadable');
      return;
    }

    const ledger = type === 'session' ? this.sessionLedger : this.notebookLedger;
    if (ledger.has(fingerprint)) {
      this.reportSkip(type, filePath, 'already-imported');
      return;
    }

    const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
    for (const pending of inFlight.values()) {
      if (pending === fingerprint) {
        this.reportSkip(type, filePath, 'already-queued');
        return;
      }
    }

    inFlight.set(filePath, fingerprint);
    this.queueBatch(type, filePath);
  }

  /** Tell the renderer about a file that will not be imported (GH-311). */
  private reportSkip(type: WatchType, filePath: string, reason: FileSkipReason): void {
    console.warn(`[WatcherManager] Skipped ${type} file (${reason}):`, filePath);
    const win = this.getWindow();
    if (!win || win.isDestroyed()) return;
    const payload: FileSkippedPayload = { type, path: filePath, reason };
    win.webContents.send('watcher:fileSkipped', payload);
  }

  // ─── Private: Batching ────────────────────────────────────────────────────

  private queueBatch(type: WatchType, filePath: string): void {
    if (type === 'session') {
      this.sessionBatch.push(filePath);
      if (this.sessionBatchTimer) return;
      this.sessionBatchTimer = setTimeout(() => {
        const files = [...this.sessionBatch];
        this.sessionBatch = [];
        this.sessionBatchTimer = null;
        this.dispatchBatch('session', files);
      }, BATCH_DELAY_MS);
    } else {
      this.notebookBatch.push(filePath);
      if (this.notebookBatchTimer) return;
      this.notebookBatchTimer = setTimeout(() => {
        const files = [...this.notebookBatch];
        this.notebookBatch = [];
        this.notebookBatchTimer = null;
        this.dispatchBatch('notebook', files);
      }, BATCH_DELAY_MS);
    }
  }

  private dispatchBatch(type: WatchType, files: string[]): void {
    if (files.length === 0) return;
    const win = this.getWindow();
    if (!win || win.isDestroyed()) {
      const inFlight = type === 'session' ? this.sessionInFlight : this.notebookInFlight;
      for (const p of files) inFlight.delete(p);
      console.warn(
        `[WatcherManager] No window for ${files.length} ${type} file(s); forgetting them.`,
      );
      return;
    }

    const fileMeta: FileDetectedMeta[] = files.map((filePath) => {
      try {
        const stat = fs.statSync(filePath);
        // birthtime is the true creation time on macOS and Windows;
        // on Linux ext4 it equals mtime (no birthtime support).
        const createdAt =
          stat.birthtime.getTime() > 0 ? stat.birthtime.toISOString() : stat.mtime.toISOString();
        return { path: filePath, createdAt };
      } catch {
        return { path: filePath, createdAt: new Date().toISOString() };
      }
    });

    const payload: FilesDetectedPayload = { type, files, count: files.length, fileMeta };
    win.webContents.send('watcher:filesDetected', payload);
    console.log(`[WatcherManager] Dispatched ${files.length} ${type} file(s) to renderer.`);
  }
}
