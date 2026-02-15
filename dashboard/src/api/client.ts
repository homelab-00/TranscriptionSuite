/**
 * API client for TranscriptionSuite server.
 * Covers all REST endpoints; WebSocket connections are handled separately.
 */

import { getServerBaseUrl } from '../config/store';
import type {
  HealthResponse,
  ReadyResponse,
  ServerStatus,
  LoginRequest,
  LoginResponse,
  AuthToken,
  CreateTokenRequest,
  TranscriptionResponse,
  TranscriptionUploadOptions,
  TranscriptionCancelResponse,
  LanguagesResponse,
  Recording,
  RecordingDetail,
  RecordingTranscription,
  UploadResponse,
  CalendarResponse,
  TimeslotResponse,
  ExportFormat,
  BackupsResponse,
  BackupCreateResponse,
  RestoreResponse,
  SearchResponse,
  WordSearchResponse,
  AdminStatus,
  LogsResponse,
  LLMStatus,
  LLMResponse,
  LLMRequest,
  ServerControlResponse,
  LLMModelsResponse,
  LLMModel,
  Conversation,
  ChatMessage,
} from './types';

// Re-export types that consumers need
export type { HealthResponse, ReadyResponse, ServerStatus } from './types';

export class APIClient {
  private baseUrl: string;
  private authToken: string | null = null;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  // ─── Configuration ────────────────────────────────────────────────────────

  /** Update the server base URL */
  setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/+$/, '');
  }

  /** Get the current base URL */
  getBaseUrl(): string {
    return this.baseUrl;
  }

  /** Set the auth token for authenticated requests */
  setAuthToken(token: string | null): void {
    this.authToken = token;
  }

  /** Get the current auth token (used by WebSocket service for handshake) */
  getAuthToken(): string | null {
    return this.authToken;
  }

  /**
   * Sync base URL from config store.
   * Call this on app startup and whenever server config changes.
   */
  async syncFromConfig(): Promise<void> {
    const url = await getServerBaseUrl();
    this.setBaseUrl(url);
  }

  // ─── Internal helpers ─────────────────────────────────────────────────────

  private headers(): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.authToken) h['Authorization'] = `Bearer ${this.authToken}`;
    return h;
  }

  private authHeaders(): Record<string, string> {
    const h: Record<string, string> = {};
    if (this.authToken) h['Authorization'] = `Bearer ${this.authToken}`;
    return h;
  }

  private async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async patch<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'PATCH',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async put<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'PUT',
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async del<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'DELETE',
      headers: this.authHeaders(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async postFormData<T>(path: string, formData: FormData): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this.authHeaders(), // No Content-Type — browser sets multipart boundary
      body: formData,
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  // ─── Health / Status ──────────────────────────────────────────────────────

  /** GET /health — basic liveness check */
  async healthCheck(): Promise<HealthResponse> {
    return this.get('/health');
  }

  /** GET /ready — model readiness */
  async getReadiness(): Promise<ReadyResponse> {
    return this.get('/ready');
  }

  /** GET /api/status — detailed server status */
  async getStatus(): Promise<ServerStatus> {
    return this.get('/api/status');
  }

  /**
   * Combined connectivity check — returns a summary of server state.
   * Does not throw; returns an error state object on failure.
   */
  async checkConnection(): Promise<{
    reachable: boolean;
    ready: boolean;
    status: ServerStatus | null;
    error: string | null;
  }> {
    try {
      await this.healthCheck();
    } catch {
      return { reachable: false, ready: false, status: null, error: 'Server unreachable' };
    }
    try {
      const [readiness, status] = await Promise.all([
        this.getReadiness(),
        this.getStatus(),
      ]);
      return {
        reachable: true,
        ready: readiness.status === 'ready',
        status,
        error: null,
      };
    } catch (err) {
      return {
        reachable: true,
        ready: false,
        status: null,
        error: err instanceof Error ? err.message : 'Unknown error',
      };
    }
  }

  // ─── Auth ─────────────────────────────────────────────────────────────────

  /** POST /api/auth/login */
  async login(token: string): Promise<LoginResponse> {
    const body: LoginRequest = { token };
    return this.post('/api/auth/login', body);
  }

  /** GET /api/auth/tokens — admin only */
  async listTokens(): Promise<{ tokens: AuthToken[] }> {
    return this.get('/api/auth/tokens');
  }

  /** POST /api/auth/tokens — admin only */
  async createToken(req: CreateTokenRequest): Promise<{ success: boolean; message: string; token: AuthToken }> {
    return this.post('/api/auth/tokens', req);
  }

  /** DELETE /api/auth/tokens/:id — admin only */
  async revokeToken(tokenId: string): Promise<{ success: boolean }> {
    return this.del(`/api/auth/tokens/${tokenId}`);
  }

  // ─── Transcription ────────────────────────────────────────────────────────

  /** POST /api/transcribe/audio — transcribe an uploaded file */
  async transcribeAudio(file: File, options?: TranscriptionUploadOptions): Promise<TranscriptionResponse> {
    const fd = new FormData();
    fd.append('file', file);
    if (options?.language) fd.append('language', options.language);
    if (options?.translation_enabled) fd.append('translation_enabled', 'true');
    if (options?.translation_target_language) fd.append('translation_target_language', options.translation_target_language);
    if (options?.enable_word_timestamps !== undefined) fd.append('word_timestamps', String(options.enable_word_timestamps));
    if (options?.enable_diarization) fd.append('diarization', 'true');
    if (options?.expected_speakers) fd.append('expected_speakers', String(options.expected_speakers));
    return this.postFormData('/api/transcribe/audio', fd);
  }

  /** POST /api/transcribe/quick — quick transcription, text only */
  async transcribeQuick(file: File, language?: string): Promise<TranscriptionResponse> {
    const fd = new FormData();
    fd.append('file', file);
    if (language) fd.append('language', language);
    return this.postFormData('/api/transcribe/quick', fd);
  }

  /** POST /api/transcribe/cancel */
  async cancelTranscription(): Promise<TranscriptionCancelResponse> {
    return this.post('/api/transcribe/cancel');
  }

  /** GET /api/transcribe/languages */
  async getLanguages(): Promise<LanguagesResponse> {
    return this.get('/api/transcribe/languages');
  }

  // ─── Notebook: Recordings ─────────────────────────────────────────────────

  /** GET /api/notebook/recordings */
  async listRecordings(startDate?: string, endDate?: string): Promise<Recording[]> {
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const qs = params.toString();
    return this.get(`/api/notebook/recordings${qs ? `?${qs}` : ''}`);
  }

  /** GET /api/notebook/recordings/:id */
  async getRecording(id: number): Promise<RecordingDetail> {
    return this.get(`/api/notebook/recordings/${id}`);
  }

  /** DELETE /api/notebook/recordings/:id */
  async deleteRecording(id: number): Promise<{ status: string; id: string }> {
    return this.del(`/api/notebook/recordings/${id}`);
  }

  /** PATCH /api/notebook/recordings/:id/title */
  async updateRecordingTitle(id: number, title: string): Promise<{ status: string; id: number; title: string }> {
    return this.patch(`/api/notebook/recordings/${id}/title`, { title });
  }

  /** PATCH /api/notebook/recordings/:id/summary */
  async updateRecordingSummary(
    id: number,
    summary?: string,
    summaryModel?: string,
  ): Promise<{ status: string; id: number; summary: string | null; summary_model: string | null }> {
    return this.patch(`/api/notebook/recordings/${id}/summary`, {
      summary,
      summary_model: summaryModel,
    });
  }

  /** PUT /api/notebook/recordings/:id/summary — query-param variant */
  async setRecordingSummary(
    id: number,
    summary: string,
    summaryModel?: string,
  ): Promise<{ status: string; id: number; summary: string; summary_model: string | null }> {
    const params = new URLSearchParams({ summary });
    if (summaryModel) params.set('summary_model', summaryModel);
    return this.put(`/api/notebook/recordings/${id}/summary?${params.toString()}`);
  }

  /** GET /api/notebook/recordings/:id/transcription */
  async getRecordingTranscription(id: number): Promise<RecordingTranscription> {
    return this.get(`/api/notebook/recordings/${id}/transcription`);
  }

  /**
   * GET /api/notebook/recordings/:id/audio
   * Returns the audio URL for streaming playback (not fetched — use as <audio> src).
   */
  getAudioUrl(id: number): string {
    const tokenParam = this.authToken ? `?token=${encodeURIComponent(this.authToken)}` : '';
    return `${this.baseUrl}/api/notebook/recordings/${id}/audio${tokenParam}`;
  }

  /**
   * GET /api/notebook/recordings/:id/export
   * Returns a download URL (not fetched directly).
   */
  getExportUrl(id: number, format: ExportFormat): string {
    const params = new URLSearchParams({ format });
    if (this.authToken) params.set('token', this.authToken);
    return `${this.baseUrl}/api/notebook/recordings/${id}/export?${params}`;
  }

  // ─── Notebook: Upload & Transcribe ────────────────────────────────────────

  /**
   * POST /api/notebook/transcribe/upload
   * Upload audio, transcribe, and save to notebook in one step.
   */
  async uploadAndTranscribe(file: File, options?: TranscriptionUploadOptions): Promise<UploadResponse> {
    const fd = new FormData();
    fd.append('file', file);
    if (options?.language) fd.append('language', options.language);
    if (options?.translation_enabled) fd.append('translation_enabled', 'true');
    if (options?.translation_target_language) fd.append('translation_target_language', options.translation_target_language);
    if (options?.enable_diarization) fd.append('enable_diarization', 'true');
    if (options?.enable_word_timestamps !== undefined) fd.append('enable_word_timestamps', String(options.enable_word_timestamps));
    if (options?.expected_speakers) fd.append('expected_speakers', String(options.expected_speakers));
    if (options?.file_created_at) fd.append('file_created_at', options.file_created_at);
    return this.postFormData('/api/notebook/transcribe/upload', fd);
  }

  // ─── Notebook: Calendar & Timeslot ────────────────────────────────────────

  /** GET /api/notebook/calendar?year=&month= */
  async getCalendar(year: number, month: number): Promise<CalendarResponse> {
    return this.get(`/api/notebook/calendar?year=${year}&month=${month}`);
  }

  /** GET /api/notebook/timeslot?date=&hour= */
  async getTimeslot(date: string, hour: number): Promise<TimeslotResponse> {
    return this.get(`/api/notebook/timeslot?date=${date}&hour=${hour}`);
  }

  // ─── Notebook: Backups ────────────────────────────────────────────────────

  /** GET /api/notebook/backups */
  async listBackups(): Promise<BackupsResponse> {
    return this.get('/api/notebook/backups');
  }

  /** POST /api/notebook/backup */
  async createBackup(): Promise<BackupCreateResponse> {
    return this.post('/api/notebook/backup');
  }

  /** POST /api/notebook/restore */
  async restoreBackup(filename: string): Promise<RestoreResponse> {
    return this.post('/api/notebook/restore', { filename });
  }

  // ─── Search ───────────────────────────────────────────────────────────────

  /** GET /api/search/ — unified search */
  async search(
    query: string,
    options?: { fuzzy?: boolean; startDate?: string; endDate?: string; limit?: number },
  ): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query });
    if (options?.fuzzy) params.set('fuzzy', 'true');
    if (options?.startDate) params.set('start_date', options.startDate);
    if (options?.endDate) params.set('end_date', options.endDate);
    if (options?.limit) params.set('limit', String(options.limit));
    return this.get(`/api/search/?${params}`);
  }

  /** GET /api/search/words */
  async searchWords(query: string, limit?: number): Promise<WordSearchResponse> {
    const params = new URLSearchParams({ q: query });
    if (limit) params.set('limit', String(limit));
    return this.get(`/api/search/words?${params}`);
  }

  /** GET /api/search/recordings */
  async searchRecordings(query: string, limit?: number): Promise<WordSearchResponse> {
    const params = new URLSearchParams({ q: query });
    if (limit) params.set('limit', String(limit));
    return this.get(`/api/search/recordings?${params}`);
  }

  // ─── Admin ────────────────────────────────────────────────────────────────

  /** GET /api/admin/status */
  async getAdminStatus(): Promise<AdminStatus> {
    return this.get('/api/admin/status');
  }

  /** POST /api/admin/models/load */
  async loadModels(): Promise<{ status: string }> {
    return this.post('/api/admin/models/load');
  }

  /**
   * WS /api/admin/models/load/stream — load models with progress streaming.
   *
   * Returns a cleanup function. Callbacks fire as the server sends progress:
   *   { type: 'progress', message: string }
   *   { type: 'complete', status: 'loaded' }
   *   { type: 'error', message: string }
   */
  loadModelsStream(callbacks: {
    onProgress?: (message: string) => void;
    onComplete?: () => void;
    onError?: (message: string) => void;
  }): () => void {
    const wsProto = this.baseUrl.startsWith('https') ? 'wss' : 'ws';
    const wsBase = this.baseUrl.replace(/^https?/, wsProto);
    const url = `${wsBase}/api/admin/models/load/stream`;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      // Auth via first message if we have a token
      if (this.authToken) {
        ws.send(JSON.stringify({ type: 'auth', token: this.authToken }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'progress':
            callbacks.onProgress?.(msg.message ?? '');
            break;
          case 'complete':
            callbacks.onComplete?.();
            ws.close();
            break;
          case 'error':
            callbacks.onError?.(msg.message ?? 'Model loading failed');
            ws.close();
            break;
        }
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onerror = () => {
      callbacks.onError?.('WebSocket connection error');
    };

    ws.onclose = () => {
      // No-op — cleanup handled by caller
    };

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }

  /** POST /api/admin/models/unload */
  async unloadModels(): Promise<{ status: string }> {
    return this.post('/api/admin/models/unload');
  }

  /** GET /api/admin/logs */
  async getLogs(service?: string, level?: string): Promise<LogsResponse> {
    const params = new URLSearchParams();
    if (service) params.set('service', service);
    if (level) params.set('level', level);
    const qs = params.toString();
    return this.get(`/api/admin/logs${qs ? `?${qs}` : ''}`);
  }

  // ─── LLM ──────────────────────────────────────────────────────────────────

  /** GET /api/llm/status */
  async getLLMStatus(): Promise<LLMStatus> {
    return this.get('/api/llm/status');
  }

  /** POST /api/llm/process — non-streaming */
  async llmProcess(request: LLMRequest): Promise<LLMResponse> {
    return this.post('/api/llm/process', request);
  }

  /**
   * POST /api/llm/process/stream — SSE streaming.
   * Returns an async generator yielding content chunks.
   */
  async *llmProcessStream(request: LLMRequest): AsyncGenerator<string, void, unknown> {
    const res = await fetch(`${this.baseUrl}/api/llm/process/stream`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), '/api/llm/process/stream');
    yield* this.readSSE(res);
  }

  /** POST /api/llm/summarize/:recordingId — non-streaming */
  async summarizeRecording(recordingId: number, customPrompt?: string): Promise<LLMResponse> {
    const params = customPrompt ? `?custom_prompt=${encodeURIComponent(customPrompt)}` : '';
    return this.post(`/api/llm/summarize/${recordingId}${params}`);
  }

  /**
   * POST /api/llm/summarize/:recordingId/stream — SSE streaming.
   * Returns an async generator yielding content chunks.
   */
  async *summarizeRecordingStream(recordingId: number, customPrompt?: string): AsyncGenerator<string, void, unknown> {
    const params = customPrompt ? `?custom_prompt=${encodeURIComponent(customPrompt)}` : '';
    const res = await fetch(`${this.baseUrl}/api/llm/summarize/${recordingId}/stream${params}`, {
      method: 'POST',
      headers: this.headers(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), `/api/llm/summarize/${recordingId}/stream`);
    yield* this.readSSE(res);
  }

  /** POST /api/llm/server/start */
  async startLLMServer(): Promise<ServerControlResponse> {
    return this.post('/api/llm/server/start');
  }

  /** POST /api/llm/server/stop */
  async stopLLMServer(): Promise<ServerControlResponse> {
    return this.post('/api/llm/server/stop');
  }

  /** GET /api/llm/models/available */
  async listLLMModels(): Promise<LLMModelsResponse> {
    return this.get('/api/llm/models/available');
  }

  /** GET /api/llm/models/loaded */
  async getLoadedLLMModels(): Promise<{ success: boolean; output?: string; error?: string }> {
    return this.get('/api/llm/models/loaded');
  }

  /** POST /api/llm/model/load */
  async loadLLMModel(modelId?: string, gpuOffload?: number, contextLength?: number): Promise<ServerControlResponse> {
    return this.post('/api/llm/model/load', {
      model_id: modelId,
      gpu_offload: gpuOffload,
      context_length: contextLength,
    });
  }

  /** POST /api/llm/model/unload */
  async unloadLLMModel(instanceId?: string): Promise<ServerControlResponse> {
    const params = instanceId ? `?instance_id=${encodeURIComponent(instanceId)}` : '';
    return this.post(`/api/llm/model/unload${params}`);
  }

  // ─── LLM: Conversations ──────────────────────────────────────────────────

  /** GET /api/llm/conversations/:recordingId */
  async listConversations(recordingId: number): Promise<{ conversations: Conversation[] }> {
    return this.get(`/api/llm/conversations/${recordingId}`);
  }

  /** POST /api/llm/conversations */
  async createConversation(recordingId: number, title?: string): Promise<{ conversation_id: number; title: string }> {
    return this.post('/api/llm/conversations', { recording_id: recordingId, title });
  }

  /** GET /api/llm/conversation/:id */
  async getConversation(conversationId: number): Promise<Conversation> {
    return this.get(`/api/llm/conversation/${conversationId}`);
  }

  /** PATCH /api/llm/conversation/:id */
  async updateConversation(conversationId: number, title: string): Promise<{ success: boolean; title: string }> {
    return this.patch(`/api/llm/conversation/${conversationId}`, { title });
  }

  /** DELETE /api/llm/conversation/:id */
  async deleteConversation(conversationId: number): Promise<{ success: boolean }> {
    return this.del(`/api/llm/conversation/${conversationId}`);
  }

  /** POST /api/llm/conversation/:id/message */
  async addMessage(
    conversationId: number,
    role: 'user' | 'assistant',
    content: string,
    model?: string,
    tokensUsed?: number,
  ): Promise<{ message_id: number }> {
    return this.post(`/api/llm/conversation/${conversationId}/message`, {
      role,
      content,
      model,
      tokens_used: tokensUsed,
    });
  }

  /**
   * POST /api/llm/chat — SSE streaming chat.
   * Returns an async generator yielding content chunks.
   */
  async *chat(request: {
    conversation_id: number;
    user_message: string;
    system_prompt?: string;
    include_transcription?: boolean;
    max_tokens?: number;
    temperature?: number;
  }): AsyncGenerator<string, void, unknown> {
    const res = await fetch(`${this.baseUrl}/api/llm/chat`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), '/api/llm/chat');
    yield* this.readSSE(res);
  }

  // ─── SSE helper ───────────────────────────────────────────────────────────

  private async *readSSE(res: Response): AsyncGenerator<string, void, unknown> {
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6).trim();
          if (!data || data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            if (parsed.done) return;
            if (parsed.error) throw new Error(parsed.error);
            if (parsed.content) yield parsed.content;
          } catch (e) {
            if (e instanceof SyntaxError) continue; // Skip malformed JSON
            throw e;
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

// ─── Error class ──────────────────────────────────────────────────────────────

export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
    public readonly path: string,
  ) {
    super(`API ${status} on ${path}`);
    this.name = 'APIError';
  }
}

// ─── Singleton ────────────────────────────────────────────────────────────────

/** Singleton API client instance */
export const apiClient = new APIClient();

/**
 * Initialize the API client from stored config.
 * Call once at app startup (e.g. in App.tsx useEffect).
 */
export async function initApiClient(): Promise<void> {
  await apiClient.syncFromConfig();
}
