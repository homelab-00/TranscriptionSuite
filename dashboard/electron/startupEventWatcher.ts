/**
 * Startup event watcher — reads JSON Lines from a bind-mounted file.
 *
 * The server writes structured events to /startup-events/startup-events.jsonl
 * during container startup (bootstrap, lifespan, model download). This watcher
 * uses fs.watch() to detect new data and parses each line as JSON, forwarding
 * parsed events to a callback.
 *
 * Designed to run in the Electron main process. Events are forwarded to the
 * renderer via IPC.
 */

import fs from 'fs';

export interface StartupEvent {
  id: string;
  category: string;
  label: string;
  status?: string;
  progress?: number;
  totalSize?: string;
  downloadedSize?: string;
  detail?: string;
  severity?: string;
  persistent?: boolean;
  phase?: string;
  syncMode?: string;
  expandableDetail?: string;
  durationMs?: number;
  ts?: number;
}

export class StartupEventWatcher {
  private watcher: fs.FSWatcher | null = null;
  private offset = 0;
  private filePath: string | null = null;
  private onEvent: ((event: StartupEvent) => void) | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * Start watching a file for new JSON Lines.
   *
   * @param filePath - Path to the startup-events.jsonl file
   * @param onEvent  - Callback invoked for each parsed event
   */
  start(filePath: string, onEvent: (event: StartupEvent) => void): void {
    this.stop();
    this.filePath = filePath;
    this.onEvent = onEvent;
    this.offset = 0;

    this.tryWatch();
  }

  /** Stop watching and clean up. */
  stop(): void {
    if (this.watcher) {
      this.watcher.close();
      this.watcher = null;
    }
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.filePath = null;
    this.onEvent = null;
    this.offset = 0;
  }

  private tryWatch(): void {
    if (!this.filePath || !this.onEvent) return;

    try {
      // Read any existing content first
      this.readNewLines();

      this.watcher = fs.watch(this.filePath, () => {
        this.readNewLines();
      });

      // Handle watcher errors (file deleted, etc.)
      this.watcher.on('error', () => {
        this.watcher?.close();
        this.watcher = null;
        // Retry after a short delay
        this.retryTimer = setTimeout(() => this.tryWatch(), 1000);
      });
    } catch {
      // File may not exist yet — retry
      this.retryTimer = setTimeout(() => this.tryWatch(), 1000);
    }
  }

  private readNewLines(): void {
    if (!this.filePath || !this.onEvent) return;

    let content: string;
    let fd: number;
    try {
      fd = fs.openSync(this.filePath, 'r');
    } catch {
      return; // File not openable — will retry on next watch event
    }
    try {
      const stat = fs.fstatSync(fd);

      // File was truncated (e.g. container restart) — reset to beginning
      if (stat.size < this.offset) {
        this.offset = 0;
      }

      const bytesToRead = stat.size - this.offset;
      if (bytesToRead <= 0) return;

      const buffer = Buffer.alloc(bytesToRead);
      fs.readSync(fd, buffer, 0, bytesToRead, this.offset);

      this.offset = stat.size;
      content = buffer.toString('utf-8');
    } catch {
      return; // File not readable — will retry on next watch event
    } finally {
      fs.closeSync(fd);
    }

    const lines = content.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      try {
        const event = JSON.parse(trimmed) as StartupEvent;
        if (event.id && event.category && event.label) {
          this.onEvent!(event);
        }
      } catch {
        // Malformed JSON line — skip and continue
        // This can happen if the file is written to mid-line
      }
    }
  }
}
