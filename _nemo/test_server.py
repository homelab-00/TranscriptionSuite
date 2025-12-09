#!/usr/bin/env python3
"""
Test client for the Canary transcription server.

This script tests the server by:
1. Checking if server is running (starts it if not)
2. Getting server status
3. Transcribing a test audio file (if provided)

Usage:
    # Just test server startup and status
    python test_server.py

    # Test with an audio file
    python test_server.py /path/to/audio.wav

    # Test with Greek audio
    python test_server.py /path/to/greek_audio.wav --language el
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 50051


def send_request(request: dict, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 300.0) -> dict:
    """Send a request to the server and return the response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
        request_bytes = (json.dumps(request) + "\n").encode("utf-8")
        sock.sendall(request_bytes)

        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        return json.loads(data.decode("utf-8").strip())
    finally:
        sock.close()


def check_server_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if the server is responding."""
    try:
        response = send_request({"action": "ping"}, host, port, timeout=2.0)
        return response.get("success", False)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Test the Canary transcription server")
    parser.add_argument("audio_file", nargs="?", help="Optional audio file to transcribe")
    parser.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--no-pnc", action="store_true", help="Disable punctuation/capitalization")

    args = parser.parse_args()

    print("=" * 60)
    print("Canary Server Test Client")
    print("=" * 60)

    # Check if server is running
    print(f"\n1. Checking server at {args.host}:{args.port}...")
    if check_server_running(args.host, args.port):
        print("   ✓ Server is running")
    else:
        print("   ✗ Server not running")
        print("\n   Please start the server first:")
        print(f"   cd _nemo && source .venv/bin/activate && python canary_server.py")
        sys.exit(1)

    # Get server status
    print("\n2. Getting server status...")
    try:
        response = send_request({"action": "status"}, args.host, args.port)
        if response.get("success"):
            status = response["result"]
            print(f"   Model loaded: {status.get('model_loaded', False)}")
            print(f"   Model name: {status.get('model_name', 'N/A')}")
            print(f"   Device: {status.get('device', 'N/A')}")
            if "vram_used_gb" in status:
                print(f"   VRAM used: {status['vram_used_gb']} GB / {status.get('vram_total_gb', 'N/A')} GB")
        else:
            print(f"   ✗ Failed to get status: {response.get('error')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Transcribe audio file if provided
    if args.audio_file:
        audio_path = Path(args.audio_file).resolve()
        if not audio_path.exists():
            print(f"\n✗ Audio file not found: {audio_path}")
            sys.exit(1)

        print(f"\n3. Transcribing: {audio_path}")
        print(f"   Language: {args.language}")
        print(f"   PNC: {not args.no_pnc}")

        start_time = time.time()
        try:
            response = send_request(
                {
                    "action": "transcribe",
                    "audio_path": str(audio_path),
                    "language": args.language,
                    "pnc": not args.no_pnc,
                },
                args.host,
                args.port,
                timeout=300.0,
            )

            elapsed = time.time() - start_time

            if response.get("success"):
                result = response["result"]
                print(f"\n   ✓ Transcription complete in {elapsed:.2f}s")
                print(f"   Audio duration: {result['duration']:.2f}s")
                print(f"   Processing time: {result['processing_time']:.2f}s")
                print(f"   Speed ratio: {result['duration'] / result['processing_time']:.1f}x realtime")
                print(f"   Words: {len(result.get('word_timestamps', []))}")
                print(f"\n   Text:\n   {'-' * 50}")
                print(f"   {result['text']}")
                print(f"   {'-' * 50}")

                # Show first few word timestamps
                words = result.get("word_timestamps", [])
                if words:
                    print(f"\n   First 5 word timestamps:")
                    for w in words[:5]:
                        print(f"   [{w['start']:.2f} - {w['end']:.2f}] {w['word']}")
            else:
                print(f"\n   ✗ Transcription failed: {response.get('error')}")
        except Exception as e:
            print(f"\n   ✗ Error: {e}")
    else:
        print("\n3. No audio file provided. To test transcription:")
        print(f"   python test_server.py /path/to/audio.wav --language el")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
