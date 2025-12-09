# AudioToTextRecorder Initialization Parameters

This document provides a detailed description of all parameters available when initializing the `AudioToTextRecorder` class in `stt_engine.py`.

## Core Transcription Parameters

- **`model`** (str, default=`"tiny"`): Specifies the size of the transcription model to use or the path to a converted model directory. Valid options are 'tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en', 'large-v1', 'large-v2', 'large-v3'. If a specific size is provided, the model is downloaded from the Hugging Face Hub.
- **`download_root`** (str, default=`None`): Specifies the root path where the Whisper models are downloaded. When empty, the default cache location is used.
- **`language`** (str, default=`""`): Language code for the speech-to-text engine. If not specified, the model will attempt to detect the language automatically.
- **`compute_type`** (str, default=`"default"`): Specifies the type of computation to be used for transcription. See [CTranslate2 Quantization](https://opennmt.net/CTranslate2/quantization.html) for details.
- **`device`** (str, default=`"cuda"`): The hardware device for the model to use. Can be either `"cuda"` or `"cpu"`.
- **`gpu_device_index`** (int or list, default=`0`): The ID of the GPU device to use. The model can also be loaded on multiple GPUs by passing a list of IDs (e.g., `[0, 1, 2, 3]`).
- **`batch_size`** (int, default=`16`): The batch size used for transcription inference.
- **`beam_size`** (int, default=`5`): The beam size to use for beam search decoding, which can improve accuracy at the cost of speed.
- **`initial_prompt`** (str or iterable, default=`None`): An initial prompt to guide the transcription model's style or context.
- **`suppress_tokens`** (list of int, default=`[-1]`): A list of token IDs to be suppressed from the transcription output.
- **`faster_whisper_vad_filter`** (bool, default=`True`): If `True`, uses the VAD filter from the `faster_whisper` library, which is more robust against background noise but requires additional GPU resources.
- **`normalize_audio`** (bool, default=`False`): If `True`, normalizes the audio to a specific range before processing, which can improve transcription quality.

## Audio & Recording Control

- **`use_microphone`** (bool, default=`True`): If `True`, the recorder captures audio from the system's microphone. If `False`, it relies on audio fed programmatically via the `feed_audio()` method.
- **`input_device_index`** (int, default=`None`): The index of the specific audio input device to use. If `None`, the system default is used.
- **`sample_rate`** (int, default=`16000`): The sample rate for audio recording. Changing this is not recommended as VAD models are sensitive to it.
- **`buffer_size`** (int, default=`512`): The buffer size for audio recording. Changing this may impact performance.
- **`handle_buffer_overflow`** (bool, default=`True`): If `True`, logs a warning and discards data when an input overflow occurs.

## Voice Activity Detection (VAD) Parameters

- **`silero_sensitivity`** (float, default=`0.4`): Sensitivity for the Silero VAD model, ranging from `0` (least sensitive) to `1` (most sensitive).
- **`silero_use_onnx`** (bool, default=`False`): If `True`, uses the ONNX version of the Silero model for potentially faster performance.
- **`silero_deactivity_detection`** (bool, default=`False`): If `True`, enables the Silero model for end-of-speech detection. This is more robust against noise but uses more GPU resources. When `False`, the default WebRTC VAD is used.
- **`webrtc_sensitivity`** (int, default=`3`): Sensitivity for the WebRTC VAD engine, ranging from `0` (most sensitive) to `3` (least sensitive).
- **`post_speech_silence_duration`** (float, default=`0.6`): The duration of silence (in seconds) that must follow speech before a recording is considered complete.
- **`min_length_of_recording`** (float, default=`0.5`): The minimum duration (in seconds) a recording must have to be considered valid.
- **`min_gap_between_recordings`** (float, default=`0`): The minimum time interval (in seconds) required between the end of one recording and the start of the next.
- **`pre_recording_buffer_duration`** (float, default=`1.0`): The duration (in seconds) of audio to keep in a pre-roll buffer to compensate for VAD latency.
- **`early_transcription_on_silence`** (int, default=`0`): If set to a value greater than `0` (milliseconds), the system will start a speculative transcription after that period of silence is detected. This can result in faster final transcriptions but may increase GPU load.

## Callbacks & Events

- **`on_recording_start`** (callable, default=`None`): A callback function executed when audio recording starts.
- **`on_recording_stop`** (callable, default=`None`): A callback function executed when audio recording stops.
- **`on_transcription_start`** (callable, default=`None`): A callback function executed just before the final transcription process begins.
- **`on_vad_start`** (callable, default=`None`): A callback function executed when VAD detects the start of speech.
- **`on_vad_stop`** (callable, default=`None`): A callback function executed when VAD detects the end of speech.
- **`on_recorded_chunk`** (callable, default=`None`): A callback executed for each chunk of audio recorded from the microphone.
- **`start_callback_in_new_thread`** (bool, default=`False`): If `True`, all callbacks will be executed in a separate thread to avoid blocking the main processing loop.

## Output Formatting

- **`ensure_sentence_starting_uppercase`** (bool, default=`True`): Ensures the final transcribed sentence starts with an uppercase letter.
- **`ensure_sentence_ends_with_period`** (bool, default=`True`): Ensures the final transcribed sentence ends with a period if no other punctuation is present.

## Miscellaneous

- **`spinner`** (bool, default=`True`): If `True`, shows a spinner animation in the console indicating the current state (e.g., "listening", "recording").
- **`level`** (int, default=`logging.WARNING`): The logging level for the module.
- **`debug_mode`** (bool, default=`False`): If `True`, enables additional debug output.
- **`no_log_file`** (bool, default=`False`): If `True`, prevents the creation of the `realtimesst.log` file.
- **`use_extended_logging`** (bool, default=`False`): Enables extensive logging for the audio recording worker, which can be useful for debugging audio issues.
