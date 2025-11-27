// Types for the Transcription Viewer application

export interface Word {
  word: string;
  start: number;
  end: number;
  probability?: number;
  confidence?: number;
}

export interface Segment {
  text: string;
  start: number;
  end: number;
  duration?: number;
  speaker?: string;
  words?: Word[];
}

export interface Recording {
  id: number;
  filename: string;
  filepath: string;
  recorded_at: string;
  imported_at: string;
  duration_seconds: number;
  word_count: number;
  has_diarization: boolean;
}

export interface Transcription {
  recording_id: number;
  segments: Segment[];
}

export interface SearchResult {
  recording_id: number;
  recording: Recording;
  word: string;
  start_time: number;
  end_time: number;
  context: string; // Surrounding text for context
}

export interface RecordingsByDate {
  [date: string]: Recording[];
}

export interface SearchParams {
  query: string;
  from_date?: string;
  to_date?: string;
  fuzzy?: boolean;
}

export interface ImportJob {
  id: number;
  filename: string;
  status: 'pending' | 'transcribing' | 'completed' | 'failed';
  progress?: number;
  message?: string;
}
