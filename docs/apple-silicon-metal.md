# Apple Silicon / Metal Backend — Setup & Usage Guide

---

## Overview

The Metal/MLX backend enables hardware-accelerated Whisper transcription on Apple Silicon
Macs using the `mlx-whisper` package. When the Metal runtime profile is selected, the
dashboard manages a native uvicorn server process directly rather than using Docker.

| Component | Details |
|-----------|---------|
| Acceleration | Apple Metal GPU via `mlx-whisper` |
| Diarization | PyAnnote on MPS (falls back to CPU) |
| Server | Native uvicorn (no Docker) |
| Models | `mlx-community/*` Whisper variants |

---

## 1. Prerequisites

1. **Apple Silicon Mac** (M1 or later) running macOS 12+.
2. Python backend dependencies installed with the `mlx` extra:

   ```bash
   cd server/backend
   uv sync --extra mlx
   ```

3. A [Hugging Face](https://huggingface.co/) account with access to the PyAnnote
   diarization models (required only for diarization):
   - Accept [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - Accept [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - Generate an API token at <https://huggingface.co/settings/tokens>

---

## 2. Server Startup — Bare-Metal (Metal/MLX)

The server runs directly on macOS without Docker via the `.venv` uvicorn binary.
All path arguments must be fully expanded (no `$HOME` in quoted env vars on macOS).

```bash
cd /path/to/TranscriptionSuite

DATA_DIR="/Users/<you>/Library/Application Support/TranscriptionSuite/data" \
HF_HOME="/Users/<you>/Library/Application Support/TranscriptionSuite/models" \
HF_TOKEN="hf_..." \
MAIN_TRANSCRIBER_MODEL="mlx-community/whisper-large-v3-mlx" \
server/backend/.venv/bin/uvicorn server.api.main:app \
  --host 0.0.0.0 --port 9786
```

> **Tip — debug logging:** Add `LOG_LEVEL=DEBUG LOG_DIR="$DATA_DIR/logs"` to the
> env block above to get a structured JSON log at `$LOG_DIR/server.log`.

The server is ready when:

```bash
curl -s http://localhost:9786/ready | python3 -m json.tool
```

returns `"loaded": true` with `"backend": "mlx_whisper"` and `"features.mlx.available": true`.

---

## 3. Metal Runtime Profile — Dashboard

In the dashboard the Metal profile can be selected from two places:

**Settings → Server Profile**

1. Open the dashboard (e.g. `npm run dev:electron` from `dashboard/`).
2. Click the gear ⚙ icon → **Settings**.
3. Under *Runtime Profile*, select **Metal (Apple Silicon)**.
4. The model selector will show only `mlx-community/*` models.
5. Click **Save**. The dashboard stores `runtimeProfile: "metal"` in its config.

**Server View (quick toggle)**

- The Server panel also exposes the profile dropdown so you can switch without opening Settings.

When `metal` is selected the dashboard bypasses Docker entirely. The Server view
shows "Native Process Running" / "Server Offline" status and a ⚡ Metal badge.
Start/stop the server from the **Server** view using the native process controls.

---

## 4. Transcribing a File

### 4a. Terminal (curl)

Basic transcription, no diarization:

```bash
curl -s -X POST http://localhost:9786/api/transcribe/file \
  -F "file=@/path/to/audio.wav" \
  -w "\nHTTP_STATUS: %{http_code}\n"
```

With speaker diarization (requires `HF_TOKEN` and PyAnnote model access):

```bash
curl -s -X POST http://localhost:9786/api/transcribe/file \
  -F "file=@/path/to/audio.wav" \
  -F "diarization=true" \
  -w "\nHTTP_STATUS: %{http_code}\n"
```

The response is a JSON object:

```jsonc
{
  "text": "...",                  // full transcript
  "language": "en",
  "language_probability": 1.0,
  "duration": 60.0,
  "num_speakers": 2,              // present when diarization=true
  "segments": [
    {
      "text": "Hello world.",
      "start": 0.0,
      "end": 2.5,
      "speaker": "SPEAKER_00",   // present when diarization=true
      "words": [...]              // per-word timestamps + speaker
    }
  ],
  "words": [...]                  // flat word list with speaker labels
}
```

Useful optional form fields:

| Field | Default | Description |
|-------|---------|-------------|
| `language` | auto-detect | BCP-47 code, e.g. `"en"` |
| `diarization` | `false` | Enable speaker diarization |
| `min_speakers` | auto | Hint minimum speaker count |
| `max_speakers` | auto | Hint maximum speaker count |
| `initial_prompt` | none | Context string to guide transcription |

### 4b. Dashboard — File Transcription

1. Open the dashboard.
2. Navigate to the **Transcribe** view.
3. Drag-and-drop or browse to an audio/video file.
4. Enable *Speaker Diarization* if desired.
5. Click **Transcribe**.

Results are shown inline and can be exported as `.srt` or `.txt`.

### 4c. Dashboard — Audio Notebook

Files can also be sent to the Audio Notebook for storage and later review:
- Enable *Add to Notebook* in the transcription panel, or
- Set `auto_add_to_audio_notebook: true` in `server/config.yaml`.

---

## 5. MLX Backend Notes

- **Model selection**: Any `mlx-community/*` Whisper model works (e.g.
  `mlx-community/whisper-large-v3-mlx`, `mlx-community/whisper-large-v3-turbo`).
  The backend is auto-selected when the model name matches `mlx-community/*`.
- **Beam search**: MLX Whisper only supports greedy decoding. If `beam_size > 1`
  is configured (the default is 5), the backend silently falls back to greedy.
  This has no user-visible impact.
- **Diarization**: PyAnnote diarization works with the MLX backend exactly as
  with other backends — transcription runs on Metal, diarization runs on MPS
  (or CPU if MPS is unavailable).
- **Performance**: ~3 s per minute of audio on an M-series chip with
  `whisper-large-v3-mlx`.
- **Async safety**: All MLX transcription calls are wrapped in
  `asyncio.to_thread()` to prevent blocking the FastAPI event loop.

---

## 6. Logging Configuration

Two env vars override the logging section of `server/config.yaml`:

| Variable | Config key | Example |
|----------|-----------|---------|
| `LOG_LEVEL` | `logging.level` | `DEBUG`, `INFO`, `WARNING` |
| `LOG_DIR` | `logging.directory` | `/path/to/logs` |

The log file is written to `$LOG_DIR/server.log` in structured JSON
(one object per line, via structlog).

Example tail / pretty-print:

```bash
tail -f "/Users/<you>/Library/Application Support/TranscriptionSuite/data/logs/server.log" \
  | python3 -c "import sys,json; [print(json.dumps(json.loads(l),indent=2)) for l in sys.stdin]"
```

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `mlx_whisper not found` | MLX extra not installed | `uv sync --extra mlx` |
| `features.mlx.available: false` | Not Apple Silicon or wrong Python | Check `uname -m` → must be `arm64` |
| Diarization falls back to CPU | MPS memory pressure | Normal; use `device: cpu` in `config.yaml` to force |
| `DATA_DIR` not found errors | Path not created | `mkdir -p "$DATA_DIR/logs" "$DATA_DIR/audio" "$DATA_DIR/tokens"` |
| Server won't start on port 9786 | Port in use | `lsof -i :9786` then kill or change `--port` |

For full testing instructions see [docs/README_DEV.md](README_DEV.md#testing-bare-metal-mlx-functionality).
