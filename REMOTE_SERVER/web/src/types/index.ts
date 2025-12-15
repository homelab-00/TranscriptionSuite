// User information returned from login
export interface User {
  name: string;
  is_admin: boolean;
  created_at: string;
}

// Token information (for admin panel)
export interface TokenInfo {
  token: string;       // Masked token for display
  full_token: string;  // Full token for copy
  client_name: string;
  created_at: string;
  is_admin: boolean;
  is_revoked: boolean;
}

// Transcription result
export interface TranscriptionResult {
  text: string;
  words?: WordInfo[];
  duration: number;
  language?: string;
  is_final: boolean;
}

// Word-level timestamp info
export interface WordInfo {
  word: string;
  start: number;
  end: number;
  probability: number;
}

// Session history entry
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

// Server status
export interface ServerStatus {
  running: boolean;
  transcribing: boolean;
  active_user: string | null;
  https_port: number;
  wss_port: number;
}
