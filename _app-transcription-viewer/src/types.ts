// Types for the Transcription Viewer application

export interface Word {
  word: string;
  start: number;
  end: number;
  probability: number;
}

export interface Segment {
  text: string;
  start: number;
  end: number;
  duration: number;
  speaker?: string;
  words?: Word[];
}

export interface Recording {
  id: number;
  filename: string;
  original_path: string;
  internal_path: string;
  transcription_path: string;
  recorded_at: string;
  imported_at: string;
  duration_seconds: number;
  word_count: number;
  is_transcribed: boolean;
}

export interface Transcription {
  segments: Segment[];
  num_speakers: number;
  total_duration: number;
  total_words: number;
  metadata: {
    source_file: string;
    num_segments: number;
    speakers?: string[];
  };
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
