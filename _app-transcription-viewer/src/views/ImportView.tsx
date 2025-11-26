import { useState, useRef } from 'react';
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
} from '@mui/material';
import {
  CloudUpload as UploadIcon,
  Folder as FolderIcon,
  AudioFile as AudioIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
  Pending as PendingIcon,
} from '@mui/icons-material';
import { api } from '../services/api';

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
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImportFile = async () => {
    if (!filePath.trim()) {
      setError('Please enter a file path');
      return;
    }

    setError(null);
    
    try {
      const response = await api.importFile(filePath, true, enableDiarization);
      
      const newJob: ImportJob = {
        id: response.recording_id,
        filename: filePath.split('/').pop() || filePath,
        status: 'transcribing',
        message: response.message,
      };
      
      setJobs(prev => [newJob, ...prev]);
      setFilePath('');
      
      // Start polling for status
      pollJobStatus(newJob.id);
      
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to import file');
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setError(null);

    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadFile(file, enableDiarization);
        
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

      {/* Import from file path */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Import from Local Path
        </Typography>
        
        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            fullWidth
            label="File Path"
            placeholder="/path/to/audio.mp3"
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            InputProps={{
              startAdornment: <FolderIcon sx={{ mr: 1, color: 'text.secondary' }} />,
            }}
          />
          <Button
            variant="contained"
            onClick={handleImportFile}
            disabled={!filePath.trim()}
          >
            Import
          </Button>
        </Box>

        <FormControlLabel
          control={
            <Switch
              checked={enableDiarization}
              onChange={(e) => setEnableDiarization(e.target.checked)}
            />
          }
          label="Enable speaker diarization (requires separate Python 3.10 environment)"
        />
      </Paper>

      {/* Upload files */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Upload Files
        </Typography>
        
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="audio/*"
          style={{ display: 'none' }}
          onChange={handleFileUpload}
        />
        
        <Button
          variant="outlined"
          size="large"
          startIcon={<UploadIcon />}
          onClick={() => fileInputRef.current?.click()}
          sx={{ py: 4, width: '100%' }}
        >
          Click to upload audio files
        </Button>
        
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Supported formats: MP3, WAV, OPUS, OGG, FLAC, M4A
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
