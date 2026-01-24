import axios from 'axios';
import { TokenInfo, NewTokenInfo } from '../types';

// Use dynamic base URL - same origin in production, localhost in development
const API_BASE_URL = import.meta.env.DEV
  ? 'http://localhost:8000/api'
  : `${window.location.origin}/api`;

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,  // Include cookies for authentication
});

// Auth API for token management
const AUTH_API = `${API_BASE_URL}/auth`;

export const api = {
  // Token Management (Admin)
  async listTokens(): Promise<{ tokens: TokenInfo[] }> {
    const response = await client.get(`${AUTH_API}/tokens`);
    return response.data;
  },

  async createToken(
    clientName: string,
    isAdmin: boolean = false,
    expiryDays?: number
  ): Promise<{ success: boolean; message: string; token: NewTokenInfo }> {
    const response = await client.post(`${AUTH_API}/tokens`, {
      client_name: clientName,
      is_admin: isAdmin,
      expiry_days: expiryDays,
    });
    return response.data;
  },

  async revokeToken(tokenId: string): Promise<{ success: boolean }> {
    const response = await client.delete(`${AUTH_API}/tokens/${encodeURIComponent(tokenId)}`);
    return response.data;
  },
};
