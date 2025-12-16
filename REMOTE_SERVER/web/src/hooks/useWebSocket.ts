import { useState, useRef, useCallback, useEffect } from 'react';
import { api, getWsUrl } from '../api/client';
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

export function useWebSocket(options: WebSocketOptions = {}) {
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  // Store options in ref to avoid recreating callbacks on every render
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const updateStatus = useCallback((newStatus: WebSocketStatus) => {
    setStatus(newStatus);
    optionsRef.current.onStatusChange?.(newStatus);
  }, []);

  const connect = useCallback(() => {
    const token = api.getToken();
    if (!token) {
      setError('Not authenticated');
      updateStatus('error');
      return;
    }

    // Prevent duplicate connections
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
        // Send auth message
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
        // Only set disconnected if not already in error state
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
        // Heartbeat response
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

  // Cleanup on unmount
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
