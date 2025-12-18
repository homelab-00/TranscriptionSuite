import { TranscriptionResult } from '../types';

interface TranscriptionDisplayProps {
  result: TranscriptionResult;
}

export function TranscriptionDisplay({ result }: TranscriptionDisplayProps) {
  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(result.text);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-slate-700/50 rounded-lg border border-slate-600 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-slate-700 border-b border-slate-600 flex items-center justify-between">
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span>Duration: {formatDuration(result.duration)}</span>
          {result.language && <span>Language: {result.language}</span>}
          {result.words && <span>{result.words.length} words</span>}
        </div>
        <button
          onClick={copyToClipboard}
          className="px-3 py-1 text-sm bg-slate-600 hover:bg-slate-500 rounded 
                   transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          Copy
        </button>
      </div>

      {/* Text content */}
      <div className="p-4">
        <p className="text-white whitespace-pre-wrap leading-relaxed">
          {result.text || <span className="text-slate-500 italic">No transcription</span>}
        </p>
      </div>
    </div>
  );
}
