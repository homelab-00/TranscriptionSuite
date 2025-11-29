#!/usr/bin/env python3
"""
Test script to verify the diarization module installation.
"""

import os
import sys


def test_imports():
    """Test if all required packages can be imported."""
    print("Testing imports...")

    packages = [
        ("torch", "PyTorch"),
        ("torchaudio", "TorchAudio"),
        ("numpy", "NumPy"),
        ("scipy", "SciPy"),
        ("soundfile", "SoundFile"),
        ("yaml", "PyYAML"),
        ("rich", "Rich"),
    ]

    all_good = True
    for package, name in packages:
        try:
            __import__(package)
            print(f"  ✓ {name}")
        except ImportError as e:
            print(f"  ✗ {name}: {e}")
            all_good = False

    return all_good


def test_pyannote():
    """Test if PyAnnote can be imported."""
    print("\nTesting PyAnnote...")
    try:
        from pyannote.audio import Pipeline

        # Prevent "imported but unused" warning
        _ = Pipeline

        print("  ✓ PyAnnote audio pipeline")
        return True
    except ImportError as e:
        print(f"  ✗ PyAnnote: {e}")
        return False


def test_cuda():
    """Test CUDA availability."""
    print("\nTesting CUDA...")
    try:
        import torch

        if torch.cuda.is_available():
            print("  ✓ CUDA is available")
            print(f"    Device count: {torch.cuda.device_count()}")
            print(f"    Current device: {torch.cuda.get_device_name(0)}")
        else:
            print("  ℹ CUDA not available, will use CPU")
    except Exception as e:
        print(f"  ⚠ Could not check CUDA: {e}")


def test_config():
    """Test configuration file."""
    print("\nTesting configuration...")

    # Add parent to path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    try:
        from config_manager import ConfigManager

        config = ConfigManager()

        print("  ✓ Configuration loaded")

        # Check HF token
        hf_token = config.get("pyannote", "hf_token")
        if hf_token:
            print(f"  ✓ HuggingFace token configured (length: {len(hf_token)})")
        else:
            print("  ⚠ HuggingFace token not set!")
            print("    Please add your token to DIARIZATION/config.yaml")

    except Exception as e:
        print(f"  ✗ Configuration error: {e}")


def test_module_imports():
    """Test if our module components can be imported."""
    print("\nTesting module components...")

    components = [
        "diarization_manager",
        "transcription_combiner",
        "utils",
        "config_manager",
        "logging_setup",
        "diarize_audio",
        "api",
    ]

    all_good = True
    for component in components:
        try:
            __import__(component)
            print(f"  ✓ {component}")
        except ImportError as e:
            print(f"  ✗ {component}: {e}")
            all_good = False

    return all_good


def main():
    """Run all tests."""
    print("=" * 50)
    print("Diarization Module Installation Test")
    print("=" * 50)

    # Test imports
    imports_ok = test_imports()

    # Test PyAnnote
    pyannote_ok = test_pyannote()

    # Test CUDA
    test_cuda()

    # Test config
    test_config()

    # Test module
    module_ok = test_module_imports()

    print("\n" + "=" * 50)
    if imports_ok and pyannote_ok and module_ok:
        print("✅ All tests passed! Module is ready to use.")
        print("\nNext steps:")
        print("1. Add your HuggingFace token to DIARIZATION/config.yaml")
        print("2. Test with: python DIARIZATION/diarize_audio.py <audio_file>")
    else:
        print("❌ Some tests failed. Please check the errors above.")
        print("\nTry running: uv sync")
    print("=" * 50)


if __name__ == "__main__":
    main()
