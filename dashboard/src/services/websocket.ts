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

/** Reconnection configuration */
export interface ReconnectConfig {
  /** Enable automatic reconnection (default: true) */
  enabled: boolean;
  /** Initial delay in ms before first reconnect attempt (default: 1000) */
  initialDelayMs: number;
  /** Maximum delay in ms between reconnect attempts (default: 30000) */
  maxDelayMs: number;
  /** Multiplier applied to delay after each failed attempt (default: 2) */
  backoffMultiplier: number;
  /** Maximum number of reconnect attempts before giving up (0 = unlimited, default: 0) */
  maxAttempts: number;
}

const DEFAULT_RECONNECT: ReconnectConfig = {
  enabled: true,
  initialDelayMs: 1_000,
  maxDelayMs: 30_000,
  backoffMultiplier: 2,
  maxAttempts: 0,
};

/** Callbacks consumers register */
export interface SocketCallbacks {
  onStateChange?: (state: ConnectionState) => void;
  onMessage?: (msg: ServerMessage) => void;
  onError?: (error: string) => void;
  onClose?: (code: number, reason: string) => void;
  /** Called when a reconnect attempt is scheduled */
  onReconnect?: (attempt: number, delayMs: number) => void;
  /** Called when reconnect gives up after maxAttempts */
  onReconnectExhausted?: () => void;
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
  private reconnectConfig: ReconnectConfig;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  /** When true, disconnect was initiated by the user — don't auto-reconnect */
  private intentionalDisconnect = false;

  constructor(endpoint: SocketEndpoint, callbacks: SocketCallbacks, reconnect?: Partial<ReconnectConfig>) {
    this.endpoint = endpoint;
    this.callbacks = callbacks;
    this.reconnectConfig = { ...DEFAULT_RECONNECT, ...reconnect };
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

    this.intentionalDisconnect = false;
    this.reconnectAttempt = 0;
    this.cancelReconnect();
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
      this.scheduleReconnect();
    };
  }

  /** Close the WebSocket cleanly. */
  disconnect(): void {
    this.intentionalDisconnect = true;
    this.cancelReconnect();
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
  // ── Reconnection ────────────────────────────────────────────────────────

  /** Schedule a reconnect attempt with exponential backoff. */
  private scheduleReconnect(): void {
    if (this.intentionalDisconnect) return;
    if (!this.reconnectConfig.enabled) return;
    if (this.reconnectConfig.maxAttempts > 0 && this.reconnectAttempt >= this.reconnectConfig.maxAttempts) {
      this.callbacks.onReconnectExhausted?.();
      return;
    }

    const delay = Math.min(
      this.reconnectConfig.initialDelayMs * Math.pow(this.reconnectConfig.backoffMultiplier, this.reconnectAttempt),
      this.reconnectConfig.maxDelayMs,
    );
    this.reconnectAttempt++;

    this.callbacks.onReconnect?.(this.reconnectAttempt, delay);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.doReconnect();
    }, delay);
  }

  /** Perform the actual reconnect (bypasses intentional-disconnect guard). */
  private doReconnect(): void {
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close(1000, 'Reconnecting');
      }
      this.ws = null;
    }
    this.cleanup();
    // Re-enter the connect flow but keep the attempt counter
    this.setState('connecting');
    const url = this.getWsUrl();
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      this.setState('authenticating');
      this.reconnectAttempt = 0; // reset on success
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
    };

    this.ws.onerror = () => {
      this.setState('error');
      this.callbacks.onError?.('WebSocket connection error');
    };

    this.ws.onclose = (ev: CloseEvent) => {
      this.cleanup();
      this.setState('disconnected');
      this.callbacks.onClose?.(ev.code, ev.reason);
      this.scheduleReconnect();
    };
  }

  /** Cancel any pending reconnect timer. */
  private cancelReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /** Update reconnect configuration at runtime. */
  setReconnectConfig(config: Partial<ReconnectConfig>): void {
    this.reconnectConfig = { ...this.reconnectConfig, ...config };
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
    // Note: don't cancel reconnect here — cleanup is called during reconnect flow
  }
}
