# Transcription Viewer

A desktop application for managing and searching transcribed audio recordings with word-level timestamps.

## Features

- 📅 **Calendar View** - Browse recordings organized by date
- 🔍 **Full-Text Search** - Find specific words or phrases across all recordings
- ⏱️ **Word Timestamps** - Click any word to jump to that moment in the audio
- 🎵 **Audio Player** - Built-in player with timestamp-aware seeking
- 📁 **Auto-Import** - Import audio files and automatically transcribe them
- 🌙 **Dark Mode** - Easy on the eyes

## Architecture

```txt
_app-transcription-viewer/
├── backend/                 # Python FastAPI server
│   ├── main.py             # Server entry point
│   ├── database.py         # SQLite database operations
│   ├── transcription.py    # Integration with _core transcription
│   └── requirements.txt    # Python dependencies
│
├── src-tauri/              # Tauri (Rust) desktop wrapper
│   ├── src/
│   ├── Cargo.toml
│   └── tauri.conf.json
│
├── src/                    # React frontend
│   ├── components/         # UI components
│   ├── views/              # Page views
│   ├── hooks/              # Custom React hooks
│   ├── services/           # API calls
│   └── App.tsx
│
├── data/                   # Application data (created at runtime)
│   ├── recordings/         # Stored audio files
│   ├── transcriptions/     # JSON transcription files
│   └── transcription_viewer.db  # SQLite database
│
└── package.json
```

## Tech Stack

- **Desktop Shell**: Tauri (Rust + System WebView)
- **Frontend**: React 18 + TypeScript + MUI (Material-UI)
- **Backend**: FastAPI (Python)
- **Database**: SQLite with FTS5 for full-text search
- **Audio**: Howler.js

## Setup

### Prerequisites

- Node.js 18+
- Rust (for Tauri)
- Python 3.11+ with uv

### Installation

```bash
cd _app-transcription-viewer

# Install frontend dependencies
npm install

# Install backend dependencies  
cd backend
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
cd ..

# Install Tauri CLI
cargo install tauri-cli
```

### Development

```bash
# Start backend server
cd backend && source .venv/bin/activate && uvicorn main:app --reload

# In another terminal, start frontend dev server
npm run tauri dev
```

### Build for Production

```bash
npm run tauri build
```

## Integration with TranscriptionSuite

This app uses the transcription engine from `_core`:

1. User imports an audio file
2. Backend calls `_core/SCRIPT/static_transcriber.py`
3. Audio is transcribed with word timestamps
4. Results are saved to database and displayed

## Future Features

- [ ] LLM integration for summarization (via LM Studio)
- [ ] Export to various formats (SRT, TXT, etc.)
- [ ] Batch import
- [ ] Recording tags/categories
