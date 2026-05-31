// @vitest-environment node

/**
 * GH-125 — CPU profile must never request a NeMo model.
 *
 * `applyCpuModelDefaults` is the authoritative funnel guard in startContainer:
 * every start path flows through it, so it also covers the first-run auto-detect
 * path where the UI-side reset in ServerView may not have fired yet. These tests
 * lock in that a NeMo main model on the CPU profile is substituted with a
 * faster-whisper model + INSTALL_NEMO=false / INSTALL_WHISPER=true, and that all
 * other combinations pass through unchanged.
 */

import { describe, it, expect, vi } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-cpu-model-test-'));

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (_name: string) => userDataRoot,
    setPath: vi.fn(),
  },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

vi.mock('../containerRuntime.js', () => ({
  getRuntimeBin: vi.fn(async () => '/usr/bin/docker'),
  getContainerRuntime: vi.fn(async () => ({ kind: 'docker', displayName: 'Docker' })),
  getDetectionResult: vi.fn(() => null),
  resetDetection: vi.fn(),
  resolveRootlessSocket: vi.fn(() => null),
  getSocketPaths: vi.fn(() => ({ docker: '/var/run/docker.sock', podman: null })),
}));

import { isNemoModelName, applyCpuModelDefaults } from '../dockerManager.js';

describe('isNemoModelName', () => {
  it('detects NeMo families (case-insensitive)', () => {
    expect(isNemoModelName('nvidia/parakeet-tdt-0.6b-v3')).toBe(true);
    expect(isNemoModelName('nvidia/canary-1b-v2')).toBe(true);
    expect(isNemoModelName('NVIDIA/Parakeet-TDT-1.1b')).toBe(true);
    expect(isNemoModelName('  nvidia/nemotron-speech-4b  ')).toBe(true);
  });

  it('returns false for non-NeMo and empty inputs', () => {
    expect(isNemoModelName('Systran/faster-whisper-medium')).toBe(false);
    expect(isNemoModelName('ggml-large-v3.bin')).toBe(false);
    expect(isNemoModelName('mlx-community/whisper-large-v3-asr-fp16')).toBe(false);
    expect(isNemoModelName('')).toBe(false);
    expect(isNemoModelName(undefined)).toBe(false);
    expect(isNemoModelName(null)).toBe(false);
  });
});

describe('applyCpuModelDefaults', () => {
  it('substitutes a NeMo main model with faster-whisper on the CPU profile', () => {
    const result = applyCpuModelDefaults('cpu', {
      mainTranscriberModel: 'nvidia/parakeet-tdt-0.6b-v3',
      installNemo: true,
      installWhisper: false,
    });
    expect(result.mainTranscriberModel).toBe('Systran/faster-whisper-medium');
    expect(result.installNemo).toBe(false);
    expect(result.installWhisper).toBe(true);
  });

  it('leaves a whisper main model unchanged on the CPU profile', () => {
    const opts = {
      mainTranscriberModel: 'Systran/faster-whisper-large-v3',
      installNemo: false,
      installWhisper: true,
    };
    expect(applyCpuModelDefaults('cpu', opts)).toEqual(opts);
  });

  it('does not touch NeMo models on non-CPU profiles', () => {
    const opts = {
      mainTranscriberModel: 'nvidia/parakeet-tdt-0.6b-v3',
      installNemo: true,
      installWhisper: false,
    };
    expect(applyCpuModelDefaults('gpu', opts)).toEqual(opts);
    expect(applyCpuModelDefaults('metal', opts)).toEqual(opts);
  });

  it('is a no-op when no main model is set on the CPU profile', () => {
    const opts = { installNemo: undefined, installWhisper: undefined };
    expect(applyCpuModelDefaults('cpu', opts)).toEqual(opts);
  });
});
