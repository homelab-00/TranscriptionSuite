/**
 * MLX Log Sink — owns the persist-and-deliver pipeline for `mlx:logLine`
 * messages emitted by `MLXServerManager`.
 *
 * Mirrors the existing `app:clientLogLine` pipeline in `main.ts` (the
 * `earlyLogBuffer` + `flushEarlyLogBuffer` pattern at `:134-148` and the
 * disk-write helper at `:218-251`) but isolated in a small factory so it can
 * be unit-tested without spinning up an Electron app.
 *
 * Two states:
 *   - **Buffer mode** (initial): `_buffer` is an array. `append()` pushes
 *     each line to it (FIFO-evicting at MLX_EARLY_LOG_BUFFER_MAX) and writes
 *     to disk. No IPC delivery yet.
 *   - **Live mode** (after `flush()`): `_buffer` is `null`. `append()` writes
 *     to disk and sends via `webContents.send('mlx:logLine', line)`.
 *
 * The transition happens exactly once, when `flush()` is called from the
 * `did-finish-load` handler in `main.ts`. Calling `flush()` twice is a no-op.
 */

import * as fs from 'fs';
import type { BrowserWindow } from 'electron';

export const MLX_EARLY_LOG_BUFFER_MAX = 1000;
export const MLX_LOG_IPC_CHANNEL = 'mlx:logLine';

export interface MlxLogSinkOptions {
  getWindow: () => BrowserWindow | null;
  getLogFilePath: () => string;
}

export interface MlxLogSink {
  append: (line: string) => void;
  flush: () => void;
}

export function createMlxLogSink(opts: MlxLogSinkOptions): MlxLogSink {
  let buffer: string[] | null = [];

  function persistToDisk(line: string): void {
    try {
      fs.appendFileSync(opts.getLogFilePath(), `${line}\n`, 'utf-8');
    } catch (err) {
      // Best-effort only — never block log delivery on disk failures.
      console.warn('[MLX] Failed to persist log line:', err);
    }
  }

  function deliverToRenderer(line: string): void {
    const win = opts.getWindow();
    if (!win || win.isDestroyed()) return;
    try {
      win.webContents.send(MLX_LOG_IPC_CHANNEL, line);
    } catch {
      // Window may be tearing down — drop silently.
    }
  }

  return {
    append(line: string): void {
      persistToDisk(line);
      if (buffer) {
        buffer.push(line);
        if (buffer.length > MLX_EARLY_LOG_BUFFER_MAX) {
          buffer.splice(0, buffer.length - MLX_EARLY_LOG_BUFFER_MAX);
        }
      } else {
        deliverToRenderer(line);
      }
    },

    flush(): void {
      if (!buffer) return;
      const queued = buffer;
      buffer = null;
      for (const line of queued) {
        deliverToRenderer(line);
      }
    },
  };
}
