import { useState, useRef } from 'react';
import {
  Box,
  Paper,
  Typography,
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
  AudioFile as AudioIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
  Pending as PendingIcon,
  CloudUpload as UploadIcon,
} from '@mui/icons-material';
import { api } from '../services/api';
import { ImportJob } from '../types';

export default function ImportView() {
  const [enableDiarization, setEnableDiarization] = useState(false);
  const [enableWordTimestamps, setEnableWordTimestamps] = useState(true);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Open HTML file picker
  const openFilePicker = () => {
    fileInputRef.current?.click();
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

  // Handle drag events for the drop zone
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      await handleFiles(files);
    }
  };

  const handleFiles = async (files: FileList) => {
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
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 3 }}>
        Import Recordings
      </Typography>

      {/* Drag and drop zone */}
      <Paper
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        sx={{
          p: 3,
          mb: 3,
          border: '2px dashed',
          borderColor: dragActive ? 'primary.main' : 'divider',
          bgcolor: dragActive ? 'action.hover' : 'background.paper',
          transition: 'all 0.2s ease',
          cursor: 'pointer',
        }}
        onClick={openFilePicker}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            py: 4,
          }}
        >
          <UploadIcon sx={{ fontSize: 48, color: dragActive ? 'primary.main' : 'text.secondary', mb: 2 }} />
          <Typography variant="h6" sx={{ mb: 1 }}>
            {dragActive ? 'Drop files here' : 'Drag & drop audio files here'}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            or click to browse
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Supported: MP3, WAV, OPUS, OGG, FLAC, M4A, WMA, AAC
          </Typography>
        </Box>
        
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="audio/*,.mp3,.wav,.opus,.ogg,.flac,.m4a,.wma,.aac"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </Paper>

      {/* Options */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Transcription Options
        </Typography>

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
