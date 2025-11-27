import axios from 'axios';
import { Recording, Transcription, SearchResult, RecordingsByDate, SearchParams } from '../types';

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

interface TranscriptionStatus {
  recording_id: number;
  status: string;
  progress?: number;
  message?: string;
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

  async uploadFile(file: File, enableDiarization: boolean = false, enableWordTimestamps: boolean = true): Promise<TranscribeResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('enable_diarization', String(enableDiarization));
    formData.append('enable_word_timestamps', String(enableWordTimestamps));
    
    const response = await client.post('/transcribe/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  async getTranscriptionStatus(recordingId: number): Promise<TranscriptionStatus> {
    const response = await client.get(`/transcribe/status/${recordingId}`);
    return response.data;
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
