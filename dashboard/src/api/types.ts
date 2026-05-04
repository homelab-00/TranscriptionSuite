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
  status: 'ready' | 'ready_live_mode' | 'loading' | 'initializing';
  models?: Record<string, unknown>;
}

export interface ServerStatus {
  status: string;
  version?: string;
  models?: Record<string, unknown> & {
    transcription?: { selected_model?: string; loaded?: boolean; disabled?: boolean };
  };
  features?: Record<string, unknown>;
  ready?: boolean;
  uptime?: number;
  gpu_available?: boolean;
  gpu_memory?: string;
  gpu_error?: string;
  gpu_error_action?: string;
  /**
   * Diagnostic hint surfaced when the backend's CUDA health check
   * returns the error-999 "unrecoverable" fingerprint. Present only on
   * the error-999 path; absent for other GPU failure modes.
   * Consumed by the GpuHealthCard on the Server tab.
   */
  gpu_error_recovery_hint?: string;
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
  parallel_diarization?: boolean;
  multitrack?: boolean;
  file_created_at?: string;
  title?: string;
  /** Active recording-profile id (FR18). Snapshotted server-side at job start. */
  profile_id?: number | null;
}

export interface LanguagesResponse {
  languages: Record<string, string>;
  count: number;
  auto_detect: boolean;
  backend_type?:
    | 'whisper'
    | 'parakeet'
    | 'canary'
    | 'vibevoice_asr'
    | 'mlx_parakeet'
    | 'mlx_canary'
    | 'mlx_whisper'
    | 'mlx_vibevoice';
  supports_translation?: boolean;
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
  transcription_backend?: 'whisper' | 'parakeet' | 'canary' | 'vibevoice_asr' | null;
  // Issue #104 Sprint 4 — auto-action lifecycle (migration 015). Optional on
  // older serialized clients; null when the toggle is off or the action has
  // not run yet. Status enum lives in the migration; the dashboard's
  // statusToBadgeProps handles all known values.
  auto_summary_status?: string | null;
  auto_summary_error?: string | null;
  auto_export_status?: string | null;
  auto_export_error?: string | null;
  auto_export_path?: string | null;
}

export interface RecordingDetail extends Recording {
  segments: TranscriptionSegment[];
  words: TranscriptionWord[];
  // Issue #104 Sprint 5 — Story 7.7: latest webhook delivery state for
  // this recording. Both fields are null when no webhook has ever been
  // attempted (toggle off, no profile, fresh recording).
  webhook_status?: string | null;
  webhook_error?: string | null;
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

/** Returned by POST /api/notebook/transcribe/upload (202 Accepted) */
export interface TranscriptionAccepted {
  job_id: string;
  /**
   * Issue #104 / Story 2.4 — populated by /api/transcribe/import when a
   * prior job's audio_hash matches this upload. Empty list = J1 happy path
   * (no duplicate). Notebook upload (`/api/notebook/transcribe/upload`)
   * doesn't currently populate this field; it's reserved for future cross-
   * flow dedup. Default-empty keeps the response shape backwards-compatible
   * for callers that ignore it.
   */
  dedup_matches?: DedupMatch[];
}

/** A prior item that shares this upload's audio_hash or normalized_audio_hash.
 *
 * `source` (Sprint 2 carve-out — Item 2) tells the dashboard which table the
 * match came from. Optional for backwards compatibility with older server
 * responses that pre-date Item 2. Default behavior on undefined is to assume
 * `'transcription_job'` (the original Sprint 2 contract).
 */
export interface DedupMatch {
  recording_id: string;
  name: string;
  created_at: string;
  source?: 'transcription_job' | 'recording';
}

/** Returned by POST /api/transcribe/import/dedup-check (Issue #104, Story 2.4). */
export interface DedupCheckResponse {
  matches: DedupMatch[];
}

/** Result stored in job_tracker after background transcription completes */
export interface JobTrackerResult {
  job_id: string;
  recording_id?: number;
  message?: string;
  diarization?: {
    requested: boolean;
    performed: boolean;
    reason: string | null;
  };
  error?: string;
}

/** Typed status from job_tracker exposed via /api/admin/status */
export interface JobTrackerStatus {
  is_busy: boolean;
  active_user: string | null;
  active_job_id: string | null;
  cancellation_requested: boolean;
  progress: { current: number; total: number; message: string } | null;
  result: JobTrackerResult | null;
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

// ─── File Import (Session) ────────────────────────────────────────────────────

/** Result stored in job_tracker after a file-import background transcription completes */
export interface FileImportJobResult {
  job_id: string;
  transcription?: TranscriptionResponse;
  diarization?: {
    requested: boolean;
    performed: boolean;
    reason: string | null;
  };
  error?: string;
}

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
    transcription?: {
      model: string;
      device?: string;
    };
    main_transcriber?: {
      model: string;
      device?: string;
    };
    live_transcriber?: {
      model: string;
      device?: string;
    };
    live_transcription?: {
      model: string;
      device?: string;
      [key: string]: unknown;
    };
    diarization?: {
      parallel?: boolean;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  features?: {
    diarization?: { available: boolean; reason: string };
    whisper?: { available: boolean; reason: string };
    nemo?: { available: boolean; reason: string };
    mlx?: { available: boolean; reason: string };
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

// ─── Server Config Tree ──────────────────────────────────────────────────────

export interface ConfigField {
  key: string;
  path: string;
  value: unknown;
  type: 'string' | 'boolean' | 'integer' | 'float' | 'list' | 'object';
  comment: string;
}

export interface ConfigSubsection {
  key: string;
  title: string;
  comment: string;
  fields: ConfigField[];
}

export interface ConfigSection {
  key: string;
  title: string;
  comment: string;
  fields: ConfigField[];
  subsections: ConfigSubsection[];
}

export interface ServerConfigTree {
  sections: ConfigSection[];
}

// ─── LLM ──────────────────────────────────────────────────────────────────────

export interface LLMStatus {
  available: boolean;
  base_url: string;
  model: string | null;
  model_state: string | null;
  error: string | null;
  has_api_key: boolean;
  title_generation_prompt?: string | null;
  auto_title_enabled?: boolean;
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
  owned_by?: string;
  state?: string;
}

export interface LLMModelsResponse {
  models: LLMModel[];
  /** Present in LM Studio-specific /models/available responses */
  total?: number;
  /** Present in LM Studio-specific /models/available responses */
  loaded?: number;
}

export interface ChatRequest {
  conversation_id: number;
  user_message: string;
  system_prompt?: string;
  include_transcription?: boolean;
  max_tokens?: number;
  temperature?: number;
  model?: string;
}

export interface Conversation {
  id: number;
  recording_id: number;
  title: string;
  created_at: string;
  updated_at: string;
  model?: string | null;
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
