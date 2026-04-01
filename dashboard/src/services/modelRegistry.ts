/**
 * Static model metadata registry for the Model Manager tab.
 *
 * Each entry represents a known HuggingFace model that can be used with
 * TranscriptionSuite.  The registry drives the Model Manager UI — family
 * grouping, capability badges, and HuggingFace links.
 */

import {
  isNemoModel,
  isVibeVoiceASRModel,
  isCanaryModel,
  isParakeetModel,
  isMLXModel,
  isMLXParakeetModel,
} from './modelCapabilities';

export type ModelFamily = 'whisper' | 'nemo' | 'vibevoice' | 'mlx' | 'diarization' | 'custom' | 'none';
export type ModelRole = 'main' | 'live' | 'diarization';

export interface ModelInfo {
  /** HuggingFace repo ID (e.g. "Systran/faster-whisper-large-v3") */
  id: string;
  displayName: string;
  family: ModelFamily;
  description: string;
  parameterCount?: string;
  huggingfaceUrl: string;
  capabilities: {
    translation: boolean;
    liveMode: boolean;
    diarization: boolean;
    languageCount: number;
  };
  /** Config slots this model can fill */
  roles: ModelRole[];
}

export const MODEL_REGISTRY: ModelInfo[] = [
  // ── NeMo ─────────────────────────────────────────────────────────────────
  {
    id: 'nvidia/parakeet-tdt-0.6b-v3',
    displayName: 'Parakeet TDT 0.6B',
    family: 'nemo',
    description: 'NVIDIA NeMo ASR-only model. Fast inference, 25 EU languages.',
    parameterCount: '600M',
    huggingfaceUrl: 'https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 25 },
    roles: ['main'],
  },
  {
    id: 'nvidia/canary-1b-v2',
    displayName: 'Canary 1B V2',
    family: 'nemo',
    description: 'NVIDIA NeMo multitask model with ASR + translation across 25 EU languages.',
    parameterCount: '1B',
    huggingfaceUrl: 'https://huggingface.co/nvidia/canary-1b-v2',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 25 },
    roles: ['main'],
  },

  // ── Faster Whisper ──────────────────────────────────────────────────────────────
  {
    id: 'Systran/faster-whisper-large-v3',
    displayName: 'Faster Whisper Large v3',
    family: 'whisper',
    description: 'State-of-the-art multilingual ASR. Best accuracy, higher VRAM usage.',
    parameterCount: '1.5B',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-large-v3',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-distil-whisper-large-v3',
    displayName: 'Faster Distil Whisper Large v3',
    family: 'whisper',
    description: 'Distilled large-v3. ~6x faster with minimal accuracy loss.',
    parameterCount: '756M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-distil-whisper-large-v3',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'deepdml/faster-whisper-large-v3-turbo-ct2',
    displayName: 'Faster Whisper Large v3 Turbo',
    family: 'whisper',
    description: 'Turbo variant of large-v3. Fastest large model, no translation support.',
    parameterCount: '809M',
    huggingfaceUrl: 'https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-medium',
    displayName: 'Faster Whisper Medium',
    family: 'whisper',
    description: 'Good balance of accuracy and speed. Lower VRAM than Large v3.',
    parameterCount: '769M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-medium',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-medium.en',
    displayName: 'Faster Whisper Medium (English)',
    family: 'whisper',
    description: 'English-only medium model. Better English accuracy than multilingual variant.',
    parameterCount: '769M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-medium.en',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 1 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-distil-whisper-medium.en',
    displayName: 'Faster Distil Whisper Medium (English)',
    family: 'whisper',
    description: 'Distilled English-only medium. Fast with good English accuracy.',
    parameterCount: '394M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-distil-whisper-medium.en',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 1 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-small',
    displayName: 'Faster Whisper Small',
    family: 'whisper',
    description: 'Lightweight model suitable for real-time use on modest hardware.',
    parameterCount: '244M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-small',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-small.en',
    displayName: 'Faster Whisper Small (English)',
    family: 'whisper',
    description: 'English-only small model. Lightweight, best for English-only real-time use.',
    parameterCount: '244M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-small.en',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 1 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-distil-whisper-small.en',
    displayName: 'Faster Distil Whisper Small (English)',
    family: 'whisper',
    description: 'Distilled English-only small. Smallest and fastest model available.',
    parameterCount: '166M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-distil-whisper-small.en',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 1 },
    roles: ['main', 'live'],
  },

  // ── VibeVoice ────────────────────────────────────────────────────────────
  {
    id: 'microsoft/VibeVoice-ASR',
    displayName: 'VibeVoice ASR',
    family: 'vibevoice',
    description:
      'Microsoft ASR + diarization model. Handles speaker attribution natively. Very large (~16 GB).',
    parameterCount: '9B',
    huggingfaceUrl: 'https://huggingface.co/microsoft/VibeVoice-ASR',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 51 },
    roles: ['main'],
  },
  {
    id: 'scerz/VibeVoice-ASR-4bit',
    displayName: 'VibeVoice ASR 4-bit',
    family: 'vibevoice',
    description: 'Quantized VibeVoice variant. Lower VRAM requirement (~7 GB).',
    parameterCount: '9B',
    huggingfaceUrl: 'https://huggingface.co/scerz/VibeVoice-ASR-4bit',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 51 },
    roles: ['main'],
  },

  // ── MLX VibeVoice (Apple Silicon / Metal) ────────────────────────────────
  {
    id: 'mlx-community/VibeVoice-ASR-4bit',
    displayName: 'MLX VibeVoice ASR (4-bit)',
    family: 'mlx',
    description:
      'Microsoft VibeVoice-ASR on MLX, 4-bit quantised. Native diarization + timestamps on Apple Silicon. Smallest VibeVoice variant (~5.7 GB).',
    parameterCount: '9B',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/VibeVoice-ASR-4bit',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 51 },
    roles: ['main'],
  },
  {
    id: 'mlx-community/VibeVoice-ASR-8bit',
    displayName: 'MLX VibeVoice ASR (8-bit)',
    family: 'mlx',
    description:
      'Microsoft VibeVoice-ASR on MLX, 8-bit quantised. Native diarization + timestamps on Apple Silicon (~9.5 GB).',
    parameterCount: '9B',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/VibeVoice-ASR-8bit',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 51 },
    roles: ['main'],
  },
  {
    id: 'mlx-community/VibeVoice-ASR-bf16',
    displayName: 'MLX VibeVoice ASR (bf16)',
    family: 'mlx',
    description:
      'Microsoft VibeVoice-ASR on MLX. Native diarization + timestamps on Apple Silicon. Very large (~18 GB).',
    parameterCount: '9B',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/VibeVoice-ASR-bf16',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 51 },
    roles: ['main'],
  },

  // ── MLX Parakeet (Apple Silicon / Metal) ───────────────────────────────
  // Note: mlx-community/parakeet-tdt-1.1b is intentionally omitted.
  // The 1.1b TDT model was trained to output lowercase text only (no native
  // punctuation or capitalisation) and there is no MLX PnC variant.  The
  // 0.6b-v3 is NVIDIA's September 2025 SOTA model trained on 660K hours
  // (10× more data), supports 25 languages with native P&C, and matches or
  // beats the 1.1b on all English benchmarks.
  {
    id: 'mlx-community/parakeet-tdt-0.6b-v3',
    displayName: 'MLX Parakeet TDT 0.6B v3',
    family: 'mlx',
    description:
      'NVIDIA Parakeet-TDT 0.6B v3 on MLX. SOTA accuracy on Apple Silicon — 660K hours of training, native punctuation & capitalisation, 25 European languages.',
    parameterCount: '600M',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 25 },
    roles: ['main'],
  },

  // ── MLX Canary (Apple Silicon / Metal) ─────────────────────────────────
  // Community MLX ports of NVIDIA Canary 1B v2 using the canary-mlx package.
  // No translation support in the MLX port (ASR only).
  {
    id: 'eelcor/canary-1b-v2-mlx',
    displayName: 'MLX Canary 1B v2',
    family: 'mlx',
    description:
      'NVIDIA Canary 1B v2 on MLX. ~8.5× real-time on Apple Silicon, native P&C, 25 European languages. Full precision (~3.7 GB).',
    parameterCount: '1B',
    huggingfaceUrl: 'https://huggingface.co/eelcor/canary-1b-v2-mlx',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 25 },
    roles: ['main'],
  },
  {
    id: 'Mediform/canary-1b-v2-mlx-q8',
    displayName: 'MLX Canary 1B v2 (Q8)',
    family: 'mlx',
    description:
      'NVIDIA Canary 1B v2 on MLX, Q8 quantised. Native P&C, 25 European languages. Smaller footprint (~1.1 GB).',
    parameterCount: '1B',
    huggingfaceUrl: 'https://huggingface.co/Mediform/canary-1b-v2-mlx-q8',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 25 },
    roles: ['main'],
  },

  // ── MLX Whisper (Apple Silicon / Metal via mlx-audio) ───────────────────
  {
    id: 'mlx-community/whisper-large-v3-turbo-asr-fp16',
    displayName: 'MLX Whisper Large v3 Turbo',
    family: 'mlx',
    description:
      'Fast turbo variant of Whisper large-v3 on Apple Silicon. Best speed/accuracy tradeoff.',
    parameterCount: '809M',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/whisper-large-v3-turbo-asr-fp16',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
  },
  {
    id: 'mlx-community/whisper-large-v3-asr-fp16',
    displayName: 'MLX Whisper Large v3',
    family: 'mlx',
    description:
      'Apple Silicon Metal-accelerated Whisper large-v3. Best accuracy on Mac bare-metal.',
    parameterCount: '1.5B',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/whisper-large-v3-asr-fp16',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
  },
  {
    id: 'mlx-community/whisper-small-asr-fp16',
    displayName: 'MLX Whisper Small',
    family: 'mlx',
    description: 'Lightweight Metal-accelerated model for fast Mac bare-metal transcription.',
    parameterCount: '244M',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/whisper-small-asr-fp16',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
  },
  {
    id: 'mlx-community/whisper-tiny-asr-fp16',
    displayName: 'MLX Whisper Tiny',
    family: 'mlx',
    description: 'Smallest Metal-accelerated model. Fastest but lowest accuracy.',
    parameterCount: '39M',
    huggingfaceUrl: 'https://huggingface.co/mlx-community/whisper-tiny-asr-fp16',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
  },

  // ── Diarization ──────────────────────────────────────────────────────────
  {
    id: 'pyannote/speaker-diarization-community-1',
    displayName: 'Speaker Diarization',
    family: 'diarization',
    description:
      'Community speaker-diarization pipeline by pyannote. Used for multi-speaker segmentation.',
    huggingfaceUrl: 'https://huggingface.co/pyannote/speaker-diarization-community-1',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 0 },
    roles: ['diarization'],
  },
];

/** Return registry models grouped by family. */
export function getModelsByFamily(family: ModelFamily): ModelInfo[] {
  return MODEL_REGISTRY.filter((m) => m.family === family);
}

/** Look up a single model by its HuggingFace ID (case-insensitive). */
export function getModelById(id: string): ModelInfo | undefined {
  const needle = id.trim().toLowerCase();
  return MODEL_REGISTRY.find((m) => m.id.toLowerCase() === needle);
}

/** Detect the display family for an arbitrary model ID. */
export function detectModelFamily(modelId: string): ModelFamily {
  if (isParakeetModel(modelId) || isCanaryModel(modelId)) return 'nemo';
  if (isNemoModel(modelId)) return 'nemo';
  // MLX check must come before VibeVoice — mlx-community/VibeVoice-ASR-bf16
  // matches both isMLXModel and isVibeVoiceASRModel.
  if (isMLXParakeetModel(modelId) || isMLXModel(modelId)) return 'mlx';
  if (isVibeVoiceASRModel(modelId)) return 'vibevoice';
  return 'whisper';
}
