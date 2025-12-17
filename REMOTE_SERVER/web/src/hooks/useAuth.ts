import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import { User } from '../types';

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Check for existing token on mount
  useEffect(() => {
    const token = api.getToken();
    if (token) {
      validateToken(token);
    } else {
      setIsLoading(false);
    }
  }, []);

  const validateToken = async (token: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const result = await api.login(token);
      if (result.success && result.user) {
        setUser(result.user);
      } else {
        api.logout();
        setError(result.message || 'Invalid token');
      }
    } catch (err) {
      api.logout();
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setIsLoading(false);
    }
  };

  const login = useCallback(async (token: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await api.login(token);
      if (result.success && result.user) {
        setUser(result.user);
        return true;
      } else {
        setError(result.message || 'Invalid token');
        return false;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    api.logout();
    setUser(null);
    setError(null);
  }, []);

  return {
    user,
    isLoading,
    error,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin ?? false,
    login,
    logout,
  };
}
