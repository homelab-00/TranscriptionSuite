#!/usr/bin/env python3
"""Batch-benchmark multiple STT models on one or more audio files.

Runs each model sequentially against every input file, measuring:
  - setup_time  : backend.load() + backend.warmup() (cold start including first JIT compile)
  - transcribe_time: backend.transcribe() wall time for the target audio
  - RTF         : transcribe_time / audio_duration  (lower is faster; 1.0x = real-time)
  - word_count  : words in the transcription

Outputs:
  - Console: timing table + per-model transcription text + word-level diff
  - JSON: benchmark_<timestamp>.json  (full results + segments, in --output-dir)

Usage examples
--------------
  # All MLX models on a file (default group when no --models/--group given):
  python scripts/benchmark_stt.py --input samples/input/clip.m4a

  # Directory of files, specific group:
  python scripts/benchmark_stt.py --dir samples/input/ --group mlx-whisper

  # Explicit model list with devices:
  python scripts/benchmark_stt.py \
      --models "mlx-community/whisper-tiny-asr-fp16" "Systran/faster-whisper-tiny@cpu" \
      --input clip.m4a

  # List available model groups:
  python scripts/benchmark_stt.py --list-groups

  # Skip warmup (include first-inference JIT in transcribe_time, not setup_time):
  python scripts/benchmark_stt.py --no-warmup --input clip.m4a

Notes
-----
- Activate the venv first: source server/backend/.venv/bin/activate
- Run from the project root so the server package resolves correctly.
- Model downloads are NOT included in setup_time if the model is already cached
  in ~/.cache/huggingface/ or ~/Library/Caches/mlx.  First-run times will be
  dominated by download; subsequent runs measure pure inference.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import importlib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Bootstrap: register `server` as a package alias so imports resolve without
# a pip-install.  Mirrors the pattern in server/backend/tests/conftest.py.
# ---------------------------------------------------------------------------

def _bootstrap_server_package() -> None:
    if "server" in sys.modules:
        return
    backend_root = Path(__file__).resolve().parent.parent / "server" / "backend"
    init_file = backend_root / "__init__.py"
    if not init_file.exists():
        raise RuntimeError(
            f"Cannot locate the server package at {backend_root}. "
            "Run this script from the project root with the venv activated."
        )
    spec = importlib.util.spec_from_file_location(
        "server", init_file, submodule_search_locations=[str(backend_root)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["server"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]


_bootstrap_server_package()

# ---------------------------------------------------------------------------
# Predefined model groups
# ---------------------------------------------------------------------------

MODEL_GROUPS: dict[str, list[str]] = {
    "mlx": [
        "mlx-community/VibeVoice-ASR-4bit",
        "mlx-community/VibeVoice-ASR-8bit",
        "mlx-community/VibeVoice-ASR-bf16",
        "mlx-community/whisper-tiny-asr-4bit",
        "mlx-community/whisper-tiny-asr-8bit",
        "mlx-community/whisper-tiny-asr-fp16",
        "mlx-community/whisper-small-asr-4bit",
        "mlx-community/whisper-small-asr-8bit",
        "mlx-community/whisper-small-asr-fp16",
        "mlx-community/whisper-large-v3-asr-4bit",
        "mlx-community/whisper-large-v3-asr-8bit",
        "mlx-community/whisper-large-v3-asr-fp16",
        "mlx-community/whisper-large-v3-turbo-asr-4bit",
        "mlx-community/whisper-large-v3-turbo-asr-8bit",
        "mlx-community/whisper-large-v3-turbo-asr-fp16",
        "mlx-community/parakeet-tdt-0.6b-v3",
        "Mediform/canary-1b-v2-mlx-q8",
        "eelcor/canary-1b-v2-mlx",
    ],
    "mlx-vibevoice": [
        "mlx-community/VibeVoice-ASR-4bit",
        "mlx-community/VibeVoice-ASR-8bit",
        "mlx-community/VibeVoice-ASR-bf16",
    ],
    "mlx-whisper": [
        "mlx-community/whisper-tiny-asr-4bit",
        "mlx-community/whisper-tiny-asr-8bit",
        "mlx-community/whisper-tiny-asr-fp16",
        "mlx-community/whisper-small-asr-4bit",
        "mlx-community/whisper-small-asr-8bit",
        "mlx-community/whisper-small-asr-fp16",
        "mlx-community/whisper-large-v3-asr-4bit",
        "mlx-community/whisper-large-v3-asr-8bit",
        "mlx-community/whisper-large-v3-asr-fp16",
        "mlx-community/whisper-large-v3-turbo-asr-4bit",
        "mlx-community/whisper-large-v3-turbo-asr-8bit",
        "mlx-community/whisper-large-v3-turbo-asr-fp16",
    ],
    "mlx-asr": [
        "mlx-community/parakeet-tdt-0.6b-v3",
        "Mediform/canary-1b-v2-mlx-q8",
        "eelcor/canary-1b-v2-mlx",
    ],
    "whisper": [
        "Systran/faster-whisper-tiny",
        "Systran/faster-whisper-small",
        "Systran/faster-whisper-small.en",
        "Systran/faster-distil-whisper-small.en",
        "Systran/faster-whisper-medium",
        "Systran/faster-whisper-medium.en",
        "Systran/faster-distil-whisper-medium.en",
        "Systran/faster-whisper-large-v3",
        "Systran/faster-distil-whisper-large-v3",
        "deepdml/faster-whisper-large-v3-turbo-ct2",
    ],
    "nemo": [
        "nvidia/parakeet-tdt-0.6b-v3",
        "nvidia/canary-1b-v2",
    ],
    "all": [
        "mlx-community/whisper-tiny-asr-fp16",
        "mlx-community/whisper-small-asr-fp16",
        "mlx-community/whisper-large-v3-turbo-asr-fp16",
        "mlx-community/parakeet-tdt-0.6b-v3",
        "Mediform/canary-1b-v2-mlx-q8",
        "Systran/faster-whisper-large-v3",
        "nvidia/parakeet-tdt-0.6b-v3",
    ],
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    model: str
    backend_type: str
    device: str
    audio_file: str
    audio_duration: float        # seconds
    setup_time: float            # backend.load() + backend.warmup()
    transcribe_time: float       # backend.transcribe() only
    rtf: float                   # transcribe_time / audio_duration
    text: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    word_count: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_audio_file(path: str, target_rate: int = 16000) -> tuple[np.ndarray, int]:
    """Load audio via the server's audio pipeline (handles WAV/MP3/M4A/FLAC)."""
    from server.core.audio_utils import load_audio
    return load_audio(str(path), target_sample_rate=target_rate)


# ---------------------------------------------------------------------------
# Model runner: load → warmup → transcribe → unload
# ---------------------------------------------------------------------------

def _warmup_backend(backend: Any, backend_type: str) -> None:
    """Call warmup() with the right signature, suppressing all errors."""
    try:
        if backend_type == "whisperx":
            backend.warmup(language="en")
        else:
            backend.warmup()
    except Exception:
        pass  # warmup is non-critical


def run_model(
    model_name: str,
    audio: np.ndarray,
    sample_rate: int,
    audio_file: str,
    device: str,
    do_warmup: bool = True,
) -> ModelResult:
    """Load, optionally warm up, transcribe, and unload a model.  Returns ModelResult."""
    from server.core.stt.backends.factory import create_backend, detect_backend_type

    audio_duration = len(audio) / max(sample_rate, 1)
    backend_type = detect_backend_type(model_name)

    # ---- Load (+ optional warmup) -------------------------------------------
    t_setup_start = time.perf_counter()
    try:
        backend = create_backend(model_name)
        backend.load(model_name, device=device)
        if do_warmup:
            _warmup_backend(backend, backend_type)
    except Exception as exc:
        return ModelResult(
            model=model_name,
            backend_type=backend_type,
            device=device,
            audio_file=audio_file,
            audio_duration=audio_duration,
            setup_time=time.perf_counter() - t_setup_start,
            transcribe_time=0.0,
            rtf=0.0,
            text="",
            error=f"load failed: {exc}",
        )
    setup_time = time.perf_counter() - t_setup_start

    # ---- Transcribe -----------------------------------------------------------
    t_tx_start = time.perf_counter()
    try:
        segments, _info = backend.transcribe(audio, audio_sample_rate=sample_rate)
        transcribe_time = time.perf_counter() - t_tx_start
    except Exception as exc:
        try:
            backend.unload()
        except Exception:
            pass
        return ModelResult(
            model=model_name,
            backend_type=backend_type,
            device=device,
            audio_file=audio_file,
            audio_duration=audio_duration,
            setup_time=setup_time,
            transcribe_time=time.perf_counter() - t_tx_start,
            rtf=0.0,
            text="",
            error=f"transcribe failed: {exc}",
        )

    # ---- Unload ---------------------------------------------------------------
    try:
        backend.unload()
    except Exception:
        pass

    text = " ".join(s.text.strip() for s in segments if s.text.strip())
    rtf = transcribe_time / audio_duration if audio_duration > 0 else 0.0
    seg_dicts = [{"text": s.text, "start": round(s.start, 3), "end": round(s.end, 3)} for s in segments]

    return ModelResult(
        model=model_name,
        backend_type=backend_type,
        device=device,
        audio_file=audio_file,
        audio_duration=audio_duration,
        setup_time=setup_time,
        transcribe_time=transcribe_time,
        rtf=rtf,
        text=text,
        segments=seg_dicts,
        word_count=len(text.split()) if text else 0,
    )


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _fmt_s(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    if seconds >= 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.2f}s"


def print_table(results: list[ModelResult]) -> None:
    """ASCII benchmark table."""
    COLS = ["Model", "Backend", "Device", "File", "Audio", "Setup", "Transcribe", "RTF", "Words", "Status"]
    rows: list[list[str]] = []
    for r in results:
        status = "OK" if r.error is None else f"ERR: {r.error[:38]}"
        rows.append([
            r.model,
            r.backend_type,
            r.device,
            Path(r.audio_file).name[:28],
            f"{r.audio_duration:.0f}s",
            _fmt_s(r.setup_time),
            _fmt_s(r.transcribe_time),
            f"{r.rtf:.3f}x",
            str(r.word_count),
            status,
        ])
    widths = [
        max(len(h), max((len(row[i]) for row in rows), default=0))
        for i, h in enumerate(COLS)
    ]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    def row_line(row: list[str]) -> str:
        return "|" + "|".join(f" {c:<{w}} " for c, w in zip(row, widths)) + "|"
    print("\n" + sep)
    print(row_line(COLS))
    print(sep)
    for row in rows:
        print(row_line(row))
    print(sep + "\n")


def print_transcriptions(results: list[ModelResult]) -> None:
    """Print each model's transcription side-by-side."""
    width = 110
    print("=" * width)
    print("TRANSCRIPTION OUTPUT PER MODEL")
    print("=" * width)
    for r in results:
        label = f"[{r.model} @ {r.device}]  ({r.backend_type})"
        print(f"\n{label}")
        print("-" * min(len(label) + 2, width))
        if r.error:
            print(f"  ERROR: {r.error}")
            continue
        if not r.text:
            print("  (empty)")
            continue
        # Word-wrap at ~width chars
        words = r.text.split()
        line = ""
        for w in words:
            if len(line) + len(w) + 1 > width - 2:
                print(f"  {line}")
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            print(f"  {line}")
    print()


def _similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard-like ratio via SequenceMatcher."""
    wa = text_a.lower().split()
    wb = text_b.lower().split()
    if not wa and not wb:
        return 1.0
    return difflib.SequenceMatcher(None, wa, wb).ratio()


def _word_diff(text_a: str, text_b: str, max_changes: int = 30) -> list[str]:
    """Return a list of human-readable change descriptions (deletions/insertions/replacements)."""
    wa = text_a.lower().split()
    wb = text_b.lower().split()
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    lines: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        a_phrase = " ".join(wa[i1:i2])
        b_phrase = " ".join(wb[j1:j2])
        if tag == "replace":
            lines.append(f"  [{a_phrase}] → [{b_phrase}]")
        elif tag == "delete":
            lines.append(f"  [-{a_phrase}]")
        elif tag == "insert":
            lines.append(f"  [+{b_phrase}]")
        if len(lines) >= max_changes:
            lines.append("  ... (truncated)")
            break
    return lines


def _score_model_for_reference(model_name: str) -> int:
    """Heuristic to pick the most accurate model for the diff."""
    name = model_name.lower()
    if "large-v3" in name:
        return 100
    if "large" in name:
        return 90
    if "canary" in name:
        return 80
    if "parakeet" in name:
        return 70
    if "medium" in name:
        return 60
    if "small" in name:
        return 50
    if "base" in name:
        return 40
    if "tiny" in name:
        return 30
    return 0


def print_diff(results: list[ModelResult]) -> None:
    """Print word-level diff comparing every successful model to the highest-accuracy reference."""
    successful = [r for r in results if r.error is None and r.text]
    if len(successful) < 2:
        print("(Too few successful results for diff comparison)\n")
        return

    width = 110
    best_ref = max(successful, key=lambda r: _score_model_for_reference(r.model))

    print("=" * width)
    print(f"TRANSCRIPTION DIFF  (Reference: {best_ref.model} @ {best_ref.device})")
    print("=" * width)
    
    for r in successful:
        if r is best_ref:
            continue
        sim = _similarity(best_ref.text, r.text)
        print(f"\n  Candidate : {r.model} @ {r.device}")
        print(f"  Similarity: {sim * 100:.1f}%")
        changes = _word_diff(best_ref.text, r.text)
        if not changes:
            print("  Changes   : (identical)")
        else:
            print(f"  Changes   : {len(changes)} phrase(s) differ")
            for c in changes:
                print(c)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_audio_files(args: argparse.Namespace) -> list[str]:
    files: list[str] = list(args.input or [])
    if args.dir:
        d = Path(args.dir)
        for glob in ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.opus", "*.ogg", "*.aac"):
            files.extend(str(p) for p in sorted(d.glob(glob)))
    return files


def _collect_models(args: argparse.Namespace) -> list[tuple[str, str]]:
    raw_models = []
    if args.models:
        raw_models = list(args.models)
    elif args.group:
        g = args.group.lower()
        if g not in MODEL_GROUPS:
            print(f"ERROR: unknown group '{g}'. Available: {', '.join(MODEL_GROUPS)}")
            sys.exit(1)
        raw_models = MODEL_GROUPS[g]
    else:
        # Default behavior: test all registered models across available hardware
        import platform
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False
        
        is_apple_silicon = sys.platform == "darwin" and platform.machine() == "arm64"
        
        # 1. Add MLX models if running on Apple Silicon
        if is_apple_silicon:
            for m in MODEL_GROUPS["mlx-whisper"] + MODEL_GROUPS["mlx-asr"]:
                raw_models.append(f"{m}@metal")

        # 2. Add PyTorch standard models on CUDA if available
        if has_cuda:
            for m in MODEL_GROUPS["whisper"] + MODEL_GROUPS["nemo"]:
                raw_models.append(f"{m}@cuda")

        # 3. Always add PyTorch standard models on CPU to establish a baseline
        for m in MODEL_GROUPS["whisper"]:
            raw_models.append(f"{m}@cpu")

        # NeMo models (Parakeet/Canary) require the NeMo toolkit which is only
        # available inside Docker with INSTALL_NEMO=true. Skip on bare-metal.
        if has_cuda:
            for m in MODEL_GROUPS["nemo"]:
                raw_models.append(f"{m}@cpu")
        
    parsed = []
    for m in raw_models:
        if "@" in m:
            name, device = m.rsplit("@", 1)
            parsed.append((name, device.lower()))
        else:
            parsed.append((m, args.device.lower()))
    return parsed


def _build_json_output(results: list[ModelResult], args: argparse.Namespace, models: list[tuple[str, str]], audio_files: list[str]) -> dict[str, Any]:
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "default_device": args.device,
        "warmup": not args.no_warmup,
        "models": [f"{name}@{dev}" for name, dev in models],
        "audio_files": audio_files,
        "results": [
            {
                "model": r.model,
                "backend_type": r.backend_type,
                "device": r.device,
                "audio_file": r.audio_file,
                "audio_duration_s": round(r.audio_duration, 3),
                "setup_time_s": round(r.setup_time, 3),
                "transcribe_time_s": round(r.transcribe_time, 3),
                "rtf": round(r.rtf, 4),
                "word_count": r.word_count,
                "text": r.text,
                "segments": r.segments,
                "error": r.error,
            }
            for r in results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="benchmark_stt.py",
        description="Batch-benchmark multiple STT models on audio file(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", "-i", metavar="FILE", action="append",
                        help="Audio input file (repeat for multiple files)")
    parser.add_argument("--dir", "-d", metavar="DIR",
                        help="Directory of audio files (WAV/MP3/M4A/FLAC)")
    parser.add_argument("--models", "-m", metavar="MODEL", nargs="+",
                        help="Explicit model HuggingFace repo IDs to test")
    parser.add_argument("--group", "-g", metavar="GROUP",
                        help=f"Predefined model group: {', '.join(MODEL_GROUPS)}")
    parser.add_argument("--device", default="cpu",
                        help="Device for non-MLX backends: cpu/cuda/metal (default: cpu)")
    parser.add_argument("--output-dir", "-o", metavar="DIR", default=".",
                        help="Directory for the JSON results file (default: .)")
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip warmup pass (first-inference JIT appears in transcribe_time)")
    parser.add_argument("--no-diff", action="store_true",
                        help="Skip the word-diff section")
    parser.add_argument("--list-groups", action="store_true",
                        help="Print available model groups and exit")

    args = parser.parse_args()

    if args.list_groups:
        for name, models in MODEL_GROUPS.items():
            print(f"\n{name}:")
            for m in models:
                print(f"  {m}")
        return

    audio_files = _collect_audio_files(args)
    if not audio_files:
        parser.error("No input files specified. Use --input FILE or --dir DIR.")

    models = _collect_models(args)
    do_warmup = not args.no_warmup

    print(f"\n{'='*70}")
    print("STT Benchmark")
    print(f"{'='*70}")
    print(f"Models ({len(models)}):")
    for m, d in models:
        print(f"  {m} @ {d}")
    print(f"\nAudio files ({len(audio_files)}):")
    for f in audio_files:
        print(f"  {f}")
    print(f"\nDevice : {args.device}")
    print(f"Warmup : {'yes' if do_warmup else 'no (--no-warmup)'}")
    print(f"{'='*70}\n")

    all_results: list[ModelResult] = []

    for audio_file in audio_files:
        print(f"\n{'─'*70}")
        print(f"Audio: {Path(audio_file).name}")
        print(f"{'─'*70}")
        try:
            audio, sample_rate = load_audio_file(audio_file)
            dur = len(audio) / sample_rate
            print(f"Loaded: {dur:.1f}s  |  {sample_rate} Hz  |  {len(audio):,} samples\n")
        except Exception as exc:
            print(f"ERROR loading audio: {exc}\n")
            continue

        file_results: list[ModelResult] = []
        for idx, (model_name, device) in enumerate(models, 1):
            warmup_tag = "" if do_warmup else " [no-warmup]"
            print(f"[{idx}/{len(models)}] {model_name} @ {device}{warmup_tag}", end=" ... ", flush=True)
            result = run_model(model_name, audio, sample_rate, audio_file, device, do_warmup)
            file_results.append(result)
            all_results.append(result)
            if result.error:
                print(f"FAILED  ({result.error})")
            else:
                print(
                    f"setup={_fmt_s(result.setup_time)}, "
                    f"transcribe={_fmt_s(result.transcribe_time)}, "
                    f"RTF={result.rtf:.3f}x, "
                    f"words={result.word_count}"
                )

        print_table(file_results)
        print_transcriptions(file_results)
        if not args.no_diff:
            print_diff(file_results)

    # Write JSON
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts_tag = time.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"benchmark_{ts_tag}.json"
    payload = _build_json_output(all_results, args, models, audio_files)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write CSV
    csv_path = output_dir / f"benchmark_{ts_tag}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        headers = [
            "model", "backend_type", "device", "audio_file", "audio_duration_s",
            "setup_time_s", "transcribe_time_s", "rtf", "word_count", "error", "text"
        ]
        writer.writerow(headers)
        for r in payload["results"]:
            writer.writerow([r.get(h, "") for h in headers])

    # Final summary across all files
    if len(audio_files) > 1:
        print(f"\n{'='*70}")
        print("COMBINED SUMMARY")
        print(f"{'='*70}")
        print_table(all_results)

    print(f"\nFull results written to:\n  - {json_path}\n  - {csv_path}\n")


if __name__ == "__main__":
    main()
