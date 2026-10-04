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
import path from 'path';

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
  /** Download events (GH-318): DownloadKind, clean display name, raw byte counts. */
  kind?: string;
  name?: string;
  downloadedBytes?: number;
  totalBytes?: number;
  error?: string;
}

/**
 * How long to wait for the first event before warning that the channel looks
 * dead (GH-207). A healthy startup emits its first event within seconds; 90s
 * of silence while the container runs points at a broken STARTUP_EVENTS_DIR
 * bind mount (suspected on Docker Desktop/WSL2 setups).
 */
const SILENT_CHANNEL_DIAGNOSTIC_MS = 90_000;

export class StartupEventWatcher {
  private watcher: fs.FSWatcher | null = null;
  private offset = 0;
  private filePath: string | null = null;
  private onEvent: ((event: StartupEvent) => void) | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private diagnosticTimer: ReturnType<typeof setTimeout> | null = null;
  private sawAnyEvent = false;

  /**
   * Start watching a file for new JSON Lines.
   *
   * @param filePath - Path to the startup-events.jsonl file
   * @param onEvent  - Callback invoked for each parsed event
   * @param options  - `fromEnd`: skip what is already in the file. Used when
   *                   attaching to a server that is already running, so the
   *                   startup that already happened does not replay.
   */
  start(
    filePath: string,
    onEvent: (event: StartupEvent) => void,
    options: { fromEnd?: boolean } = {},
  ): void {
    this.stop();
    this.filePath = filePath;
    this.onEvent = onEvent;
    this.offset = 0;
    if (options.fromEnd) {
      try {
        this.offset = fs.statSync(filePath).size;
      } catch {
        this.offset = 0; // not there yet: everything written later is new
      }
    }

    this.sawAnyEvent = false;
    // A server that is already running has nothing left to announce, so the
    // silent-channel diagnostic only makes sense for a fresh start.
    if (options.fromEnd) {
      this.tryWatch();
      return;
    }
    this.diagnosticTimer = setTimeout(() => {
      if (!this.sawAnyEvent) {
        console.warn(
          `[StartupEventWatcher] no startup events observed after ${SILENT_CHANNEL_DIAGNOSTIC_MS / 1000}s (file: ${this.filePath}). ` +
            'If the container is running, the STARTUP_EVENTS_DIR bind mount may not be working on this platform.',
        );
      }
    }, SILENT_CHANNEL_DIAGNOSTIC_MS);

    this.tryWatch();
  }

  /** Whether a file is currently being watched. */
  isWatching(): boolean {
    return this.filePath !== null;
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
    if (this.diagnosticTimer) {
      clearTimeout(this.diagnosticTimer);
      this.diagnosticTimer = null;
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
          if (!this.sawAnyEvent) {
            this.sawAnyEvent = true;
            if (this.diagnosticTimer) {
              clearTimeout(this.diagnosticTimer);
              this.diagnosticTimer = null;
            }
          }
          this.onEvent!(event);
        }
      } catch {
        // Malformed JSON line — skip and continue
        // This can happen if the file is written to mid-line
      }
    }
  }
}

/** Where the server's events directory is mounted inside the container. */
const EVENTS_MOUNT_DESTINATION = '/startup-events';
const EVENTS_FILE_NAME = 'startup-events.jsonl';

/**
 * Host path of the events file of a running container, from the output of
 * `inspect --format '{{json .Mounts}}'` (GH-318).
 *
 * The events directory is a fresh temp dir per container start and its path
 * lives only in the memory of the dashboard that started the container. A
 * dashboard that starts while the server is already running recovers it from
 * the container's own mount list.
 */
export function eventsFileFromMounts(inspectOutput: string): string | null {
  let mounts: unknown;
  try {
    mounts = JSON.parse(inspectOutput);
  } catch {
    return null;
  }
  if (!Array.isArray(mounts)) return null;
  for (const mount of mounts as Array<{ Source?: unknown; Destination?: unknown }>) {
    if (mount?.Destination === EVENTS_MOUNT_DESTINATION && typeof mount.Source === 'string') {
      return path.join(mount.Source, EVENTS_FILE_NAME);
    }
  }
  return null;
}
