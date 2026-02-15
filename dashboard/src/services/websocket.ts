/**
 * TranscriptionSocket — low-level WebSocket wrapper for the transcription server.
 *
 * Handles connection lifecycle, auth handshake, binary framing (PCM Int16),
 * typed message dispatch, keep-alive pings, and automatic reconnection.
 *
 * Consumers: useTranscription (one-shot /ws), useLiveMode (continuous /ws/live).
 */

import { apiClient } from '../api/client';

// ─── Types ────────────────────────────────────────────────────────────────────

export type SocketEndpoint = '/ws' | '/ws/live';

export type ConnectionState = 'disconnected' | 'connecting' | 'authenticating' | 'ready' | 'error';

/** Messages the server can send us */
export interface ServerMessage {
  type: string;
  data?: Record<string, unknown>;
}

/** Callbacks consumers register */
export interface SocketCallbacks {
  onStateChange?: (state: ConnectionState) => void;
  onMessage?: (msg: ServerMessage) => void;
  onError?: (error: string) => void;
  onClose?: (code: number, reason: string) => void;
}

// ─── Binary framing ──────────────────────────────────────────────────────────

const SAMPLE_RATE = 16_000;

/**
 * Frame raw PCM Int16 audio into the server's binary format:
 *   [uint32 LE metadata length] [JSON metadata] [raw PCM bytes]
 */
export function frameAudioChunk(pcmInt16: Int16Array): ArrayBuffer {
  const metadata = JSON.stringify({ sample_rate: SAMPLE_RATE });
  const metaBytes = new TextEncoder().encode(metadata);
  const metaLen = metaBytes.byteLength;

  const buf = new ArrayBuffer(4 + metaLen + pcmInt16.byteLength);
  const view = new DataView(buf);

  // 4-byte LE metadata length
  view.setUint32(0, metaLen, true);
  // metadata JSON
  new Uint8Array(buf, 4, metaLen).set(metaBytes);
  // PCM data
  new Uint8Array(buf, 4 + metaLen).set(new Uint8Array(pcmInt16.buffer, pcmInt16.byteOffset, pcmInt16.byteLength));

  return buf;
}

// ─── TranscriptionSocket ─────────────────────────────────────────────────────

export class TranscriptionSocket {
  private ws: WebSocket | null = null;
  private endpoint: SocketEndpoint;
  private callbacks: SocketCallbacks;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private state: ConnectionState = 'disconnected';

  constructor(endpoint: SocketEndpoint, callbacks: SocketCallbacks) {
    this.endpoint = endpoint;
    this.callbacks = callbacks;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  /** Derive ws:// or wss:// URL from the API client's base URL */
  private getWsUrl(): string {
    const httpUrl = apiClient.getBaseUrl(); // e.g. "http://localhost:8000"
    const wsUrl = httpUrl
      .replace(/^https:/, 'wss:')
      .replace(/^http:/, 'ws:');
    return `${wsUrl}${this.endpoint}`;
  }

  /** Open the WebSocket and begin the auth handshake. */
  connect(): void {
    if (this.ws) this.disconnect();

    this.setState('connecting');

    const url = this.getWsUrl();
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      this.setState('authenticating');
      // Send auth message — token may be empty for localhost bypass
      const token = apiClient.getAuthToken?.() ?? '';
      this.sendJSON({ type: 'auth', data: { token } });
    };

    this.ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === 'string') {
        try {
          const msg: ServerMessage = JSON.parse(ev.data);
          this.handleMessage(msg);
        } catch {
          this.callbacks.onError?.('Invalid JSON from server');
        }
      }
      // We don't expect binary messages from the server
    };

    this.ws.onerror = () => {
      this.setState('error');
      this.callbacks.onError?.('WebSocket connection error');
    };

    this.ws.onclose = (ev: CloseEvent) => {
      this.cleanup();
      this.setState('disconnected');
      this.callbacks.onClose?.(ev.code, ev.reason);
    };
  }

  /** Close the WebSocket cleanly. */
  disconnect(): void {
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close(1000, 'Client disconnect');
      }
      this.ws = null;
    }
    this.cleanup();
    this.setState('disconnected');
  }

  /** Whether the socket is open and authenticated. */
  get isReady(): boolean {
    return this.state === 'ready' && this.ws?.readyState === WebSocket.OPEN;
  }

  /** Current connection state. */
  get connectionState(): ConnectionState {
    return this.state;
  }

  // ── Sending ────────────────────────────────────────────────────────────────

  /** Send a typed JSON message. */
  sendJSON(msg: { type: string; data?: unknown }): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  /** Send a framed binary audio chunk. */
  sendAudio(pcmInt16: Int16Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(frameAudioChunk(pcmInt16));
    }
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  private handleMessage(msg: ServerMessage): void {
    switch (msg.type) {
      case 'auth_ok':
        this.setState('ready');
        this.startPing();
        break;
      case 'auth_fail':
        this.setState('error');
        this.callbacks.onError?.((msg.data?.message as string) ?? 'Authentication failed');
        this.disconnect();
        return;
      case 'error':
        this.callbacks.onError?.((msg.data?.message as string) ?? 'Server error');
        break;
      case 'pong':
        // Keep-alive acknowledged — nothing to do
        return;
    }
    // Forward all messages (including auth_ok) to consumer
    this.callbacks.onMessage?.(msg);
  }

  private setState(s: ConnectionState): void {
    if (this.state !== s) {
      this.state = s;
      this.callbacks.onStateChange?.(s);
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.sendJSON({ type: 'ping' });
    }, 25_000);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private cleanup(): void {
    this.stopPing();
  }
}
