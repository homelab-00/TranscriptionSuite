# Transcription Viewer - Backend

FastAPI backend for the Transcription Viewer application.

## Features

- **Recordings Management**: List, view, and delete transcribed recordings
- **Full-Text Search**: Search words in transcriptions using SQLite FTS5
- **Audio Streaming**: Stream audio files for playback
- **Background Transcription**: Import and transcribe audio files asynchronously

## API Endpoints

### Recordings

- `GET /api/recordings` - List all recordings (with optional date filtering)
- `GET /api/recordings/{id}` - Get a specific recording
- `GET /api/recordings/{id}/transcription` - Get full transcription with word timestamps
- `GET /api/recordings/{id}/audio` - Stream audio file
- `DELETE /api/recordings/{id}` - Delete a recording

### Search

- `GET /api/search?q={query}` - Search for words in transcriptions
  - `fuzzy=true` - Enable prefix matching
  - `start_date` / `end_date` - Filter by date range

### Transcribe

- `POST /api/transcribe/file` - Import and transcribe a local file
- `POST /api/transcribe/upload` - Upload and transcribe an audio file
- `GET /api/transcribe/status/{id}` - Check transcription job status

## Database Schema

The application uses SQLite with FTS5 for efficient full-text search:

- `recordings` - Audio file metadata
- `segments` - Transcription segments (speaker turns)
- `words` - Individual words with timestamps
- `words_fts` - FTS5 virtual table for search

## Setup

```bash
cd backend

# Create virtual environment
uv venv

# Install dependencies
uv sync

# Run the server
uv run uvicorn main:app --reload --port 8000
```

## Development

The backend connects to the core transcription module in `_core/SCRIPT/` for actual transcription work.
