import { HistoryEntry } from '../types';

interface SessionHistoryProps {
  entries: HistoryEntry[];
  onSelect: (entry: HistoryEntry) => void;
}

export function SessionHistory({ entries, onSelect }: SessionHistoryProps) {
  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="h-full flex flex-col">
      <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        Session History
      </h3>

      {entries.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-slate-500 text-sm text-center">
            No transcriptions yet.<br />
            Start recording to see history.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2">
          {entries.map((entry) => (
            <button
              key={entry.id}
              onClick={() => onSelect(entry)}
              className="w-full p-3 bg-slate-700/50 hover:bg-slate-700 rounded-lg border 
                       border-slate-600 text-left transition-colors"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400">
                  {formatTime(entry.timestamp)}
                </span>
                <span className="text-xs text-slate-500">
                  {formatDuration(entry.duration)}
                </span>
              </div>
              <p className="text-sm text-white line-clamp-2">
                {entry.text || <span className="text-slate-500 italic">Empty</span>}
              </p>
              <div className="mt-1 flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${
                  entry.type === 'recording' 
                    ? 'bg-primary-900/50 text-primary-300' 
                    : 'bg-slate-600 text-slate-300'
                }`}>
                  {entry.type === 'recording' ? '🎤 Recording' : '📁 File'}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-slate-700">
        <p className="text-xs text-slate-500 text-center">
          History is stored in memory only.<br />
          It will be cleared when you refresh.
        </p>
      </div>
    </div>
  );
}
