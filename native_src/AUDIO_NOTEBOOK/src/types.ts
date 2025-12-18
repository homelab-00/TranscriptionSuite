// Types for the Transcription Viewer application

export interface Word {
  word: string;
  start: number;
  end: number;
  probability?: number;
  confidence?: number;
}

export interface Segment {
  text: string;
  start: number;
  end: number;
  duration?: number;
  speaker?: string;
  words?: Word[];
}

export interface Recording {
  id: number;
  filename: string;
  filepath: string;
  recorded_at: string;
  imported_at: string;
  duration_seconds: number;
  word_count: number;
  has_diarization: boolean;
  summary?: string;
}

export interface Transcription {
  recording_id: number;
  segments: Segment[];
}

export interface SearchResult {
  recording_id: number;
  recording: Recording;
  word: string;
  start_time: number;
  end_time: number;
  context: string; // Surrounding text for context
  match_type: 'word' | 'filename' | 'summary';
}

export interface RecordingsByDate {
  [date: string]: Recording[];
}

export interface SearchParams {
  query: string;
  from_date?: string;
  to_date?: string;
  fuzzy?: boolean;
}

export interface ImportJob {
  id: number;
  filename: string;
  status: 'pending' | 'transcribing' | 'completed' | 'failed';
  progress?: number;
  message?: string;
}

// LLM Types
export interface LLMStatus {
  available: boolean;
  base_url: string;
  model: string | null;
  model_state?: string | null; // "loaded", "not-loaded", etc.
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

// LM Studio Control Types
export interface ServerControlResponse {
  success: boolean;
  message: string;
  detail?: string;
}

export interface ModelLoadRequest {
  model_id?: string;
  gpu_offload?: number;
  context_length?: number;
}

export interface AvailableModel {
  id: string;
  type: string;
  state: string;
  quantization?: string;
  max_context_length?: number;
  arch?: string;
}

export interface AvailableModelsResponse {
  models: AvailableModel[];
  total: number;
  loaded: number;
}

// Conversation Types
export interface Conversation {
  id: number;
  recording_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  tokens_used?: number;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface ChatRequest {
  conversation_id: number;
  user_message: string;
  system_prompt?: string;
  include_transcription?: boolean;
  max_tokens?: number;
  temperature?: number;
}
