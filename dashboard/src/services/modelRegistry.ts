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
  isWhisperCppModel,
} from './modelCapabilities';

export type ModelFamily =
  | 'whisper'
  | 'nemo'
  | 'vibevoice'
  | 'whispercpp'
  | 'diarization'
  | 'custom'
  | 'none';
export type ModelRole = 'main' | 'live' | 'diarization';

export interface ModelInfo {
  /** HuggingFace repo ID (e.g. "Systran/faster-whisper-large-v3") or GGML filename (e.g. "ggml-large-v3-turbo-q8_0.bin") */
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
  /** Runtime required to use this model. Used to dim incompatible models in the UI. */
  requiresRuntime?: 'cuda' | 'vulkan';
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
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
    requiresRuntime: 'cuda',
  },

  // ── whisper.cpp (GGML / Vulkan) ──────────────────────────────────────────
  // Flat .bin files served by the whisper.cpp sidecar container.
  // Downloaded via direct HTTP from huggingface.co/ggerganov/whisper.cpp.
  // No live mode, no diarization, no translation for turbo variants.
  {
    id: 'ggml-large-v3.bin',
    displayName: 'GGML Large v3',
    family: 'whispercpp',
    description: 'Full-precision large-v3 GGML model. Best accuracy (~3.1 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-large-v3-q5_0.bin',
    displayName: 'GGML Large v3 (Q5)',
    family: 'whispercpp',
    description: 'Q5_0 quantized large-v3. Good accuracy, lower VRAM (~2.1 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-large-v3-turbo.bin',
    displayName: 'GGML Large v3 Turbo',
    family: 'whispercpp',
    description: 'Full-precision turbo variant. Fast inference, no translation (~1.6 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-large-v3-turbo-q5_0.bin',
    displayName: 'GGML Large v3 Turbo (Q5)',
    family: 'whispercpp',
    description: 'Q5_0 quantized turbo. Very fast, no translation (~1.1 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-large-v3-turbo-q8_0.bin',
    displayName: 'GGML Large v3 Turbo (Q8)',
    family: 'whispercpp',
    description:
      'Q8_0 quantized turbo. Recommended for Vulkan — best speed/quality balance (~1.4 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-medium.bin',
    displayName: 'GGML Medium',
    family: 'whispercpp',
    description: 'Full-precision medium GGML model. Good balance of accuracy and speed (~1.5 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-medium-q5_0.bin',
    displayName: 'GGML Medium (Q5)',
    family: 'whispercpp',
    description: 'Q5_0 quantized medium. Lightweight multilingual option (~1.0 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-medium.en.bin',
    displayName: 'GGML Medium (English)',
    family: 'whispercpp',
    description: 'English-only medium GGML model (~1.5 GB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 1 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-small.bin',
    displayName: 'GGML Small',
    family: 'whispercpp',
    description: 'Full-precision small GGML model. Fast and lightweight (~465 MB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-small-q5_1.bin',
    displayName: 'GGML Small (Q5)',
    family: 'whispercpp',
    description: 'Q5_1 quantized small. Smallest multilingual option (~370 MB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: true, liveMode: false, diarization: false, languageCount: 99 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
  },
  {
    id: 'ggml-small.en.bin',
    displayName: 'GGML Small (English)',
    family: 'whispercpp',
    description: 'English-only small GGML model. Smallest English option (~465 MB).',
    huggingfaceUrl: 'https://huggingface.co/ggerganov/whisper.cpp',
    capabilities: { translation: false, liveMode: false, diarization: false, languageCount: 1 },
    roles: ['main'],
    requiresRuntime: 'vulkan',
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
    requiresRuntime: 'cuda',
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
  if (isVibeVoiceASRModel(modelId)) return 'vibevoice';
  if (isWhisperCppModel(modelId)) return 'whispercpp';
  return 'whisper';
}
