import axios from 'axios';
import { Recording, Transcription, SearchResult, RecordingsByDate, SearchParams, ImportJob } from '../types';

const API_BASE_URL = 'http://localhost:8000/api';

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

interface TranscribeResponse {
  recording_id: number;
  message: string;
}

export const api = {
  // Recordings
  async getRecordings(): Promise<Recording[]> {
    const response = await client.get('/recordings');
    return response.data;
  },

  async getRecording(id: number): Promise<Recording> {
    const response = await client.get(`/recordings/${id}`);
    return response.data;
  },

  async getRecordingsByMonth(year: number, month: number): Promise<Recording[]> {
    const response = await client.get('/recordings', {
      params: { year, month },
    });
    return response.data;
  },

  async getRecordingsByDateRange(fromDate: string, toDate: string): Promise<RecordingsByDate> {
    const response = await client.get('/recordings', {
      params: { start_date: fromDate, end_date: toDate },
    });
    return response.data;
  },

  async deleteRecording(id: number): Promise<void> {
    await client.delete(`/recordings/${id}`);
  },

  async updateRecordingDate(id: number, recordedAt: string): Promise<void> {
    await client.patch(`/recordings/${id}/date`, { recorded_at: recordedAt });
  },

  async getNextAvailableMinute(date: string, hour: number): Promise<{next_minute: number, next_second: number}> {
    const response = await client.get(`/recordings/next-minute/${date}/${hour}`);
    return response.data;
  },

  // Transcriptions
  async getTranscription(recordingId: number): Promise<Transcription> {
    const response = await client.get(`/recordings/${recordingId}/transcription`);
    return response.data;
  },

  // Import/Transcribe
  async importFile(filepath: string, copyFile: boolean = true, enableDiarization: boolean = false, enableWordTimestamps: boolean = true): Promise<TranscribeResponse> {
    const response = await client.post('/transcribe/file', {
      filepath,
      copy_file: copyFile,
      enable_diarization: enableDiarization,
      enable_word_timestamps: enableWordTimestamps,
    });
    return response.data;
  },

  async uploadFile(file: File, enableDiarization: boolean = false, enableWordTimestamps: boolean = true, recordedAt?: string): Promise<TranscribeResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('enable_diarization', String(enableDiarization));
    formData.append('enable_word_timestamps', String(enableWordTimestamps));
    // Use provided recordedAt, or fall back to file's last modified time
    if (recordedAt) {
      formData.append('file_created_at', recordedAt);
    } else if (file.lastModified) {
      // Format as local time string to avoid UTC conversion issues
      const date = new Date(file.lastModified);
      const localTime = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
      formData.append('file_created_at', localTime);
    }
    
    const response = await client.post('/transcribe/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  async getTranscriptionStatus(recordingId: number): Promise<ImportJob> {
    const response = await client.get(`/transcribe/status/${recordingId}`);
    return {
      id: response.data.recording_id,
      filename: '',
      status: response.data.status,
      progress: response.data.progress,
      message: response.data.message,
    };
  },

  // Search
  async search(params: SearchParams): Promise<SearchResult[]> {
    const response = await client.get('/search', { params });
    return response.data.results;
  },

  // Audio
  getAudioUrl(recordingId: number): string {
    return `${API_BASE_URL}/recordings/${recordingId}/audio`;
  },
};
