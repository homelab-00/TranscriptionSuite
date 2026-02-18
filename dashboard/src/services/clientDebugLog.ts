export type ClientLogType = 'info' | 'success' | 'error' | 'warning';

export interface ClientDebugLogEntry {
  timestamp: string;
  source: string;
  message: string;
  type: ClientLogType;
}

const MAX_CLIENT_LOG_LINES = 2_000;

let clientLogs: ClientDebugLogEntry[] = [];
let cachedLogPath: string | null = null;
let logPathRequest: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

function nowTimestamp(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function getAppBridge(): ElectronAPI['app'] | undefined {
  if (typeof window === 'undefined') {
    return undefined;
  }
  return window.electronAPI?.app;
}

function notifyListeners(): void {
  for (const listener of listeners) {
    listener();
  }
}

async function appendToClientLogFile(line: string): Promise<void> {
  const appBridge = getAppBridge();
  if (!appBridge?.appendClientLogLine) {
    return;
  }
  try {
    await appBridge.appendClientLogLine(line);
  } catch {
    // Ignore file write failures; in-memory stream should still work.
  }
}

export function logClientEvent(
  source: string,
  message: string,
  type: ClientLogType = 'info',
): void {
  const normalizedMessage = String(message);
  const entry: ClientDebugLogEntry = {
    timestamp: nowTimestamp(),
    source,
    message: normalizedMessage,
    type,
  };

  clientLogs = [...clientLogs, entry];
  if (clientLogs.length > MAX_CLIENT_LOG_LINES) {
    clientLogs = clientLogs.slice(-MAX_CLIENT_LOG_LINES);
  }

  notifyListeners();

  const fileLine = `[${new Date().toISOString()}] [${source}] ${normalizedMessage}`;
  void appendToClientLogFile(fileLine);
}

export function getClientDebugLogs(): ClientDebugLogEntry[] {
  return clientLogs;
}

export function clearClientDebugLogs(): void {
  clientLogs = [];
  notifyListeners();
}

export function subscribeClientDebugLogs(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getCachedClientDebugLogPath(): string | null {
  return cachedLogPath;
}

export async function getClientDebugLogPath(): Promise<string | null> {
  const appBridge = getAppBridge();
  if (!appBridge?.getClientLogPath) {
    return null;
  }

  if (cachedLogPath) {
    return cachedLogPath;
  }

  if (!logPathRequest) {
    logPathRequest = appBridge
      .getClientLogPath()
      .then((resolvedPath) => {
        cachedLogPath = resolvedPath;
        return resolvedPath;
      })
      .catch(() => null)
      .finally(() => {
        logPathRequest = null;
      });
  }

  return logPathRequest;
}
