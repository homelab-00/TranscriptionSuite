// Types for the Transcription Suite Web UI

export interface Word {
  word: string;
  start: number;
  end: number;
  probability?: number;
  confidence?: number;
}

// Record Types (for real-time transcription)
export interface TranscriptionResult {
  text: string;
  words?: Word[];
  duration: number;
  language?: string;
  is_final: boolean;
}

export interface HistoryEntry {
  id: string;
  text: string;
  duration: number;
  timestamp: Date;
  type: 'recording' | 'file';
}

// WebSocket message types
export type WSMessageType =
  | 'auth'
  | 'auth_ok'
  | 'auth_fail'
  | 'session_busy'
  | 'start'
  | 'stop'
  | 'session_started'
  | 'session_stopped'
  | 'realtime'
  | 'final'
  | 'ping'
  | 'pong'
  | 'error';

export interface WSMessage {
  type: WSMessageType;
  data?: Record<string, unknown>;
  timestamp?: number;
}

// Admin Types (token management)
export interface TokenInfo {
  token_id: string;
  token: string;  // Masked token for display
  client_name: string;
  created_at: string;
  expires_at?: string | null;
  is_admin: boolean;
  is_revoked: boolean;
  is_expired: boolean;
}

export interface NewTokenInfo {
  token_id: string;
  token: string;  // Full token - only shown at creation
  client_name: string;
  created_at: string;
  expires_at?: string | null;
  is_admin: boolean;
}
