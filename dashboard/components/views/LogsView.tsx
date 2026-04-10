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
    const mlx = (window as any).electronAPI?.mlx;
    if (!mlx) return;

    // Load the existing log buffer from the main process.
    mlx
      .getLogs(500)
      .then((lines: string[]) => {
        setMlxLogLines(lines);
      })
      .catch(() => {});

    // Subscribe to real-time lines.
    const unsub = mlx.onLogLine((line: string) => {
      setMlxLogLines((prev) => [...prev, line]);
    });
    return unsub;
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
