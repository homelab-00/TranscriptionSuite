import { useState } from 'react';
import { Search, Play, Loader2, Calendar as CalendarIcon, FileText, Bot, MessageSquare } from 'lucide-react';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { SearchResult } from '../types';
import { Toggle } from '../components/ui';

export default function SearchView() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');
  const [fuzzy, setFuzzy] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setSearched(true);
    try {
      const searchResults = await api.search({
        query: query.trim(),
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        fuzzy,
      });
      setResults(searchResults);
    } catch (error) {
      console.error('Search failed:', error);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handlePlayResult = (result: SearchResult) => {
    // Navigate to day view and open the recording at the exact timestamp
    const recordedAt = dayjs(result.recording.recorded_at);
    const dateStr = recordedAt.format('YYYY-MM-DD');
    // Navigate to day view with recording ID and timestamp
    navigate(`/day/${dateStr}?recording=${result.recording_id}&t=${result.start_time}`);
  };

  const formatTime = (seconds: number): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Search Transcriptions</h1>

      {/* Search form */}
      <div className="card p-4 mb-6">
        <div className="flex flex-col gap-4">
          {/* Search input */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={20} />
            <input
              type="text"
              className="input pl-10"
              placeholder="Search for words or phrases..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyPress={handleKeyPress}
            />
          </div>

          {/* Filters row */}
          <div className="flex flex-wrap gap-4 items-center">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-400">From:</label>
              <input
                type="date"
                className="input-sm w-auto"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                max={dayjs().format('YYYY-MM-DD')}
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-400">To:</label>
              <input
                type="date"
                className="input-sm w-auto"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                max={dayjs().format('YYYY-MM-DD')}
              />
            </div>
            <Toggle
              checked={fuzzy}
              onChange={setFuzzy}
              label="Fuzzy search"
            />
          </div>

          {/* Search button */}
          <button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            className="btn-primary w-full sm:w-auto"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <>
                <Search size={20} />
                Search
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {searched && (
        <div className="card p-4">
          <h2 className="text-lg font-medium text-white mb-4">
            {results.length > 0
              ? `Found ${results.length} result${results.length !== 1 ? 's' : ''}`
              : 'No results found'}
          </h2>

          <div className="divide-y divide-gray-800">
            {results.map((result, index) => (
              <div
                key={`${result.recording_id}-${index}`}
                className="py-3 flex items-start justify-between gap-4 cursor-pointer hover:bg-gray-800/50 rounded-lg px-2 -mx-2 transition-colors"
                onClick={() => handlePlayResult(result)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {/* Match type badge */}
                    {result.match_type === 'word' && (
                      <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded flex items-center gap-1">
                        <MessageSquare size={10} />
                        transcript
                      </span>
                    )}
                    {result.match_type === 'filename' && (
                      <span className="text-xs bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded flex items-center gap-1">
                        <FileText size={10} />
                        filename
                      </span>
                    )}
                    {result.match_type === 'summary' && (
                      <span className="text-xs bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded flex items-center gap-1">
                        <Bot size={10} />
                        summary
                      </span>
                    )}
                    <span className="font-medium text-white truncate">
                      {result.recording.filename}
                    </span>
                    <span className="text-xs text-gray-500 flex items-center gap-1">
                      <CalendarIcon size={12} />
                      {dayjs(result.recording.recorded_at).format('MMM D, YYYY')}
                    </span>
                  </div>
                  <div className="text-sm text-gray-400">
                    {result.match_type === 'word' ? (
                      <>
                        ...{result.context}...
                        <span className="ml-2 text-primary text-xs">
                          @ {formatTime(result.start_time)}
                        </span>
                      </>
                    ) : (
                      <>{result.context}</>
                    )}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handlePlayResult(result);
                  }}
                  className="btn-icon flex-shrink-0"
                  title="Open recording"
                >
                  <Play size={20} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
