import { useState, useRef, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  TextField,
  Switch,
  FormControlLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Alert,
  InputAdornment,
} from '@mui/material';
import {
  Folder as FolderIcon,
  Search as BrowseIcon,
  AudioFile as AudioIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
  Pending as PendingIcon,
} from '@mui/icons-material';
import { api } from '../services/api';

// Check if we're running inside Tauri
const isTauri = (): boolean => {
  return typeof window !== 'undefined' && '__TAURI__' in window;
};

// Type for Tauri v2 dialog
type TauriDialog = {
  open: (options?: {
    multiple?: boolean;
    filters?: Array<{ name: string; extensions: string[] }>;
  }) => Promise<string | string[] | null>;
};

interface ImportJob {
  id: number;
  filename: string;
  status: 'pending' | 'transcribing' | 'completed' | 'failed';
  progress?: number;
  message?: string;
}

export default function ImportView() {
  const [filePath, setFilePath] = useState('');
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [tauriDialog, setTauriDialog] = useState<TauriDialog | null>(null);

  // Load Tauri dialog API only if in Tauri environment
  useEffect(() => {
    if (isTauri()) {
      // Tauri v2 uses @tauri-apps/plugin-dialog
      import('@tauri-apps/plugin-dialog')
        .then((mod) => setTauriDialog(mod))
        .catch(() => {
          // Failed to load Tauri dialog - will use HTML file input fallback
          console.log('Tauri dialog not available, using HTML file input');
        });
    }
  }, []);

  // Open native file picker using Tauri dialog or fallback to HTML input
  const openFilePicker = async () => {
    try {
      if (isTauri() && tauriDialog) {
        const selected = await tauriDialog.open({
          multiple: true,
          filters: [{
            name: 'Audio Files',
            extensions: ['mp3', 'wav', 'opus', 'ogg', 'flac', 'm4a', 'wma', 'aac']
          }]
        });
        
        if (selected) {
          const paths = Array.isArray(selected) ? selected : [selected];
          for (const path of paths) {
            await importFilePath(path);
          }
        }
      } else {
        // Fallback to HTML file input if not in Tauri
        fileInputRef.current?.click();
      }
    } catch (err: any) {
      setError(`Failed to open file picker: ${err.message || err}`);
    }
  };

  const importFilePath = async (path: string) => {
    if (!path.trim()) {
      setError('Please enter a file path');
      return;
    }

    setError(null);
    
    try {
      const response = await api.importFile(path, true, enableDiarization, enableWordTimestamps);
      
      const newJob: ImportJob = {
        id: response.recording_id,
        filename: path.split('/').pop() || path,
        status: 'transcribing',
        message: response.message,
      };
      
      setJobs(prev => [newJob, ...prev]);
      setFilePath('');
      
      // Start polling for status
      pollJobStatus(newJob.id);
      
    } catch (err: any) {
      setError(err.response?.data?.detail || `Failed to import file: ${path}`);
    }
  };

  const handleImportFile = async () => {
    await importFilePath(filePath);
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setError(null);

    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadFile(file, enableDiarization, enableWordTimestamps);
        
        const newJob: ImportJob = {
          id: response.recording_id,
          filename: file.name,
          status: 'transcribing',
          message: response.message,
        };
        
        setJobs(prev => [newJob, ...prev]);
        
        // Start polling for status
        pollJobStatus(newJob.id);
        
      } catch (err: any) {
        setError(`Failed to upload ${file.name}: ${err.response?.data?.detail || err.message}`);
      }
    }

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const pollJobStatus = async (recordingId: number) => {
    const maxAttempts = 120; // 10 minutes at 5 second intervals
    let attempts = 0;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        updateJobStatus(recordingId, 'failed', undefined, 'Transcription timed out');
        return;
      }

      try {
        const status = await api.getTranscriptionStatus(recordingId);
        
        updateJobStatus(
          recordingId,
          status.status as ImportJob['status'],
          status.progress,
          status.message
        );

        if (status.status === 'transcribing' || status.status === 'pending') {
          attempts++;
          setTimeout(poll, 5000);
        }
      } catch (err) {
        updateJobStatus(recordingId, 'failed', undefined, 'Failed to check status');
      }
    };

    poll();
  };

  const updateJobStatus = (
    id: number,
    status: ImportJob['status'],
    progress?: number,
    message?: string
  ) => {
    setJobs(prev =>
      prev.map(job =>
        job.id === id
          ? { ...job, status, progress, message }
          : job
      )
    );
  };

  const getStatusIcon = (status: ImportJob['status']) => {
    switch (status) {
      case 'completed':
        return <CheckIcon color="success" />;
      case 'failed':
        return <ErrorIcon color="error" />;
      case 'transcribing':
        return <PendingIcon color="info" />;
      default:
        return <AudioIcon />;
    }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 3 }}>
        Import Recordings
      </Typography>

      {/* Import audio files */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Select Audio Files
        </Typography>
        
        {/* File picker button */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="audio/*,.mp3,.wav,.opus,.ogg,.flac,.m4a,.wma,.aac"
          style={{ display: 'none' }}
          onChange={handleFileUpload}
        />
        
        <Button
          variant="contained"
          size="large"
          startIcon={<BrowseIcon />}
          onClick={openFilePicker}
          sx={{ py: 2, px: 4, mb: 3, width: '100%' }}
        >
          Browse for Audio Files
        </Button>

        {/* Manual path input */}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Or enter a file path manually:
        </Typography>
        
        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            fullWidth
            label="File Path"
            placeholder="/path/to/audio.mp3"
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && filePath.trim()) {
                handleImportFile();
              }
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <FolderIcon sx={{ color: 'text.secondary' }} />
                </InputAdornment>
              ),
            }}
          />
          <Button
            variant="outlined"
            onClick={handleImportFile}
            disabled={!filePath.trim()}
          >
            Import
          </Button>
        </Box>

        <FormControlLabel
          control={
            <Switch
              checked={enableWordTimestamps}
              onChange={(e) => setEnableWordTimestamps(e.target.checked)}
            />
          }
          label="Enable word-level timestamps (clickable words in transcript)"
        />

        <FormControlLabel
          control={
            <Switch
              checked={enableDiarization}
              onChange={(e) => setEnableDiarization(e.target.checked)}
            />
          }
          label="Enable speaker diarization (requires separate Python 3.11 environment)"
        />
        
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Supported formats: MP3, WAV, OPUS, OGG, FLAC, M4A, WMA, AAC
        </Typography>
      </Paper>

      {/* Error alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Import jobs list */}
      {jobs.length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Import Queue
          </Typography>
          
          <List>
            {jobs.map((job) => (
              <ListItem key={job.id}>
                <ListItemIcon>
                  {getStatusIcon(job.status)}
                </ListItemIcon>
                <ListItemText
                  primary={job.filename}
                  secondary={
                    <Box>
                      <Typography variant="body2" color="text.secondary">
                        {job.message || job.status}
                      </Typography>
                      {job.status === 'transcribing' && job.progress !== undefined && (
                        <LinearProgress
                          variant="determinate"
                          value={job.progress * 100}
                          sx={{ mt: 1 }}
                        />
                      )}
                    </Box>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
    </Box>
  );
}
