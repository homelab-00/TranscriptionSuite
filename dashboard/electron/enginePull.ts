/**
 * Image pull through the Docker Engine API (GH-318).
 *
 * `docker pull` without a TTY prints per-layer states and no bytes. The Engine
 * API streams byte progress per layer, so the download bar can show how much
 * has actually come down and how fast.
 *
 * This is an optional fast path, never the only one: any failure here makes
 * the caller fall back to the CLI pull, which also owns credential helpers,
 * error classification and retries. No registry credentials are sent, so a
 * private image simply fails here and goes through the CLI.
 *
 * Free of any `electron` import; the endpoint is passed in.
 */

import http from 'http';
import { enginePullError, type EnginePullMessage } from './pullProgress.js';

export type { EnginePullMessage };

/** A local socket the daemon listens on: a unix socket path or a Windows named pipe. */
export interface EngineEndpoint {
  socketPath: string;
}

export interface EnginePullResult {
  ok: boolean;
  /** Set when ok is false. */
  error?: string;
  /** True when the pull ended because the caller aborted it. */
  cancelled?: boolean;
}

const PING_TIMEOUT_MS = 2_000;

/**
 * Turn a DOCKER_HOST / docker-context endpoint into a local socket.
 * Remote endpoints (tcp, ssh) return null: the caller uses the CLI instead.
 */
export function parseEngineHost(host: string | undefined): EngineEndpoint | null {
  const value = (host ?? '').trim();
  if (value.startsWith('unix://')) {
    const socketPath = value.slice('unix://'.length);
    return socketPath ? { socketPath } : null;
  }
  if (value.startsWith('npipe://')) {
    // npipe:////./pipe/docker_engine -> \\.\pipe\docker_engine
    const pipe = value.slice('npipe://'.length).replace(/\//g, '\\');
    return pipe ? { socketPath: pipe } : null;
  }
  return null;
}

/** "ghcr.io/org/app:v1" -> { repo, tag }. A colon before the last slash is a registry port. */
export function splitImageReference(reference: string): { repo: string; tag: string } {
  const lastSlash = reference.lastIndexOf('/');
  const lastColon = reference.lastIndexOf(':');
  if (lastColon > lastSlash) {
    return { repo: reference.slice(0, lastColon), tag: reference.slice(lastColon + 1) };
  }
  return { repo: reference, tag: 'latest' };
}

/** Whether a daemon answers on *endpoint*. Never throws. */
export function pingEngine(endpoint: EngineEndpoint): Promise<boolean> {
  return new Promise((resolve) => {
    const request = http.request(
      { socketPath: endpoint.socketPath, path: '/_ping', method: 'GET', timeout: PING_TIMEOUT_MS },
      (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      },
    );
    request.on('timeout', () => request.destroy());
    request.on('error', () => resolve(false));
    request.end();
  });
}

/**
 * Pull *image* through the Engine API, handing each stream message to
 * *onMessage*. Resolves, never rejects. Aborting *signal* hangs up, which
 * makes the daemon cancel the pull.
 */
export function pullViaEngine(
  endpoint: EngineEndpoint,
  image: { repo: string; tag: string },
  onMessage: (message: EnginePullMessage) => void,
  signal: AbortSignal,
): Promise<EnginePullResult> {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (result: EnginePullResult) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', onAbort);
      resolve(result);
    };
    const cancelled = (): EnginePullResult => ({ ok: false, error: 'cancelled', cancelled: true });

    if (signal.aborted) {
      settle(cancelled());
      return;
    }

    const query = `fromImage=${encodeURIComponent(image.repo)}&tag=${encodeURIComponent(image.tag)}`;
    const request = http.request(
      { socketPath: endpoint.socketPath, path: `/images/create?${query}`, method: 'POST' },
      (response) => {
        if (response.statusCode !== 200) {
          let body = '';
          response.on('data', (chunk: Buffer) => {
            body += chunk.toString();
          });
          response.on('end', () => {
            settle({ ok: false, error: errorFromBody(body, response.statusCode) });
          });
          return;
        }

        // The stream is newline-delimited JSON; a chunk can end mid-message.
        let remainder = '';
        let streamError: string | null = null;
        const consume = (line: string) => {
          const text = line.trim();
          if (!text) return;
          let message: EnginePullMessage;
          try {
            message = JSON.parse(text) as EnginePullMessage;
          } catch {
            return;
          }
          streamError = streamError ?? enginePullError(message);
          try {
            onMessage(message);
          } catch {
            // Progress reporting must never fail the pull it is watching.
          }
        };
        response.on('data', (chunk: Buffer) => {
          const lines = (remainder + chunk.toString()).split(/\r?\n/);
          remainder = lines.pop() ?? '';
          for (const line of lines) consume(line);
        });
        response.on('end', () => {
          consume(remainder);
          settle(streamError ? { ok: false, error: streamError } : { ok: true });
        });
        response.on('error', (err) => {
          settle(signal.aborted ? cancelled() : { ok: false, error: err.message });
        });
      },
    );

    const onAbort = () => {
      request.destroy();
      settle(cancelled());
    };
    signal.addEventListener('abort', onAbort);
    request.on('error', (err) => {
      settle(signal.aborted ? cancelled() : { ok: false, error: err.message });
    });
    request.end();
  });
}

function errorFromBody(body: string, statusCode: number | undefined): string {
  try {
    const parsed = JSON.parse(body) as { message?: string };
    if (parsed.message) return parsed.message;
  } catch {
    // not JSON - fall through
  }
  return body.trim() || `Engine API answered ${statusCode ?? 'with no status'}`;
}
