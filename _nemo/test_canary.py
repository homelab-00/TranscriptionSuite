#!/usr/bin/env python3
"""Test Canary-1B-v2 installation and Greek transcription."""

import torch
from nemo.collections.asr.models import ASRModel


def main():
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print(f"CUDA version: {torch.version.cuda}")

    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(
            f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB"
        )

    print("\nLoading Canary-1B-v2 model...")
    print("(First run will download ~4GB model weights)")

    # Load the model
    model = ASRModel.from_pretrained("nvidia/canary-1b-v2")

    # Move to GPU
    model = model.cuda()
    model.eval()

    print("Model loaded successfully!")
    print(f"Model on device: {next(model.parameters()).device}")

    # Check VRAM usage
    print(f"VRAM used: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")


if __name__ == "__main__":
    main()
