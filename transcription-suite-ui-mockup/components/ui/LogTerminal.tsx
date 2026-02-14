
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

export const LogTerminal: React.FC<LogTerminalProps> = ({ title, logs, className = '', color = 'cyan' }) => {
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
    <div className={`flex flex-col bg-[#0b1120] rounded-xl border border-white/10 overflow-hidden shadow-2xl ${className}`}>
      {/* Terminal Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-white/5 border-b border-white/5">
        <div className="flex items-center gap-2">
            <span className={`text-xs font-mono font-bold uppercase tracking-wider ${accentColor.split(' ')[0]}`}>&gt;_ {title}</span>
        </div>
        <div className="flex items-center gap-2">
            <span className="text-[10px] text-green-400 font-mono animate-pulse">LIVE</span>
        </div>
      </div>

      {/* Terminal Body - Added selectable-text class */}
      <div ref={scrollRef} className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1.5 custom-scrollbar min-h-[200px] max-h-[300px] selectable-text">
        {logs.map((log, index) => (
            <div key={index} className="flex gap-3 hover:bg-white/5 p-0.5 rounded transition-colors">
                <span className="text-slate-600 shrink-0 select-none">{log.timestamp}</span>
                <span className={`font-bold shrink-0 w-20 text-right ${accentColor.split(' ')[0]}`}>[{log.source}]</span>
                <span className={`break-all ${
                    log.type === 'error' ? 'text-red-400' : 
                    log.type === 'success' ? 'text-green-400' : 
                    log.type === 'warning' ? 'text-orange-400' : 
                    'text-slate-300'
                }`}>
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
