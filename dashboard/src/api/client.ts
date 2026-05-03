/**
 * API client for TranscriptionSuite server.
 * Covers all REST endpoints; WebSocket connections are handled separately.
 */

import {
  DEFAULT_SERVER_PORT,
  getAuthToken,
  getServerBaseUrl,
  isServerUrlConfigured,
} from '../config/store';
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
  TranscriptionAccepted,
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

// ─── Profiles types (Issue #104, Story 1.2) ──────────────────────────────────

export interface ProfilePublicFields {
  filename_template: string;
  destination_folder: string;
  auto_summary_enabled: boolean;
  auto_export_enabled: boolean;
  summary_model_id: string | null;
  summary_prompt_template: string | null;
  export_format: string;
}

export interface Profile {
  id: number;
  name: string;
  description: string | null;
  schema_version: string;
  public_fields: ProfilePublicFields;
  created_at: string;
  updated_at: string;
}

export interface ProfileCreatePayload {
  name: string;
  description?: string | null;
  schema_version?: string;
  public_fields: ProfilePublicFields;
  /** Plaintext private fields — sent over the wire ONCE; persisted via keychain server-side. */
  private_fields?: Record<string, string>;
}

export interface ProfileUpdatePayload {
  name?: string;
  description?: string | null;
  schema_version?: string;
  public_fields?: ProfilePublicFields;
  private_fields?: Record<string, string>;
}

export class APIClient {
  private baseUrl: string;
  private authToken: string | null = null;
  private synced: boolean = false;
  // Listeners notified after any syncFromConfig() attempt — success OR failure.
  // Consumers (socket-owning hooks) re-check predicate state on event because
  // a failed sync still mutates the gate from "pre-sync" to "post-sync-failed".
  private configChangedListeners = new Set<() => void>();

  constructor(baseUrl: string = `http://localhost:${DEFAULT_SERVER_PORT}`) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  /**
   * Subscribe to config-changed events fired after every `syncFromConfig()`
   * attempt (both success and failure paths). Returns an unsubscribe function
   * suitable as a React `useEffect` cleanup. Used by `useTranscription` and
   * `useLiveMode` to rearm WebSockets stuck in `error` state after the user
   * fixes Settings mid-session.
   */
  onConfigChanged(listener: () => void): () => void {
    this.configChangedListeners.add(listener);
    return () => {
      this.configChangedListeners.delete(listener);
    };
  }

  private emitConfigChanged(): void {
    // Snapshot the Set before iteration so a listener that unsubscribes a
    // not-yet-visited sibling (directly or transitively) doesn't silently
    // drop that sibling from this emit cycle. Set.prototype iteration is
    // otherwise safe against deletion of the CURRENT item, but deletion of
    // a later-scheduled item WILL skip it.
    for (const listener of [...this.configChangedListeners]) {
      try {
        listener();
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        console.warn('[APIClient] config-changed listener threw:', detail);
      }
    }
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
   * Sets the `synced` flag — a precondition for isBaseUrlConfigured().
   *
   * Throw-safety: catches any throw from `getServerBaseUrl()` (preload-bridge
   * rejection, localStorage QuotaExceededError, etc.). On throw, `synced`
   * stays false so the existing `isBaseUrlConfigured()` gate stays closed and
   * downstream network paths short-circuit safely. Always emits
   * `config-changed` so subscribers can re-check gate state regardless of
   * whether the sync succeeded.
   */
  async syncFromConfig(): Promise<void> {
    try {
      const url = await getServerBaseUrl();
      this.setBaseUrl(url);
      this.synced = true;
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      console.warn('[APIClient] syncFromConfig failed:', detail);
      // synced stays false on throw — isBaseUrlConfigured() returns false,
      // network paths gate via `'remote-host-not-configured'`. Caller is
      // shielded from the unhandled rejection that previously crashed
      // App.tsx's fire-and-forget initApiClient and the SessionView /
      // SettingsModal callbacks.
    }
    this.emitConfigChanged();
  }

  /**
   * Sync predicate — returns true iff syncFromConfig() has completed at least
   * once AND the current baseUrl parses with a non-empty hostname. Network-path
   * helpers gate on this to prevent (a) pre-sync stealth-localhost probes on
   * pure-remote users and (b) post-sync malformed-URL fallout from the loud-fail
   * `http://:<port>` shape that getServerBaseUrl emits for blank-remote.
   * Spec: _bmad-output/implementation-artifacts/spec-in-app-update-renderer-network-paths-install-gate.md
   */
  isBaseUrlConfigured(): boolean {
    if (!this.synced) return false;
    try {
      const u = new URL(this.baseUrl);
      return u.hostname.length > 0;
    } catch {
      return false;
    }
  }

  // ─── Internal helpers ─────────────────────────────────────────────────────

  private ensureConfigured(path: string): void {
    if (!this.isBaseUrlConfigured()) {
      throw new APIError(0, 'remote-host-not-configured', path);
    }
  }

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
    this.ensureConfigured(path);
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    this.ensureConfigured(path);
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async patch<T>(path: string, body: unknown): Promise<T> {
    this.ensureConfigured(path);
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'PATCH',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async put<T>(path: string, body?: unknown): Promise<T> {
    this.ensureConfigured(path);
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'PUT',
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async del<T>(path: string): Promise<T> {
    this.ensureConfigured(path);
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'DELETE',
      headers: this.authHeaders(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), path);
    return res.json();
  }

  private async postFormData<T>(path: string, formData: FormData): Promise<T> {
    this.ensureConfigured(path);
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
   * Uses a single GET /api/status request whose ``ready`` field
   * consolidates the old /health + /ready + /api/status triple.
   * Does not throw; returns an error state object on failure.
   *
   * When running in Electron, performs a main-process IPC probe first.
   * Node.js gives specific error codes (ENOTFOUND, ECONNREFUSED,
   * ERR_TLS_CERT_ALTNAME_INVALID, etc.) that Chromium's renderer
   * `fetch()` can never expose.  If the probe fails, the specific error
   * is returned immediately.  If it succeeds, the normal `fetch()`
   * call proceeds to obtain the full /api/status payload.
   */
  async checkConnection(): Promise<{
    reachable: boolean;
    ready: boolean;
    status: ServerStatus | null;
    error: string | null;
  }> {
    // Short-circuit before any probe when useRemote=true with a blank
    // active-profile host. Renderer parity with electron/appState.ts's
    // isAppIdle → isServerUrlConfigured gate: surfaces a diagnostic
    // `'remote-host-not-configured'` reason instead of probing the
    // malformed `http://:<port>` URL that getServerBaseUrl now emits
    // for blank-remote.
    // Spec: _bmad-output/implementation-artifacts/spec-in-app-update-remote-host-validation-renderer.md
    //
    // Throw-safety: `isServerUrlConfigured()` reads config via the preload
    // IPC bridge; a preload rejection or a localStorage-fallback
    // QuotaExceededError can propagate as an uncaught throw. This
    // function's docstring promises "Does not throw" — without this
    // try/catch, a config-read failure would crash polling hooks
    // (useServerStatus, useAdminStatus) with unhandled rejections.
    let configured: boolean;
    try {
      configured = await isServerUrlConfigured();
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      console.warn('[APIClient] config-read failed in checkConnection:', detail);
      return {
        reachable: false,
        ready: false,
        status: null,
        error: 'config-read-failed',
      };
    }
    if (!configured) {
      return {
        reachable: false,
        ready: false,
        status: null,
        error: 'remote-host-not-configured',
      };
    }
    // In Electron, probe via main process first for specific error diagnostics.
    const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined;
    if (electronAPI?.server?.probeConnection) {
      try {
        // Determine whether to skip cert verification (LAN profile)
        const remoteProfile = await electronAPI.config?.get?.('connection.remoteProfile');
        const useRemote = await electronAPI.config?.get?.('connection.useRemote');
        const skipCertVerify = useRemote === true && remoteProfile === 'lan';

        console.debug('[APIClient] Probing', this.baseUrl, '(skipCertVerify:', skipCertVerify, ')');

        const probe = await electronAPI.server.probeConnection(
          `${this.baseUrl}/api/status`,
          skipCertVerify,
        );

        console.debug('[APIClient] Probe result:', {
          ok: probe.ok,
          httpStatus: probe.httpStatus,
          error: probe.error,
          hasBody: !!probe.body,
        });

        if (!probe.ok) {
          // For TLS-specific errors, fall through to fetch() — the renderer's
          // certificate-error handler can accept certs that Node.js rejected
          // (e.g. hostname mismatch for LAN profile).  For connectivity errors
          // (DNS, refused, timeout) return immediately — fetch would also fail.
          // Only fall through to renderer fetch for TLS errors that the
          // certificate-error handler in main.ts *can* accept (LAN profile).
          // CERT_HAS_EXPIRED is excluded: an expired cert cannot be accepted
          // by any handler — the probe's specific error should surface.
          const tlsFallbackCodes = new Set([
            'ERR_TLS_CERT_ALTNAME_INVALID',
            'DEPTH_ZERO_SELF_SIGNED_CERT',
            'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
            'ERR_TLS_CERT_AUTHORITY_INVALID',
          ]);
          if (!probe.errorCode || !tlsFallbackCodes.has(probe.errorCode)) {
            console.warn('[APIClient] Probe failed (non-TLS), returning early:', probe.error);
            return {
              reachable: false,
              ready: false,
              status: null,
              error: probe.error ?? 'Server unreachable',
            };
          }
          // TLS error → fall through to renderer fetch (certificate-error handler may accept)
          console.debug(
            '[APIClient] TLS error from probe, falling through to renderer fetch:',
            probe.errorCode,
          );
        }

        // If probe succeeded and returned a body, try to use it directly
        // to avoid a redundant second fetch() that CSP might block.
        if (probe.ok && probe.body) {
          try {
            const status = JSON.parse(probe.body) as ServerStatus;
            console.debug('[APIClient] Connected via probe body, ready:', status.ready);
            return {
              reachable: true,
              ready: status.ready === true,
              status,
              error: null,
            };
          } catch {
            // Body parse failed — fall through to normal fetch
            console.debug('[APIClient] Probe body parse failed, falling through to fetch');
          }
        }
      } catch {
        // Probe IPC failed — fall through to normal fetch
        console.warn('[APIClient] Probe IPC call failed, falling through to fetch');
      }
    }

    try {
      console.debug('[APIClient] Fetching /api/status via renderer fetch()');
      const status = await this.getStatus();
      console.debug('[APIClient] Fetch succeeded, ready:', status.ready);
      return {
        reachable: true,
        ready: status.ready === true,
        status,
        error: null,
      };
    } catch (err: unknown) {
      // Distinguish HTTP errors (server reachable) from network errors
      if (err instanceof APIError) {
        if (err.status === 401 || err.status === 403) {
          return {
            reachable: true,
            ready: false,
            status: null,
            error: `Authentication required (${err.status})`,
          };
        }
        return {
          reachable: true,
          ready: false,
          status: null,
          error: `Server error (${err.status})`,
        };
      }
      // Network-level failure — classify for user-friendly messages.
      // Order matters: specific patterns first, generic fallback last.
      // Note: Chromium's "Failed to fetch" is generic and covers DNS, TLS,
      // refused, timeout — it falls through to the default "Server unreachable".
      const msg = err instanceof Error ? err.message : 'Unknown error';
      console.warn('[APIClient] Fetch failed:', msg);
      let detail = 'Server unreachable';
      if (/ERR_NAME_NOT_RESOLVED|ENOTFOUND|getaddrinfo/i.test(msg)) {
        detail = 'DNS lookup failed — check hostname';
      } else if (/ERR_CERT|CERT_|certificate|ssl|tls|self.signed/i.test(msg)) {
        detail = 'TLS certificate error — check server certificates';
      } else if (/ERR_CONNECTION_REFUSED|ECONNREFUSED/i.test(msg)) {
        detail = 'Connection refused — is the server running?';
      } else if (/timeout|ETIMEDOUT|ERR_CONNECTION_TIMED_OUT/i.test(msg)) {
        detail = 'Connection timed out';
      }
      return { reachable: false, ready: false, status: null, error: detail };
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
  async createToken(
    req: CreateTokenRequest,
  ): Promise<{ success: boolean; message: string; token: AuthToken }> {
    return this.post('/api/auth/tokens', req);
  }

  /** DELETE /api/auth/tokens/:id — admin only */
  async revokeToken(tokenId: string): Promise<{ success: boolean }> {
    return this.del(`/api/auth/tokens/${tokenId}`);
  }

  // ─── Transcription ────────────────────────────────────────────────────────

  /** POST /api/transcribe/audio — transcribe an uploaded file */
  async transcribeAudio(
    file: File,
    options?: TranscriptionUploadOptions,
  ): Promise<TranscriptionResponse> {
    const fd = new FormData();
    fd.append('file', file);
    if (options?.language) fd.append('language', options.language);
    if (options?.translation_enabled) fd.append('translation_enabled', 'true');
    if (options?.translation_target_language)
      fd.append('translation_target_language', options.translation_target_language);
    if (options?.enable_word_timestamps !== undefined)
      fd.append('word_timestamps', String(options.enable_word_timestamps));
    if (options?.enable_diarization) fd.append('diarization', 'true');
    if (options?.expected_speakers)
      fd.append('expected_speakers', String(options.expected_speakers));
    if (options?.multitrack) fd.append('multitrack', 'true');
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
  async updateRecordingTitle(
    id: number,
    title: string,
  ): Promise<{ status: string; id: number; title: string }> {
    return this.patch(`/api/notebook/recordings/${id}/title`, { title });
  }

  /** PATCH /api/notebook/recordings/:id/date */
  async updateRecordingDate(
    id: number,
    recordedAt: string,
  ): Promise<{ status: string; id: number; recorded_at: string }> {
    return this.patch(`/api/notebook/recordings/${id}/date`, { recorded_at: recordedAt });
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
   * Returns null when the base URL is not configured (pre-sync or blank-remote);
   * callers must guard and skip playback rather than pass a broken src.
   */
  getAudioUrl(id: number): string | null {
    if (!this.isBaseUrlConfigured()) return null;
    const tokenParam = this.authToken ? `?token=${encodeURIComponent(this.authToken)}` : '';
    return `${this.baseUrl}/api/notebook/recordings/${id}/audio${tokenParam}`;
  }

  /**
   * GET /api/notebook/recordings/:id/export
   * Returns a download URL (not fetched directly).
   * Returns null when the base URL is not configured (pre-sync or blank-remote);
   * callers must guard and surface an error rather than open a broken URL.
   */
  getExportUrl(id: number, format: ExportFormat): string | null {
    if (!this.isBaseUrlConfigured()) return null;
    const params = new URLSearchParams({ format });
    if (this.authToken) params.set('token', this.authToken);
    return `${this.baseUrl}/api/notebook/recordings/${id}/export?${params}`;
  }

  // ─── Notebook: Upload & Transcribe ────────────────────────────────────────

  /**
   * POST /api/notebook/transcribe/upload
   * Upload audio and start background transcription.
   * Returns 202 with job_id immediately. Poll /api/admin/status for result.
   */
  async uploadAndTranscribe(
    file: File,
    options?: TranscriptionUploadOptions,
  ): Promise<TranscriptionAccepted> {
    const fd = new FormData();
    fd.append('file', file);
    if (options?.language) fd.append('language', options.language);
    if (options?.translation_enabled) fd.append('translation_enabled', 'true');
    if (options?.translation_target_language)
      fd.append('translation_target_language', options.translation_target_language);
    if (options?.enable_diarization) fd.append('enable_diarization', 'true');
    if (options?.enable_word_timestamps !== undefined)
      fd.append('enable_word_timestamps', String(options.enable_word_timestamps));
    if (options?.expected_speakers)
      fd.append('expected_speakers', String(options.expected_speakers));
    if (options?.parallel_diarization !== undefined)
      fd.append('parallel_diarization', String(options.parallel_diarization));
    if (options?.multitrack) fd.append('multitrack', 'true');
    if (options?.file_created_at) fd.append('file_created_at', options.file_created_at);
    if (options?.title) fd.append('title', options.title);
    return this.postFormData('/api/notebook/transcribe/upload', fd);
  }

  // ─── File Import (Session) ────────────────────────────────────────────────

  /**
   * POST /api/transcribe/import — start a background file-import transcription.
   * Returns 202 Accepted with { job_id }. Poll /api/admin/status for result.
   */
  async importAndTranscribe(
    file: File,
    options?: Omit<TranscriptionUploadOptions, 'file_created_at' | 'title'>,
  ): Promise<TranscriptionAccepted> {
    const fd = new FormData();
    fd.append('file', file);
    if (options?.language) fd.append('language', options.language);
    if (options?.translation_enabled) fd.append('translation_enabled', 'true');
    if (options?.translation_target_language)
      fd.append('translation_target_language', options.translation_target_language);
    if (options?.enable_diarization) fd.append('enable_diarization', 'true');
    if (options?.enable_word_timestamps !== undefined)
      fd.append('enable_word_timestamps', String(options.enable_word_timestamps));
    if (options?.expected_speakers)
      fd.append('expected_speakers', String(options.expected_speakers));
    if (options?.parallel_diarization !== undefined)
      fd.append('parallel_diarization', String(options.parallel_diarization));
    if (options?.multitrack) fd.append('multitrack', 'true');
    return this.postFormData('/api/transcribe/import', fd);
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
    if (!this.isBaseUrlConfigured()) {
      callbacks.onError?.('remote-host-not-configured');
      return () => {
        /* no-op: connection was never opened */
      };
    }
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

  /** PATCH /api/admin/diarization */
  async updateDiarizationSettings(settings: {
    parallel: boolean;
  }): Promise<{ status: string; diarization: { parallel: boolean } }> {
    return this.patch('/api/admin/diarization', settings);
  }

  // ─── Webhook ─────────────────────────────────────────────────────────────

  /** POST /api/admin/webhook/test — send a test webhook to the configured URL */
  async testWebhook(
    url?: string,
    secret?: string,
  ): Promise<{ success: boolean; status_code: number | null; message: string }> {
    const body: Record<string, string> = {};
    if (url) body.url = url;
    if (secret) body.secret = secret;
    return this.post('/api/admin/webhook/test', Object.keys(body).length ? body : undefined);
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
    this.ensureConfigured('/api/llm/process/stream');
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
  async *summarizeRecordingStream(
    recordingId: number,
    customPrompt?: string,
  ): AsyncGenerator<string, void, unknown> {
    this.ensureConfigured(`/api/llm/summarize/${recordingId}/stream`);
    const params = customPrompt ? `?custom_prompt=${encodeURIComponent(customPrompt)}` : '';
    const res = await fetch(`${this.baseUrl}/api/llm/summarize/${recordingId}/stream${params}`, {
      method: 'POST',
      headers: this.headers(),
    });
    if (!res.ok)
      throw new APIError(res.status, await res.text(), `/api/llm/summarize/${recordingId}/stream`);
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

  /** POST /api/llm/config/reload — tell the server to reload config from disk */
  async reloadServerConfig(): Promise<void> {
    await this.post('/api/llm/config/reload');
  }

  /** DELETE /api/llm/conversation/:id/messages-from/:msgId — truncate history */
  async deleteMessagesFrom(
    conversationId: number,
    messageId: number,
  ): Promise<{ deleted: number }> {
    return this.del(`/api/llm/conversation/${conversationId}/messages-from/${messageId}`);
  }

  /** POST /api/llm/conversation/:id/generate-title — LLM-generated ≤8-word title */
  async generateConversationTitle(conversationId: number): Promise<{ title: string }> {
    return this.post(`/api/llm/conversation/${conversationId}/generate-title`);
  }

  /** GET /api/llm/models — list models from the configured AI provider */
  async getAvailableModels(): Promise<LLMModelsResponse> {
    return this.get('/api/llm/models');
  }

  /** GET /api/llm/models/available (LM Studio-specific) */
  async listLLMModels(): Promise<LLMModelsResponse> {
    return this.get('/api/llm/models/available');
  }

  /** GET /api/llm/models/loaded */
  async getLoadedLLMModels(): Promise<{ success: boolean; output?: string; error?: string }> {
    return this.get('/api/llm/models/loaded');
  }

  /** POST /api/llm/model/load */
  async loadLLMModel(
    modelId?: string,
    gpuOffload?: number,
    contextLength?: number,
  ): Promise<ServerControlResponse> {
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
  async createConversation(
    recordingId: number,
    title?: string,
    model?: string,
  ): Promise<{ conversation_id: number; title: string; model?: string | null }> {
    return this.post('/api/llm/conversations', { recording_id: recordingId, title, model });
  }

  /** GET /api/llm/conversation/:id */
  async getConversation(conversationId: number): Promise<Conversation> {
    return this.get(`/api/llm/conversation/${conversationId}`);
  }

  /** PATCH /api/llm/conversation/:id */
  async updateConversation(
    conversationId: number,
    updates: { title?: string; model?: string | null },
  ): Promise<{ success: boolean; title: string; model?: string | null }> {
    return this.patch(`/api/llm/conversation/${conversationId}`, updates);
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
    model?: string;
  }): AsyncGenerator<string, void, unknown> {
    this.ensureConfigured('/api/llm/chat');
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

  // ── Profiles (Issue #104, Story 1.2) ────────────────────────────────────
  async listProfiles(): Promise<Profile[]> {
    return this.get<Profile[]>('/api/profiles');
  }
  async getProfile(id: number): Promise<Profile> {
    return this.get<Profile>(`/api/profiles/${id}`);
  }
  async createProfile(payload: ProfileCreatePayload): Promise<Profile> {
    return this.post<Profile>('/api/profiles', payload);
  }
  async updateProfile(id: number, payload: ProfileUpdatePayload): Promise<Profile> {
    return this.put<Profile>(`/api/profiles/${id}`, payload);
  }
  async deleteProfile(id: number): Promise<void> {
    // Server returns 204 No Content; the private del<T> would try to .json()
    // an empty body. Inline the fetch for the no-content case.
    this.ensureConfigured(`/api/profiles/${id}`);
    const res = await fetch(`${this.baseUrl}/api/profiles/${id}`, {
      method: 'DELETE',
      headers: this.authHeaders(),
    });
    if (!res.ok) throw new APIError(res.status, await res.text(), `/api/profiles/${id}`);
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
 *
 * Bootstrap diagnostic: when `!isBaseUrlConfigured()` after the sync,
 * emits one `console.warn` so support traces can distinguish "host not
 * configured" from "fetch transport error". Covers both (a) `useRemote=true`
 * + blank host persisted from a prior session and (b) syncFromConfig threw.
 * No blocking dialog — Settings UX handles fix-forward.
 */
export async function initApiClient(): Promise<void> {
  await apiClient.syncFromConfig();
  // getAuthToken() reads via the same preload-bridge chain as syncFromConfig
  // and is just as susceptible to IPC rejection. Wrapping here keeps
  // initApiClient throw-safe so App.tsx's fire-and-forget invocation never
  // produces an unhandled rejection.
  try {
    apiClient.setAuthToken(await getAuthToken());
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    console.warn('[APIClient] auth-token read failed at bootstrap:', detail);
  }
  if (!apiClient.isBaseUrlConfigured()) {
    console.warn(
      '[APIClient] bootstrap: remote host not configured — Settings must be saved before network paths activate',
    );
  }
}
