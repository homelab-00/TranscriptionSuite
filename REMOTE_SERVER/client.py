"""
Remote transcription client for Linux and Android.

This client connects to the RemoteTranscriptionServer via WebSocket
and streams audio for transcription.

Features:
- Records audio at 16kHz mono (native Whisper format)
- Token-based authentication
- Dual-channel connection (control + data)
- Works on Linux (PyAudio) and Android (android.media)

Usage:
    # Generate a token on the server first, then:
    client = RemoteTranscriptionClient(
        server_host="192.168.1.100",
        token="your_auth_token"
    )
    client.start_recording()
    # ... speak ...
    result = client.stop_and_transcribe()
    print(result["text"])
"""

import asyncio
import json
import logging
import queue
import struct
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Audio constants - record at native Whisper sample rate
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHUNK_DURATION_MS = 40  # 40ms chunks
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 640 samples

# Default ports (match server)
DEFAULT_CONTROL_PORT = 8011
DEFAULT_DATA_PORT = 8012


class ClientState(Enum):
    """Client connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


@dataclass
class TranscriptionResult:
    """Transcription result from the server."""

    text: str
    words: list
    duration: float
    language: str
    is_final: bool


class AudioRecorder:
    """
    Cross-platform audio recorder.

    Uses PyAudio on Linux/Desktop and android.media on Android.
    Records at 16kHz mono (native Whisper format) to minimize bandwidth.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        chunk_samples: int = CHUNK_SAMPLES,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Recording sample rate (default 16kHz)
            channels: Number of channels (default mono)
            chunk_samples: Samples per chunk
            on_audio_chunk: Callback for each audio chunk
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_samples = chunk_samples
        self.on_audio_chunk = on_audio_chunk

        self._is_recording = False
        self._audio_interface = None
        self._stream = None
        self._record_thread: Optional[threading.Thread] = None

        # Detect platform
        self._platform = self._detect_platform()
        logger.info(f"AudioRecorder initialized for platform: {self._platform}")

    def _detect_platform(self) -> str:
        """Detect the current platform."""
        try:
            # Check for Android
            import importlib.util

            if importlib.util.find_spec("android") is not None:
                return "android"
        except ImportError:
            pass

        # Default to desktop (Linux/Windows/Mac)
        return "desktop"

    def _init_desktop_audio(self) -> None:
        """Initialize PyAudio for desktop platforms."""
        try:
            import pyaudio

            self._audio_interface = pyaudio.PyAudio()
        except ImportError:
            raise RuntimeError("PyAudio not available. Install with: pip install pyaudio")

    def _init_android_audio(self) -> None:
        """Initialize audio recording for Android."""
        try:
            from jnius import autoclass  # type: ignore

            # Android audio classes
            self._AudioRecord = autoclass("android.media.AudioRecord")
            self._AudioFormat = autoclass("android.media.AudioFormat")
            self._MediaRecorder = autoclass("android.media.MediaRecorder")

            # Audio source constants
            self._AUDIO_SOURCE_MIC = (
                self._MediaRecorder.AudioSource.MIC  # type: ignore
            )
            self._CHANNEL_IN_MONO = (
                self._AudioFormat.CHANNEL_IN_MONO  # type: ignore
            )
            self._ENCODING_PCM_16BIT = (
                self._AudioFormat.ENCODING_PCM_16BIT  # type: ignore
            )

        except ImportError:
            raise RuntimeError(
                "pyjnius not available. This is required for Android audio recording."
            )

    def start(self) -> None:
        """Start recording audio."""
        if self._is_recording:
            logger.warning("Already recording")
            return

        if self._platform == "android":
            self._start_android_recording()
        else:
            self._start_desktop_recording()

        self._is_recording = True
        logger.info("Recording started")

    def _start_desktop_recording(self) -> None:
        """Start recording on desktop (PyAudio)."""
        if self._audio_interface is None:
            self._init_desktop_audio()

        import pyaudio

        # Open audio stream
        self._stream = self._audio_interface.open(  # type: ignore
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_samples,
        )

        # Start recording thread
        self._record_thread = threading.Thread(target=self._desktop_record_loop)
        self._record_thread.daemon = True
        self._record_thread.start()

    def _desktop_record_loop(self) -> None:
        """Recording loop for desktop."""
        while self._is_recording and self._stream:
            try:
                # Read audio chunk
                audio_data = self._stream.read(
                    self.chunk_samples, exception_on_overflow=False
                )

                # Call callback if set
                if self.on_audio_chunk:
                    self.on_audio_chunk(audio_data)

            except Exception as e:
                logger.error(f"Error reading audio: {e}")
                break

    def _start_android_recording(self) -> None:
        """Start recording on Android."""
        if self._AudioRecord is None:
            self._init_android_audio()

        # Calculate buffer size
        min_buffer = self._AudioRecord.getMinBufferSize(  # type: ignore
            self.sample_rate,
            self._CHANNEL_IN_MONO,  # type: ignore
            self._ENCODING_PCM_16BIT,  # type: ignore
        )
        buffer_size = max(min_buffer, self.chunk_samples * 2)

        # Create AudioRecord instance
        self._android_recorder = self._AudioRecord(  # type: ignore
            self._AUDIO_SOURCE_MIC,  # type: ignore
            self.sample_rate,
            self._CHANNEL_IN_MONO,  # type: ignore
            self._ENCODING_PCM_16BIT,  # type: ignore
            buffer_size,
        )

        # Start recording
        self._android_recorder.startRecording()  # type: ignore

        # Start recording thread
        self._record_thread = threading.Thread(target=self._android_record_loop)
        self._record_thread.daemon = True
        self._record_thread.start()

    def _android_record_loop(self) -> None:
        """Recording loop for Android."""
        buffer = bytearray(self.chunk_samples * 2)  # 16-bit = 2 bytes per sample

        while self._is_recording and self._android_recorder:
            try:
                # Read audio
                bytes_read = self._android_recorder.read(  # type: ignore
                    buffer, 0, len(buffer)
                )

                if bytes_read > 0:
                    audio_data = bytes(buffer[:bytes_read])
                    if self.on_audio_chunk:
                        self.on_audio_chunk(audio_data)

            except Exception as e:
                logger.error(f"Error reading Android audio: {e}")
                break

    def stop(self) -> None:
        """Stop recording."""
        self._is_recording = False

        if self._record_thread:
            self._record_thread.join(timeout=1.0)
            self._record_thread = None

        if self._platform == "android":
            if hasattr(self, "_android_recorder") and self._android_recorder:
                self._android_recorder.stop()  # type: ignore
                self._android_recorder.release()  # type: ignore
                self._android_recorder = None
        else:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None

        logger.info("Recording stopped")

    def cleanup(self) -> None:
        """Clean up audio resources."""
        self.stop()
        if self._audio_interface:
            self._audio_interface.terminate()
            self._audio_interface = None


class RemoteTranscriptionClient:
    """
    Client for remote transcription server.

    Connects to the server via WebSocket and streams audio for transcription.
    Works on both Linux and Android.
    """

    def __init__(
        self,
        server_host: str,
        token: str,
        control_port: int = DEFAULT_CONTROL_PORT,
        data_port: int = DEFAULT_DATA_PORT,
        use_tls: bool = False,
        on_realtime: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[TranscriptionResult], None]] = None,
        on_state_change: Optional[Callable[[ClientState], None]] = None,
    ):
        """
        Initialize the client.

        Args:
            server_host: Server hostname or IP
            token: Authentication token from server
            control_port: Control channel port
            data_port: Data channel port
            use_tls: Use secure WebSocket (wss://)
            on_realtime: Callback for real-time transcription updates
            on_final: Callback for final transcription result
            on_state_change: Callback for state changes
        """
        self.server_host = server_host
        self.token = token
        self.control_port = control_port
        self.data_port = data_port
        self.use_tls = use_tls

        # Callbacks
        self.on_realtime = on_realtime
        self.on_final = on_final
        self.on_state_change = on_state_change

        # State
        self._state = ClientState.DISCONNECTED
        self._control_ws = None
        self._data_ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None

        # Audio
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._recorder: Optional[AudioRecorder] = None

        # Results
        self._final_result: Optional[TranscriptionResult] = None
        self._result_event = threading.Event()

        logger.info(f"Client initialized for server: {server_host}")

    def _set_state(self, state: ClientState) -> None:
        """Update client state and notify callback."""
        self._state = state
        if self.on_state_change:
            self.on_state_change(state)

    @property
    def state(self) -> ClientState:
        """Get current client state."""
        return self._state

    @property
    def ws_scheme(self) -> str:
        """Get WebSocket URL scheme."""
        return "wss" if self.use_tls else "ws"

    def _build_audio_chunk(self, audio_data: bytes) -> bytes:
        """Build a binary audio chunk for transmission."""
        metadata = json.dumps(
            {
                "sample_rate": SAMPLE_RATE,
                "timestamp_ns": time.time_ns(),
                "sequence": 0,
            }
        ).encode("utf-8")

        # Format: [4 bytes metadata length][metadata JSON][audio PCM data]
        header = struct.pack("<I", len(metadata))
        return header + metadata + audio_data

    def _on_audio_chunk(self, audio_data: bytes) -> None:
        """Callback when audio chunk is recorded."""
        self._audio_queue.put(audio_data)

    async def _connect_control(self) -> bool:
        """Connect to control channel and authenticate."""
        import websockets

        url = f"{self.ws_scheme}://{self.server_host}:{self.control_port}"
        logger.info(f"Connecting to control channel: {url}")

        try:
            self._control_ws = await websockets.connect(url)

            # Send authentication
            auth_msg = json.dumps(
                {
                    "type": "auth",
                    "data": {"token": self.token},
                    "timestamp": time.time(),
                }
            )
            await self._control_ws.send(auth_msg)

            # Wait for response
            response = await asyncio.wait_for(self._control_ws.recv(), timeout=10.0)
            resp_data = json.loads(response)

            if resp_data["type"] == "auth_ok":
                logger.info("Control channel authenticated")
                return True
            elif resp_data["type"] == "session_busy":
                logger.error(
                    f"Server busy: {resp_data['data'].get('message', 'Another user active')}"
                )
                return False
            else:
                logger.error(f"Authentication failed: {resp_data}")
                return False

        except Exception as e:
            logger.error(f"Control connection failed: {e}")
            return False

    async def _connect_data(self) -> bool:
        """Connect to data channel and authenticate."""
        import websockets

        url = f"{self.ws_scheme}://{self.server_host}:{self.data_port}"
        logger.info(f"Connecting to data channel: {url}")

        try:
            self._data_ws = await websockets.connect(url)

            # Send authentication
            auth_msg = json.dumps(
                {
                    "type": "auth",
                    "data": {"token": self.token},
                    "timestamp": time.time(),
                }
            )
            await self._data_ws.send(auth_msg)

            # Wait for response
            response = await asyncio.wait_for(self._data_ws.recv(), timeout=10.0)
            resp_data = json.loads(response)

            if resp_data["type"] == "auth_ok":
                logger.info("Data channel authenticated")
                return True
            else:
                logger.error(f"Data auth failed: {resp_data}")
                return False

        except Exception as e:
            logger.error(f"Data connection failed: {e}")
            return False

    async def _send_audio_loop(self) -> None:
        """Loop to send audio chunks to server."""
        while self._state == ClientState.RECORDING:
            try:
                # Get audio chunk with timeout
                try:
                    audio_data = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Build and send chunk
                if self._data_ws:
                    chunk = self._build_audio_chunk(audio_data)
                    await self._data_ws.send(chunk)

            except Exception as e:
                logger.error(f"Error sending audio: {e}")
                break

    async def _receive_control_loop(self) -> None:
        """Loop to receive control messages from server."""
        while self._state in (ClientState.RECORDING, ClientState.TRANSCRIBING):
            try:
                if self._control_ws:
                    message = await asyncio.wait_for(self._control_ws.recv(), timeout=1.0)
                    data = json.loads(message)
                    await self._handle_control_message(data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if self._state != ClientState.DISCONNECTED:
                    logger.error(f"Error receiving control message: {e}")
                break

    async def _handle_control_message(self, data: Dict[str, Any]) -> None:
        """Handle a control message from server."""
        msg_type = data.get("type", "")

        if msg_type == "realtime":
            text = data.get("data", {}).get("text", "")
            if self.on_realtime and text:
                self.on_realtime(text)

        elif msg_type == "final":
            result = TranscriptionResult(
                text=data["data"].get("text", ""),
                words=data["data"].get("words", []),
                duration=data["data"].get("duration", 0.0),
                language=data["data"].get("language", ""),
                is_final=True,
            )
            self._final_result = result
            self._result_event.set()

            if self.on_final:
                self.on_final(result)

        elif msg_type == "session_stopped":
            logger.info("Session stopped by server")
            self._result_event.set()

        elif msg_type == "error":
            logger.error(f"Server error: {data.get('data', {}).get('message', '')}")

    async def _async_connect(self) -> bool:
        """Async method to connect to server."""
        self._set_state(ClientState.CONNECTING)

        # Connect control channel first
        if not await self._connect_control():
            self._set_state(ClientState.ERROR)
            return False

        # Then data channel
        if not await self._connect_data():
            self._set_state(ClientState.ERROR)
            return False

        self._set_state(ClientState.CONNECTED)
        return True

    async def _async_start_recording(self, language: Optional[str] = None) -> bool:
        """Async method to start recording session."""
        if self._control_ws is None:
            return False

        # Send start command
        start_msg = json.dumps(
            {
                "type": "start",
                "data": {
                    "language": language,
                    "enable_realtime": self.on_realtime is not None,
                    "word_timestamps": True,
                },
                "timestamp": time.time(),
            }
        )
        await self._control_ws.send(start_msg)

        # Wait for confirmation
        response = await self._control_ws.recv()
        resp_data = json.loads(response)

        if resp_data["type"] == "session_started":
            self._set_state(ClientState.RECORDING)
            return True
        else:
            logger.error(f"Failed to start session: {resp_data}")
            return False

    async def _async_stop_recording(self) -> Optional[TranscriptionResult]:
        """Async method to stop recording and get transcription."""
        if self._control_ws is None:
            return None

        self._set_state(ClientState.TRANSCRIBING)

        # Send stop command
        stop_msg = json.dumps(
            {
                "type": "stop",
                "data": {},
                "timestamp": time.time(),
            }
        )
        await self._control_ws.send(stop_msg)

        # Result will come via control message handler
        return self._final_result

    def connect(self) -> bool:
        """
        Connect to the transcription server.

        Returns:
            True if connected successfully
        """

        def run_async():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            return self._loop.run_until_complete(self._async_connect())

        # Run in current thread if no event loop, else in thread
        try:
            asyncio.get_running_loop()
            # Already in async context, run directly
            return asyncio.run(self._async_connect())
        except RuntimeError:
            return run_async()

    def start_recording(self, language: Optional[str] = None) -> bool:
        """
        Start recording audio.

        Args:
            language: Optional language code for transcription

        Returns:
            True if recording started
        """
        if self._state != ClientState.CONNECTED:
            if not self.connect():
                return False

        # Initialize recorder
        self._recorder = AudioRecorder(
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            chunk_samples=CHUNK_SAMPLES,
            on_audio_chunk=self._on_audio_chunk,
        )

        # Start async session
        async def start():
            if await self._async_start_recording(language):
                # Start audio sending loop in background
                asyncio.create_task(self._send_audio_loop())
                asyncio.create_task(self._receive_control_loop())
                return True
            return False

        if self._loop:
            future = asyncio.run_coroutine_threadsafe(start(), self._loop)
            if not future.result(timeout=10.0):
                return False
        else:
            loop = asyncio.new_event_loop()
            self._loop = loop

            def run_loop():
                asyncio.set_event_loop(loop)
                loop.run_until_complete(start())
                loop.run_forever()

            self._async_thread = threading.Thread(target=run_loop)
            self._async_thread.daemon = True
            self._async_thread.start()

            # Give it time to start
            time.sleep(0.5)
            if self._state != ClientState.RECORDING:
                return False

        # Start audio recording
        self._recorder.start()
        return True

    def stop_and_transcribe(self, timeout: float = 60.0) -> Optional[TranscriptionResult]:
        """
        Stop recording and get transcription.

        Args:
            timeout: Maximum time to wait for transcription

        Returns:
            TranscriptionResult or None if failed
        """
        if self._state != ClientState.RECORDING:
            logger.warning("Not recording")
            return None

        # Stop audio recording
        if self._recorder:
            self._recorder.stop()

        # Clear result and wait for new one
        self._final_result = None
        self._result_event.clear()

        # Send stop command
        async def stop():
            return await self._async_stop_recording()

        if self._loop:
            asyncio.run_coroutine_threadsafe(stop(), self._loop)

        # Wait for result
        if self._result_event.wait(timeout=timeout):
            return self._final_result
        else:
            logger.error("Transcription timeout")
            return None

    def disconnect(self) -> None:
        """Disconnect from server."""
        self._set_state(ClientState.DISCONNECTED)

        if self._recorder:
            self._recorder.cleanup()
            self._recorder = None

        control_ws = self._control_ws
        data_ws = self._data_ws

        async def _close_ws() -> None:
            if control_ws:
                await control_ws.close()
            if data_ws:
                await data_ws.close()

        if self._loop:
            asyncio.run_coroutine_threadsafe(_close_ws(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)

        self._control_ws = None
        self._data_ws = None
        self._loop = None

        logger.info("Disconnected from server")


# Convenience function for simple usage
def transcribe_audio(
    server_host: str,
    token: str,
    duration_seconds: float = 10.0,
    language: Optional[str] = None,
    control_port: int = DEFAULT_CONTROL_PORT,
    data_port: int = DEFAULT_DATA_PORT,
) -> Optional[str]:
    """
    Simple function to record and transcribe audio.

    Args:
        server_host: Server hostname or IP
        token: Authentication token
        duration_seconds: Recording duration
        language: Optional language code
        control_port: Control channel port
        data_port: Data channel port

    Returns:
        Transcribed text or None
    """
    client = RemoteTranscriptionClient(
        server_host=server_host,
        token=token,
        control_port=control_port,
        data_port=data_port,
    )

    try:
        if not client.start_recording(language=language):
            return None

        # Record for specified duration
        time.sleep(duration_seconds)

        # Get transcription
        result = client.stop_and_transcribe()
        return result.text if result else None

    finally:
        client.disconnect()


if __name__ == "__main__":
    # Simple CLI for testing
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Remote Transcription Client")
    parser.add_argument("--host", required=True, help="Server hostname or IP")
    parser.add_argument("--token", required=True, help="Authentication token")
    parser.add_argument("--duration", type=float, default=10.0, help="Recording duration")
    parser.add_argument("--language", help="Language code (e.g., en, el)")
    parser.add_argument("--control-port", type=int, default=8011)
    parser.add_argument("--data-port", type=int, default=8012)

    args = parser.parse_args()

    print(f"Recording for {args.duration} seconds...")
    text = transcribe_audio(
        server_host=args.host,
        token=args.token,
        duration_seconds=args.duration,
        language=args.language,
        control_port=args.control_port,
        data_port=args.data_port,
    )

    if text:
        print(f"\nTranscription:\n{text}")
    else:
        print("\nTranscription failed")
