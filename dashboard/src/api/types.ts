/**
 * TypeScript interfaces matching the FastAPI server's response models.
 * Grouped by API route module.
 */

// ─── Health / Status ──────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  service: string;
}

export interface ReadyResponse {
  status: 'ready' | 'loading' | 'initializing';
  models?: Record<string, unknown>;
}

export interface ServerStatus {
  status: string;
  version?: string;
  models?: Record<string, unknown>;
  features?: Record<string, unknown>;
  uptime?: number;
  gpu_available?: boolean;
  gpu_memory?: string;
  diarization_available?: boolean;
  active_connections?: number;
  tls_enabled?: boolean;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  token: string;
}

export interface LoginResponse {
  success: boolean;
  user?: {
    name: string;
    is_admin: boolean;
    token_id: string;
  };
  message?: string;
}

export interface AuthToken {
  token: string;
  token_id: string;
  client_name: string;
  is_admin: boolean;
  created_at: string;
  expires_at: string | null;
  is_revoked?: boolean;
  is_expired?: boolean;
}

export interface CreateTokenRequest {
  client_name: string;
  is_admin?: boolean;
  expiry_days?: number;
}

// ─── Transcription ────────────────────────────────────────────────────────────

export interface TranscriptionResponse {
  text: string;
  segments: TranscriptionSegment[];
  words: TranscriptionWord[];
  language?: string;
  language_probability: number;
  duration: number;
  num_speakers: number;
}

export interface TranscriptionSegment {
  text: string;
  start: number;
  end: number;
  speaker?: string;
  words?: TranscriptionWord[];
}

export interface TranscriptionWord {
  word: string;
  start: number;
  end: number;
  probability?: number;
  speaker?: string;
}

export interface TranscriptionUploadOptions {
  language?: string;
  translation_enabled?: boolean;
  translation_target_language?: string;
  enable_diarization?: boolean;
  enable_word_timestamps?: boolean;
  expected_speakers?: number;
  file_created_at?: string;
}

export interface LanguagesResponse {
  languages: Record<string, string>;
  count: number;
  auto_detect: boolean;
}

export interface TranscriptionCancelResponse {
  success: boolean;
  cancelled_user?: string;
  message: string;
}

// ─── Notebook ─────────────────────────────────────────────────────────────────

export interface Recording {
  id: number;
  filename: string;
  filepath: string;
  title: string | null;
  duration_seconds: number;
  recorded_at: string;
  imported_at: string | null;
  word_count: number;
  has_diarization: boolean;
  summary: string | null;
  summary_model: string | null;
}

export interface RecordingDetail extends Recording {
  segments: TranscriptionSegment[];
  words: TranscriptionWord[];
}

export interface RecordingTranscription {
  recording_id: number;
  segments: TranscriptionSegment[];
}

export interface UploadResponse {
  recording_id: number;
  message: string;
  diarization: {
    requested: boolean;
    performed: boolean;
    reason: string | null;
  };
}

export interface CalendarResponse {
  year: number;
  month: number;
  days: Record<string, Recording[]>;
  total_recordings: number;
}

export interface TimeslotResponse {
  recordings: Recording[];
  next_available: string | null;
  total_duration: number;
  available_seconds: number;
  is_full: boolean;
}

export type ExportFormat = 'txt' | 'srt' | 'ass';

export interface BackupInfo {
  filename: string;
  created_at: string;
  size: number;
}

export interface BackupsResponse {
  backups: BackupInfo[];
  count: number;
}

export interface BackupCreateResponse {
  success: boolean;
  message: string;
  backup: BackupInfo;
}

export interface RestoreResponse {
  success: boolean;
  message: string;
  restored_from: string;
}

// ─── Search ───────────────────────────────────────────────────────────────────

export interface SearchResult {
  id: number | null;
  recording_id: number;
  segment_id: number | null;
  word: string;
  start_time: number;
  end_time: number;
  filename: string;
  title: string | null;
  recorded_at: string;
  speaker: string | null;
  context: string;
  match_type: 'word' | 'summary' | 'filename';
}

export interface SearchResponse {
  query: string;
  fuzzy: boolean;
  results: SearchResult[];
  count: number;
}

export interface WordSearchResponse {
  query: string;
  results: Array<Record<string, unknown>>;
  count: number;
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export interface AdminStatus {
  status: string;
  models: Record<string, unknown>;
  models_loaded?: boolean;
  config: {
    server: Record<string, unknown>;
    transcription: {
      model: string;
      device: string;
    };
    live_transcription?: {
      model: string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}

export interface LogEntry {
  timestamp: string;
  level: string;
  service: string;
  message: string;
}

export interface LogsResponse {
  logs: LogEntry[];
  count: number;
  filters: {
    service: string | null;
    level: string | null;
  };
}

// ─── LLM ──────────────────────────────────────────────────────────────────────

export interface LLMStatus {
  available: boolean;
  base_url: string;
  model: string | null;
  model_state: string | null;
  error: string | null;
}

export interface LLMResponse {
  response: string;
  model: string;
  tokens_used: number | null;
}

export interface LLMRequest {
  transcription_text: string;
  system_prompt?: string;
  user_prompt?: string;
  max_tokens?: number;
  temperature?: number;
}

export interface ServerControlResponse {
  success: boolean;
  message: string;
  detail?: string;
}

export interface LLMModel {
  id: string;
  type: string;
  state: string;
  quantization?: string;
  max_context_length?: number;
  arch?: string;
}

export interface LLMModelsResponse {
  models: LLMModel[];
  total: number;
  loaded: number;
}

export interface ChatRequest {
  conversation_id: number;
  user_message: string;
  system_prompt?: string;
  include_transcription?: boolean;
  max_tokens?: number;
  temperature?: number;
}

export interface Conversation {
  id: number;
  recording_id: number;
  title: string;
  created_at: string;
  updated_at: string;
  messages?: ChatMessage[];
}

export interface ChatMessage {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  model?: string;
  tokens_used?: number;
  created_at: string;
}
