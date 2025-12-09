import axios from 'axios';
import { Recording, Transcription, SearchResult, RecordingsByDate, SearchParams, ImportJob, LLMStatus, LLMResponse, LLMRequest } from '../types';

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

  // Summary
  async updateSummary(recordingId: number, summary: string | null): Promise<void> {
    await client.patch(`/recordings/${recordingId}/summary`, { summary });
  },

  async getSummary(recordingId: number): Promise<string | null> {
    const response = await client.get(`/recordings/${recordingId}/summary`);
    return response.data.summary;
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
    // Transform frontend params to backend expected params
    const apiParams = {
      q: params.query,
      fuzzy: params.fuzzy,
      start_date: params.from_date,
      end_date: params.to_date,
    };
    const response = await client.get('/search', { params: apiParams });
    // Transform the raw results to include the Recording object
    return response.data.results.map((r: {
      id: number | null;
      recording_id: number;
      word: string;
      start_time: number;
      end_time: number;
      filename: string;
      recorded_at: string;
      speaker: string | null;
      context: string;
      match_type: 'word' | 'filename' | 'summary';
    }) => ({
      recording_id: r.recording_id,
      recording: {
        id: r.recording_id,
        filename: r.filename,
        filepath: '',
        recorded_at: r.recorded_at,
        imported_at: r.recorded_at,
        duration_seconds: 0,
        word_count: 0,
        has_diarization: false,
      },
      word: r.word,
      start_time: r.start_time,
      end_time: r.end_time,
      context: r.context,
      match_type: r.match_type,
    }));
  },

  // Audio
  getAudioUrl(recordingId: number): string {
    return `${API_BASE_URL}/recordings/${recordingId}/audio`;
  },

  // LLM endpoints
  async getLLMStatus(): Promise<LLMStatus> {
    const response = await client.get('/llm/status');
    return response.data;
  },

  async processWithLLM(request: LLMRequest): Promise<LLMResponse> {
    const response = await client.post('/llm/process', request);
    return response.data;
  },

  // Streaming LLM processing - returns an EventSource-like interface
  async processWithLLMStream(
    request: LLMRequest,
    onChunk: (content: string) => void,
    onDone: () => void,
    onError: (error: string) => void
  ): Promise<AbortController> {
    const controller = new AbortController();
    
    try {
      const response = await fetch(`${API_BASE_URL}/llm/process/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response body');
      }

      const decoder = new TextDecoder();
      
      const processStream = async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const dataStr = line.slice(6);
                try {
                  const data = JSON.parse(dataStr);
                  if (data.content) {
                    onChunk(data.content);
                  } else if (data.done) {
                    onDone();
                    return;
                  } else if (data.error) {
                    onError(data.error);
                    return;
                  }
                } catch {
                  // Ignore parse errors for incomplete chunks
                }
              }
            }
          }
          onDone();
        } catch (error) {
          if ((error as Error).name !== 'AbortError') {
            onError((error as Error).message);
          }
        }
      };
      
      processStream();
    } catch (error) {
      onError((error as Error).message);
    }
    
    return controller;
  },

  async summarizeRecording(recordingId: number, customPrompt?: string): Promise<LLMResponse> {
    const response = await client.post(
      `/llm/summarize/${recordingId}`,
      null,
      { params: customPrompt ? { custom_prompt: customPrompt } : {} }
    );
    return response.data;
  },
};
