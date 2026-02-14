/**
 * Minimal API client for TranscriptionSuite server.
 * Phase 1: health, readiness, and status endpoints only.
 */

export interface HealthResponse {
  status: string;
}

export interface ReadyResponse {
  ready: boolean;
  model_loaded: boolean;
  reason?: string;
}

export interface ServerStatus {
  status: string;
  version?: string;
  uptime?: number;
  model?: string;
  live_model?: string;
  gpu_available?: boolean;
  diarization_available?: boolean;
  active_connections?: number;
  tls_enabled?: boolean;
}

export class APIClient {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://localhost:8000') {
    // Strip trailing slash
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  /** Update the server base URL */
  setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/+$/, '');
  }

  /** GET /health — basic liveness check */
  async healthCheck(): Promise<HealthResponse> {
    const res = await fetch(`${this.baseUrl}/health`);
    if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
    return res.json();
  }

  /** GET /ready — model readiness */
  async getReadiness(): Promise<ReadyResponse> {
    const res = await fetch(`${this.baseUrl}/ready`);
    if (!res.ok) throw new Error(`Readiness check failed: ${res.status}`);
    return res.json();
  }

  /** GET /api/status — detailed server status */
  async getStatus(): Promise<ServerStatus> {
    const res = await fetch(`${this.baseUrl}/api/status`);
    if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
    return res.json();
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
        ready: readiness.ready,
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
}

/** Singleton API client instance */
export const apiClient = new APIClient();
