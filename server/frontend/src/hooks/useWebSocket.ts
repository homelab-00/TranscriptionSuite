import { useState, useRef, useCallback, useEffect } from 'react';
import { WSMessage, TranscriptionResult } from '../types';

interface WebSocketOptions {
  onRealtimeText?: (text: string) => void;
  onFinalResult?: (result: TranscriptionResult) => void;
  onError?: (error: string) => void;
  onStatusChange?: (status: WebSocketStatus) => void;
}

export type WebSocketStatus = 
  | 'disconnected'
  | 'connecting'
  | 'authenticating'
  | 'ready'
  | 'recording'
  | 'transcribing'
  | 'busy'
  | 'error';

// Get WebSocket URL
// In development mode, use backend port 8000
// In production, use same port as the page (frontend and backend are served together)
const getWsUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;

  // In development, frontend runs on port 1420 (Vite) but backend is on port 8000
  // In production, frontend and backend are served from the same port
  const port = import.meta.env.DEV
    ? '8000'
    : (window.location.port || '8443');

  return `${protocol}//${host}:${port}/ws`;
};

// Get auth token from cookie
const getAuthToken = (): string | null => {
  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'auth_token') {
      return value;
    }
  }
  return null;
};

export function useWebSocket(options: WebSocketOptions = {}) {
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const updateStatus = useCallback((newStatus: WebSocketStatus) => {
    setStatus(newStatus);
    optionsRef.current.onStatusChange?.(newStatus);
  }, []);

  const connect = useCallback(() => {
    // For localhost connections, authentication is bypassed
    const isLocalhost = window.location.hostname === 'localhost' || 
                       window.location.hostname === '127.0.0.1' ||
                       window.location.hostname === '::1';
    
    let token = getAuthToken();
    
    // If no token and not localhost, show error
    if (!token && !isLocalhost) {
      setError('Not authenticated');
      updateStatus('error');
      return;
    }
    
    // For localhost without token, use placeholder
    if (!token && isLocalhost) {
      token = 'localhost';
    }

    if (wsRef.current?.readyState === WebSocket.OPEN || 
        wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    updateStatus('connecting');
    setError(null);

    try {
      const ws = new WebSocket(getWsUrl());

      ws.onopen = () => {
        updateStatus('authenticating');
        ws.send(JSON.stringify({
          type: 'auth',
          data: { token },
          timestamp: Date.now() / 1000,
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          handleMessage(msg);
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = () => {
        setError('WebSocket connection error');
        updateStatus('error');
        optionsRef.current.onError?.('WebSocket connection error');
      };

      ws.onclose = () => {
        wsRef.current = null;
        setStatus(prev => prev === 'error' ? 'error' : 'disconnected');
      };

      wsRef.current = ws;

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed');
      updateStatus('error');
    }
  }, [updateStatus]);

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'auth_ok':
        updateStatus('ready');
        break;

      case 'auth_fail':
        setError(msg.data?.message as string || 'Authentication failed');
        updateStatus('error');
        wsRef.current?.close();
        break;

      case 'session_busy':
        setError(`Server busy: ${msg.data?.active_user || 'another user'} is using it`);
        updateStatus('busy');
        wsRef.current?.close();
        break;

      case 'session_started':
        updateStatus('recording');
        break;

      case 'session_stopped':
        updateStatus('ready');
        break;

      case 'realtime':
        if (msg.data?.text) {
          optionsRef.current.onRealtimeText?.(msg.data.text as string);
        }
        break;

      case 'final':
        updateStatus('ready');
        if (msg.data) {
          optionsRef.current.onFinalResult?.({
            text: msg.data.text as string || '',
            words: msg.data.words as TranscriptionResult['words'],
            duration: msg.data.duration as number || 0,
            language: msg.data.language as string,
            is_final: true,
          });
        }
        break;

      case 'error':
        setError(msg.data?.message as string || 'Server error');
        optionsRef.current.onError?.(msg.data?.message as string || 'Server error');
        break;

      case 'pong':
        break;

      default:
        console.log('Unknown message type:', msg.type);
    }
  }, [updateStatus]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    updateStatus('disconnected');
  }, [updateStatus]);

  const startRecording = useCallback((language?: string) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      setError('Not connected');
      return false;
    }

    wsRef.current.send(JSON.stringify({
      type: 'start',
      data: { language, enable_realtime: false },
      timestamp: Date.now() / 1000,
    }));

    return true;
  }, []);

  const stopRecording = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }

    updateStatus('transcribing');
    wsRef.current.send(JSON.stringify({
      type: 'stop',
      data: {},
      timestamp: Date.now() / 1000,
    }));

    return true;
  }, [updateStatus]);

  const sendAudioData = useCallback((data: ArrayBuffer) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }

    wsRef.current.send(data);
    return true;
  }, []);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    status,
    error,
    isConnected: status !== 'disconnected' && status !== 'error',
    isReady: status === 'ready',
    isRecording: status === 'recording',
    isTranscribing: status === 'transcribing',
    connect,
    disconnect,
    startRecording,
    stopRecording,
    sendAudioData,
  };
}
