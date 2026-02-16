import React, { useEffect, useRef } from 'react';

interface LogEntry {
  timestamp: string;
  source: string;
  message: string;
  type?: 'info' | 'error' | 'success' | 'warning';
}

interface LogTerminalProps {
  title: string;
  logs: LogEntry[];
  className?: string;
  color?: 'cyan' | 'magenta' | 'orange';
}

export const LogTerminal: React.FC<LogTerminalProps> = ({
  title,
  logs,
  className = '',
  color = 'cyan',
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const accentColor = {
    cyan: 'text-accent-cyan border-accent-cyan/20',
    magenta: 'text-accent-magenta border-accent-magenta/20',
    orange: 'text-accent-orange border-accent-orange/20',
  }[color];

  return (
    <div
      className={`flex flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0b1120] shadow-2xl ${className}`}
    >
      {/* Terminal Header */}
      <div className="flex items-center justify-between border-b border-white/5 bg-white/5 px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`font-mono text-xs font-bold tracking-wider uppercase ${accentColor.split(' ')[0]}`}
          >
            &gt;_ {title}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="animate-pulse font-mono text-[10px] text-green-400">LIVE</span>
        </div>
      </div>

      {/* Terminal Body - Added selectable-text class */}
      <div
        ref={scrollRef}
        className="custom-scrollbar selectable-text max-h-[300px] min-h-[200px] flex-1 space-y-1.5 overflow-y-auto p-4 font-mono text-xs"
      >
        {logs.map((log, index) => (
          <div key={index} className="flex gap-3 rounded p-0.5 transition-colors hover:bg-white/5">
            <span className="shrink-0 text-slate-600 select-none">{log.timestamp}</span>
            <span className={`w-20 shrink-0 text-right font-bold ${accentColor.split(' ')[0]}`}>
              [{log.source}]
            </span>
            <span
              className={`break-all ${
                log.type === 'error'
                  ? 'text-red-400'
                  : log.type === 'success'
                    ? 'text-green-400'
                    : log.type === 'warning'
                      ? 'text-orange-400'
                      : 'text-slate-300'
              }`}
            >
              {log.message}
            </span>
          </div>
        ))}
        {logs.length === 0 && (
          <div className="text-slate-700 italic select-none">Waiting for stream...</div>
        )}
      </div>
    </div>
  );
};
