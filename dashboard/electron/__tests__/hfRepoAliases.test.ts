// @vitest-environment node

/**
 * hfRepoAliases — ModelScope→HuggingFace repo alias resolution.
 *
 * Guards the false "Missing" badge fix for iic/SenseVoiceSmall: the model is
 * configured under its ModelScope id but cached under the FunAudioLLM HF org,
 * so the cache-dir name must be derived from the resolved HF repo id.
 */

import { describe, it, expect } from 'vitest';
import { resolveHfRepoId, hfCacheDirName, MODELSCOPE_TO_HF_REPO } from '../hfRepoAliases.js';

describe('resolveHfRepoId', () => {
  it('remaps the ModelScope SenseVoice id to its HF repo', () => {
    expect(resolveHfRepoId('iic/SenseVoiceSmall')).toBe('FunAudioLLM/SenseVoiceSmall');
  });

  it('passes an unaliased id through unchanged', () => {
    expect(resolveHfRepoId('pyannote/speaker-diarization-community-1')).toBe(
      'pyannote/speaker-diarization-community-1',
    );
  });

  it('trims surrounding whitespace before lookup', () => {
    expect(resolveHfRepoId('  iic/SenseVoiceSmall  ')).toBe('FunAudioLLM/SenseVoiceSmall');
  });

  it('is case-sensitive: a differently-cased id does not alias', () => {
    // HF repo ids are case-sensitive, so this must pass through unchanged.
    expect(resolveHfRepoId('iic/sensevoicesmall')).toBe('iic/sensevoicesmall');
  });
});

describe('hfCacheDirName', () => {
  it('derives the HF cache dir from the resolved alias', () => {
    expect(hfCacheDirName('iic/SenseVoiceSmall')).toBe('models--FunAudioLLM--SenseVoiceSmall');
  });

  it('derives the cache dir from an unaliased whisper id', () => {
    expect(hfCacheDirName('Systran/faster-whisper-large-v3')).toBe(
      'models--Systran--faster-whisper-large-v3',
    );
  });

  it('derives the cache dir for a plain org/name id', () => {
    expect(hfCacheDirName('funasr/campplus')).toBe('models--funasr--campplus');
  });
});

describe('MODELSCOPE_TO_HF_REPO', () => {
  it('is frozen so the alias table cannot be mutated at runtime', () => {
    expect(Object.isFrozen(MODELSCOPE_TO_HF_REPO)).toBe(true);
  });
});
