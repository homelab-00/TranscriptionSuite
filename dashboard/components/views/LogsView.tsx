import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Copy } from 'lucide-react';
import { LogTerminal } from '../ui/LogTerminal';
import { Button } from '../ui/Button';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { useClientDebugLogs } from '../../src/hooks/useClientDebugLogs';
import { writeToClipboard } from '../../src/hooks/useClipboard';

interface LogsViewProps {
  runtimeProfile?: string;
}

export const LogsView: React.FC<LogsViewProps> = ({ runtimeProfile }) => {
  const isMetal = runtimeProfile === 'metal';
  const docker = useDockerContext();
  const { logs: clientLogs } = useClientDebugLogs();

  // ── Metal mode: subscribe to native MLX server log lines ──────────────────
  const [mlxLogLines, setMlxLogLines] = useState<string[]>([]);

  useEffect(() => {
    if (!isMetal) {
      setMlxLogLines([]);
      return;
    }

    // Bounded retry: preload may not have exposed `electronAPI.mlx` yet at
    // first effect run (especially during dev hot-reload or when LogsView
    // mounts before the contextBridge bind completes). Poll every 250 ms up
    // to 10 attempts (~2.5 s budget); after that, give up with a warning.
    let unsub: (() => void) | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;
    let attempts = 0;
    const MAX_ATTEMPTS = 10;
    const POLL_INTERVAL_MS = 250;

    const tryAttach = (): boolean => {
      const mlx = (window as any).electronAPI?.mlx;
      if (!mlx) return false;
      if (cancelled) return true;

      // Defensive: a malformed preload binding (e.g. `mlx` exposed as a partial
      // object missing `getLogs` / `onLogLine`) would otherwise throw inside the
      // setInterval callback. Node does NOT auto-clear timers on uncaught
      // callback exceptions, which would leak a 250 ms error spam loop. Treat
      // any throw here as terminal — log once and stop polling.
      try {
        mlx
          .getLogs(500)
          .then((lines: string[]) => {
            if (!cancelled) setMlxLogLines(lines);
          })
          .catch(() => {});

        unsub = mlx.onLogLine((line: string) => {
          if (!cancelled) setMlxLogLines((prev) => [...prev, line]);
        });
        return true;
      } catch (err) {
        console.warn('[LogsView] failed to attach mlx subscription:', err);
        return true;
      }
    };

    if (!tryAttach()) {
      pollTimer = setInterval(() => {
        attempts += 1;
        if (tryAttach()) {
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          return;
        }
        if (attempts >= MAX_ATTEMPTS) {
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          console.warn(
            '[LogsView] electronAPI.mlx not available after retry — Metal logs unavailable',
          );
        }
      }, POLL_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
      if (unsub) unsub();
    };
  }, [isMetal]);

  // Build structured log entries from raw Docker output lines.
  const serverLogs = useMemo(() => {
    const logs: Array<{
      timestamp: string;
      source: string;
      message: string;
      type: 'info' | 'success' | 'error' | 'warning';
    }> = [];
    const now = () => new Date().toLocaleTimeString('en-US', { hour12: false });

    const classifyLine = (line: string): 'info' | 'success' | 'error' | 'warning' => {
      if (/(^|\b)(error|exception|traceback|fatal)(\b|$)/i.test(line)) return 'error';
      if (/(^|\b)(warn|warning)(\b|$)/i.test(line)) return 'warning';
      if (/(^|\b)(started|ready|listening|healthy|startup complete)(\b|$)/i.test(line))
        return 'success';
      return 'info';
    };

    const parseDockerLine = (line: string) => {
      const trimmed = line.trimEnd();
      const match = trimmed.match(
        /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+(.*)$/,
      );
      if (!match) {
        return {
          timestamp: now(),
          source: 'Docker',
          message: trimmed,
          type: classifyLine(trimmed),
        };
      }
      const parsedDate = new Date(match[1]);
      const time = Number.isNaN(parsedDate.getTime())
        ? now()
        : parsedDate.toLocaleTimeString('en-US', { hour12: false });
      return {
        timestamp: time,
        source: 'Docker',
        message: match[2],
        type: classifyLine(match[2]),
      };
    };

    if (isMetal) {
      // Metal mode: show native MLX server output
      for (const line of mlxLogLines) {
        const trimmed = line.trimEnd();
        logs.push({
          timestamp: now(),
          source: 'Metal',
          message: trimmed,
          type: classifyLine(trimmed),
        });
      }
      return logs;
    }

    for (const line of docker.logLines) {
      logs.push(parseDockerLine(line));
    }

    if (docker.container.running && logs.length === 0) {
      logs.push({
        timestamp: now(),
        source: 'Docker',
        message: 'Waiting for docker logs...',
        type: 'info',
      });
    }

    if (docker.operationError) {
      logs.push({
        timestamp: now(),
        source: 'Docker',
        message: docker.operationError,
        type: 'error',
      });
    }

    return logs;
  }, [isMetal, mlxLogLines, docker.logLines, docker.container.running, docker.operationError]);

  // Keep Docker logs streaming so the terminal updates in real time.
  // Skip when in Metal mode — the MLX useEffect above handles log streaming.
  useEffect(() => {
    if (isMetal || !docker.container.exists) {
      docker.stopLogStream();
      return;
    }
    docker.startLogStream();
    return () => {
      docker.stopLogStream();
    };
  }, [
    isMetal,
    docker.container.exists,
    docker.container.running,
    docker.startLogStream,
    docker.stopLogStream,
  ]);

  const handleCopyLogs = useCallback(() => {
    const allLogs = [...serverLogs, ...clientLogs];
    const logText = allLogs.map((l) => `[${l.timestamp}] [${l.source}] ${l.message}`).join('\n');
    writeToClipboard(logText).catch(() => {});
  }, [serverLogs, clientLogs]);

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col p-6">
      {/* Header */}
      <div className="mb-6 flex flex-none items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-white">System Logs</h1>
        <Button
          variant="glass"
          size="sm"
          className="h-8 text-xs"
          onClick={handleCopyLogs}
          icon={<Copy size={14} />}
        >
          Copy All
        </Button>
      </div>

      {/* Dual-panel log view — side by side on large screens */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-2">
        <LogTerminal
          title={isMetal ? 'Server Output (Metal)' : 'Server Output (Docker)'}
          logs={serverLogs}
          color="magenta"
          className="h-full"
        />
        <LogTerminal
          title="Client Debug (Socket)"
          logs={clientLogs}
          color="cyan"
          className="h-full"
        />
      </div>
    </div>
  );
};
