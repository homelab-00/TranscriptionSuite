import { useState } from 'react';
import {
  Box,
  TextField,
  Button,
  Paper,
  Typography,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  FormControlLabel,
  Checkbox,
  CircularProgress,
  InputAdornment,
} from '@mui/material';
import { DatePicker } from '@mui/x-date-pickers';
import { 
  PlayArrow as PlayIcon,
  Search as SearchIcon,
} from '@mui/icons-material';
import dayjs, { Dayjs } from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { SearchResult } from '../types';

export default function SearchView() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [fromDate, setFromDate] = useState<Dayjs | null>(null);
  const [toDate, setToDate] = useState<Dayjs | null>(null);
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
        from_date: fromDate?.format('YYYY-MM-DD'),
        to_date: toDate?.format('YYYY-MM-DD'),
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
    // Navigate to recording with start time offset by 15 seconds
    const startTime = Math.max(0, result.start_time - 15);
    navigate(`/recording/${result.recording_id}?t=${startTime}`);
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

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 3 }}>
        Search Transcriptions
      </Typography>

      {/* Search form */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField
            fullWidth
            label="Search for words or phrases"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Enter search term..."
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon color="action" />
                </InputAdornment>
              ),
            }}
          />

          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            <DatePicker
              label="From date"
              value={fromDate}
              onChange={setFromDate}
              maxDate={dayjs()}
              slotProps={{ textField: { size: 'small' } }}
            />
            <DatePicker
              label="To date"
              value={toDate}
              onChange={setToDate}
              maxDate={dayjs()}
              slotProps={{ textField: { size: 'small' } }}
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={fuzzy}
                  onChange={(e) => setFuzzy(e.target.checked)}
                />
              }
              label="Fuzzy search"
            />
          </Box>

          <Button
            variant="contained"
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            startIcon={loading ? undefined : <SearchIcon />}
          >
            {loading ? <CircularProgress size={24} /> : 'Search'}
          </Button>
        </Box>
      </Paper>

      {/* Results */}
      {searched && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            {results.length > 0
              ? `Found ${results.length} result${results.length !== 1 ? 's' : ''}`
              : 'No results found'}
          </Typography>

          <List>
            {results.map((result, index) => (
              <ListItem
                key={`${result.recording_id}-${index}`}
                divider={index < results.length - 1}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="subtitle1">
                        {result.recording.filename}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {dayjs(result.recording.recorded_at).format('MMM D, YYYY')}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    <>
                      <Typography
                        component="span"
                        variant="body2"
                        color="text.secondary"
                      >
                        ...{result.context}...
                      </Typography>
                      <Typography
                        component="span"
                        variant="caption"
                        color="primary"
                        sx={{ ml: 1 }}
                      >
                        @ {formatTime(result.start_time)}
                      </Typography>
                    </>
                  }
                />
                <ListItemSecondaryAction>
                  <IconButton
                    edge="end"
                    onClick={() => handlePlayResult(result)}
                    title="Play from 15 seconds before"
                  >
                    <PlayIcon />
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
    </Box>
  );
}
