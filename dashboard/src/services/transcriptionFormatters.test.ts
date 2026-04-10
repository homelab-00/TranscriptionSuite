import { describe, expect, it } from 'vitest';

import type { TranscriptionResponse } from '../api/types';

import {
  renderSrt,
  renderAss,
  renderTxt,
  resolveTranscriptionOutput,
} from './transcriptionFormatters';

/* ------------------------------------------------------------------ */
/*  Fixtures                                                          */
/* ------------------------------------------------------------------ */

/** Minimal response with timed segments but no speakers. */
const timedResponse: TranscriptionResponse = {
  text: 'Hello world. Goodbye world.',
  segments: [
    { text: 'Hello world.', start: 0, end: 1.5 },
    { text: 'Goodbye world.', start: 2.0, end: 3.5 },
  ],
  words: [],
  language_probability: 0.99,
  duration: 3.5,
  num_speakers: 0,
};

/** Response with timed segments AND speaker labels. */
const diarizedResponse: TranscriptionResponse = {
  text: 'Hello world. Goodbye world.',
  segments: [
    { text: 'Hello world.', start: 0, end: 1.5, speaker: 'SPEAKER_00' },
    { text: 'Goodbye world.', start: 2.0, end: 3.5, speaker: 'SPEAKER_01' },
  ],
  words: [],
  language_probability: 0.99,
  duration: 3.5,
  num_speakers: 2,
};

/** Response with no segments (text only). */
const textOnlyResponse: TranscriptionResponse = {
  text: 'Hello world. Goodbye world.',
  segments: [],
  words: [],
  language_probability: 0.99,
  duration: 3.5,
  num_speakers: 0,
};

/* ------------------------------------------------------------------ */
/*  Renderer unit tests                                               */
/* ------------------------------------------------------------------ */

describe('renderTxt', () => {
  it('returns plain text', () => {
    expect(renderTxt(timedResponse)).toBe('Hello world. Goodbye world.');
  });
});

describe('renderSrt', () => {
  it('renders timed cues without speaker labels when no speakers', () => {
    const srt = renderSrt(timedResponse);
    expect(srt).toContain('00:00:00,000 --> 00:00:01,500');
    expect(srt).not.toContain('[Speaker');
  });

  it('renders timed cues with speaker labels when speakers present', () => {
    const srt = renderSrt(diarizedResponse);
    expect(srt).toContain('[Speaker 1]');
    expect(srt).toContain('[Speaker 2]');
  });

  it('returns empty string for empty segments', () => {
    expect(renderSrt(textOnlyResponse)).toBe('');
  });
});

describe('renderAss', () => {
  it('renders dialogue lines without speaker labels when no speakers', () => {
    const ass = renderAss(timedResponse, 'Test');
    expect(ass).toContain('Dialogue:');
    expect(ass).not.toContain('[Speaker');
  });

  it('renders dialogue lines with speaker labels when speakers present', () => {
    const ass = renderAss(diarizedResponse, 'Test');
    expect(ass).toContain('[Speaker 1]');
    expect(ass).toContain('[Speaker 2]');
  });
});

/* ------------------------------------------------------------------ */
/*  resolveTranscriptionOutput — I/O matrix                           */
/* ------------------------------------------------------------------ */

describe('resolveTranscriptionOutput', () => {
  const filename = 'recording.wav';

  it('diarization OFF, timestamps ON, segments present → timed SRT output', () => {
    const result = resolveTranscriptionOutput(filename, timedResponse, {
      hideTimestamps: false,
      diarizationPerformed: false,
      diarizedFormat: 'srt',
    });
    expect(result.outputFilename).toBe('recording.srt');
    expect(result.content).toContain('-->');
    expect(result.content).not.toContain('[Speaker');
  });

  it('diarization OFF, timestamps ON, segments present → timed ASS output', () => {
    const result = resolveTranscriptionOutput(filename, timedResponse, {
      hideTimestamps: false,
      diarizationPerformed: false,
      diarizedFormat: 'ass',
    });
    expect(result.outputFilename).toBe('recording.ass');
    expect(result.content).toContain('Dialogue:');
    expect(result.content).not.toContain('[Speaker');
  });

  it('diarization OFF, timestamps ON, segments empty → .txt fallback', () => {
    const result = resolveTranscriptionOutput(filename, textOnlyResponse, {
      hideTimestamps: false,
      diarizationPerformed: false,
      diarizedFormat: 'srt',
    });
    expect(result.outputFilename).toBe('recording.txt');
    expect(result.content).toBe('Hello world. Goodbye world.');
  });

  it('diarization OFF, timestamps OFF → .txt plain text', () => {
    const result = resolveTranscriptionOutput(filename, timedResponse, {
      hideTimestamps: true,
      diarizationPerformed: false,
      diarizedFormat: 'srt',
    });
    expect(result.outputFilename).toBe('recording.txt');
    expect(result.content).toBe('Hello world. Goodbye world.');
  });

  it('diarization ON, timestamps ON → timed SRT with speakers', () => {
    const result = resolveTranscriptionOutput(filename, diarizedResponse, {
      hideTimestamps: false,
      diarizationPerformed: true,
      diarizedFormat: 'srt',
    });
    expect(result.outputFilename).toBe('recording.srt');
    expect(result.content).toContain('-->');
    expect(result.content).toContain('[Speaker 1]');
  });

  it('diarization ON, timestamps ON → timed ASS with speakers', () => {
    const result = resolveTranscriptionOutput(filename, diarizedResponse, {
      hideTimestamps: false,
      diarizationPerformed: true,
      diarizedFormat: 'ass',
    });
    expect(result.outputFilename).toBe('recording.ass');
    expect(result.content).toContain('Dialogue:');
    expect(result.content).toContain('[Speaker 1]');
  });

  it('diarization ON, timestamps OFF → .txt plain text', () => {
    const result = resolveTranscriptionOutput(filename, diarizedResponse, {
      hideTimestamps: true,
      diarizationPerformed: true,
      diarizedFormat: 'ass',
    });
    expect(result.outputFilename).toBe('recording.txt');
    expect(result.content).toBe('Hello world. Goodbye world.');
  });
});
