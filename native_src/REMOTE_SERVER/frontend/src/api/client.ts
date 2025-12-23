import { User, TokenInfo, NewTokenInfo, TranscriptionResult, ServerStatus } from '../types';

// Get base URL - use current origin in production, proxy in dev
const getBaseUrl = () => {
  if (import.meta.env.DEV) {
    return '';  // Vite proxy handles this
  }
  return '';  // Same origin in production
};

// Get WebSocket URL (same port as HTTPS, /ws endpoint)
export const getWsUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  const port = window.location.port || '8443';
  return `${protocol}//${host}:${port}/ws`;
};

// API client
class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor() {
    this.baseUrl = getBaseUrl();
    // Try to restore token from localStorage
    this.token = localStorage.getItem('auth_token');
  }

  setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem('auth_token', token);
      // Also set cookie for server-side auth middleware
      document.cookie = `auth_token=${token}; path=/; max-age=${30*24*60*60}; SameSite=Strict; Secure`;
    } else {
      localStorage.removeItem('auth_token');
      // Clear auth cookie
      document.cookie = 'auth_token=; path=/; max-age=0; SameSite=Strict; Secure';
    }
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    if (this.token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Request failed' }));
      throw new Error(error.message || error.error || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Auth endpoints
  async login(token: string): Promise<{ success: boolean; user?: User; message?: string }> {
    const result = await this.request<{ success: boolean; user?: User; message?: string }>(
      '/api/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({ token }),
      }
    );
    
    if (result.success) {
      this.setToken(token);
    }
    
    return result;
  }

  logout() {
    this.setToken(null);
  }

  // Token management (admin only)
  async listTokens(): Promise<{ tokens: TokenInfo[] }> {
    return this.request('/api/auth/tokens');
  }

  async createToken(
    clientName: string,
    isAdmin: boolean = false,
    expiryDays?: number
  ): Promise<{ success: boolean; message: string; token: NewTokenInfo }> {
    return this.request('/api/auth/tokens', {
      method: 'POST',
      body: JSON.stringify({ 
        client_name: clientName, 
        is_admin: isAdmin,
        expiry_days: expiryDays,
      }),
    });
  }

  async revokeToken(tokenId: string): Promise<{ success: boolean }> {
    // Now uses token_id instead of full token
    return this.request(`/api/auth/tokens/${encodeURIComponent(tokenId)}`, {
      method: 'DELETE',
    });
  }

  // File transcription
  async transcribeFile(
    file: File,
    language?: string,
    onProgress?: (progress: number) => void
  ): Promise<TranscriptionResult> {
    const formData = new FormData();
    formData.append('file', file);
    if (language) {
      formData.append('language', language);
    }

    const xhr = new XMLHttpRequest();
    
    return new Promise((resolve, reject) => {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress((e.loaded / e.total) * 100);
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          try {
            const error = JSON.parse(xhr.responseText);
            reject(new Error(error.error || 'Upload failed'));
          } catch {
            reject(new Error(`HTTP ${xhr.status}`));
          }
        }
      });

      xhr.addEventListener('error', () => reject(new Error('Network error')));

      xhr.open('POST', `${this.baseUrl}/api/transcribe/file`);
      if (this.token) {
        xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
      }
      xhr.send(formData);
    });
  }

  // Server status
  async getStatus(): Promise<ServerStatus> {
    return this.request('/api/status');
  }
}

export const api = new ApiClient();
