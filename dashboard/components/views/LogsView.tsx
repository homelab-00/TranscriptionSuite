import React, { useCallback, useEffect, useMemo } from 'react';
import { Copy } from 'lucide-react';
import { LogTerminal } from '../ui/LogTerminal';
import { Button } from '../ui/Button';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { useClientDebugLogs } from '../../src/hooks/useClientDebugLogs';
import { writeToClipboard } from '../../src/hooks/useClipboard';

export const LogsView: React.FC = () => {
  const docker = useDockerContext();
  const { logs: clientLogs } = useClientDebugLogs();

  // Build structured log entries from raw Docker output lines.
  const serverLogs = useMemo(() => {
    const logs: Array<{
      timestamp: string;
      source: string;
      message: string;
      type: 'info' | 'success' | 'error' | 'warning';
    }> = [];
    const now = () => new Date().toLocaleTimeString('en-US', { hour12: false });

    const classifyDockerLine = (line: string): 'info' | 'success' | 'error' | 'warning' => {
      if (/(^|\b)(error|exception|traceback|fatal)(\b|$)/i.test(line)) return 'error';
      if (/(^|\b)(warn|warning)(\b|$)/i.test(line)) return 'warning';
      if (/(^|\b)(started|ready|listening|healthy)(\b|$)/i.test(line)) return 'success';
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
          type: classifyDockerLine(trimmed),
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
        type: classifyDockerLine(match[2]),
      };
    };

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
  }, [docker.logLines, docker.container.running, docker.operationError]);

  // Keep Docker logs streaming so the terminal updates in real time.
  useEffect(() => {
    if (!docker.container.exists) {
      docker.stopLogStream();
      return;
    }
    docker.startLogStream();
    return () => {
      docker.stopLogStream();
    };
  }, [
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
          title="Server Output (Docker)"
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
