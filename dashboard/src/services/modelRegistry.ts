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
} from './modelCapabilities';

export type ModelFamily = 'whisper' | 'nemo' | 'vibevoice' | 'diarization' | 'custom';
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
  // ── Whisper ──────────────────────────────────────────────────────────────
  {
    id: 'Systran/faster-whisper-large-v3',
    displayName: 'Whisper Large V3',
    family: 'whisper',
    description: 'State-of-the-art multilingual ASR. Best accuracy, higher VRAM usage.',
    parameterCount: '1.5B',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-large-v3',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-medium',
    displayName: 'Whisper Medium',
    family: 'whisper',
    description: 'Good balance of accuracy and speed. Lower VRAM than Large V3.',
    parameterCount: '769M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-medium',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-small',
    displayName: 'Whisper Small',
    family: 'whisper',
    description: 'Lightweight model suitable for real-time use on modest hardware.',
    parameterCount: '244M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-small',
    capabilities: { translation: true, liveMode: true, diarization: false, languageCount: 99 },
    roles: ['main', 'live'],
  },

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

  // ── VibeVoice ────────────────────────────────────────────────────────────
  {
    id: 'microsoft/VibeVoice-ASR',
    displayName: 'VibeVoice ASR',
    family: 'vibevoice',
    description: 'Microsoft ASR + diarization model. Handles speaker attribution natively.',
    huggingfaceUrl: 'https://huggingface.co/microsoft/VibeVoice-ASR',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 1 },
    roles: ['main'],
  },
  {
    id: 'scerz/VibeVoice-ASR-4bit',
    displayName: 'VibeVoice ASR 4-bit',
    family: 'vibevoice',
    description: 'Quantized VibeVoice variant. Lower VRAM requirement (~4 GB).',
    huggingfaceUrl: 'https://huggingface.co/scerz/VibeVoice-ASR-4bit',
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 1 },
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
  if (isVibeVoiceASRModel(modelId)) return 'vibevoice';
  return 'whisper';
}
