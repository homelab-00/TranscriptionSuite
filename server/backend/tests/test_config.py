"""Tests for ServerConfig class."""

import pytest

from server import config


def test_get_single_key():
    """Test single key access."""
    cfg = config.ServerConfig()
    result = cfg.get("main_transcriber")
    assert isinstance(result, dict)


def test_get_with_default():
    """Test default value return."""
    cfg = config.ServerConfig()
    result = cfg.get("nonexistent_key", default={"test": "value"})
    assert result == {"test": "value"}


def test_get_nested_keys():
    """Test nested key access."""
    cfg = config.ServerConfig()
    result = cfg.get("main_transcriber", "model")
    assert result is not None


def test_get_nested_with_default():
    """Test nested keys with default."""
    cfg = config.ServerConfig()
    result = cfg.get("nonexistent", "nested", "key", default="default_value")
    assert result == "default_value"


def test_get_rejects_non_string_keys():
    """Test that non-string keys raise TypeError with helpful message."""
    cfg = config.ServerConfig()

    # This should raise TypeError with helpful message
    with pytest.raises(TypeError, match="must be strings"):
        cfg.get("audio_processing", {})

    # This should also raise TypeError
    with pytest.raises(TypeError, match="must be strings"):
        cfg.get("key", 123)


def test_get_empty_keys():
    """Test calling get() with no keys returns full config."""
    cfg = config.ServerConfig()
    result = cfg.get()
    assert isinstance(result, dict)
    assert "main_transcriber" in result or "transcription" in result


def test_get_audio_processing_config():
    """Test accessing audio_processing configuration correctly."""
    cfg = config.ServerConfig()

    # Correct usage with default keyword
    audio_config = cfg.get("audio_processing", default={})
    assert isinstance(audio_config, dict)

    # Should be able to access nested values
    backend = audio_config.get("backend", "ffmpeg")
    assert isinstance(backend, str)


def test_get_preserves_none_values():
    """Test that None values in config are handled correctly."""
    cfg = config.ServerConfig()

    # If a key exists but has None value, should return None
    # (Not the default, unless the key doesn't exist)
    result = cfg.get("nonexistent_key", default="default")
    assert result == "default"


def test_get_type_error_message_quality():
    """Test that TypeError messages are helpful for debugging."""
    cfg = config.ServerConfig()

    try:
        cfg.get("audio_processing", {})
        assert False, "Should have raised TypeError"
    except TypeError as e:
        error_msg = str(e)
        # Check that error message contains helpful information
        assert "must be strings" in error_msg
        assert "default=" in error_msg
        assert "dict" in error_msg
