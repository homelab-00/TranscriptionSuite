/**
 * Client-side formatters for transcription results.
 *
 * These work with the API response format (TranscriptionResponse) — not
 * the database format used by server-side subtitle_export.py.
 */

import type { TranscriptionResponse } from '../api/types';

/**
 * Format milliseconds as SRT timestamp: HH:MM:SS,mmm
 */
function formatSrtTime(seconds: number): string {
  const totalMs = Math.round(seconds * 1000);
  const ms = totalMs % 1000;
  const totalSec = Math.floor(totalMs / 1000);
  const s = totalSec % 60;
  const totalMin = Math.floor(totalSec / 60);
  const m = totalMin % 60;
  const h = Math.floor(totalMin / 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

/**
 * Render transcription as SRT subtitle format.
 *
 * Each segment becomes a numbered cue with optional [Speaker N] prefix.
 * Speaker labels are normalized by first appearance order.
 */
export function renderSrt(response: TranscriptionResponse): string {
  if (!response.segments || response.segments.length === 0) {
    return '';
  }

  // Build speaker label normalization map (first appearance → Speaker 1, 2, ...)
  const speakerMap = new Map<string, string>();
  let speakerCounter = 0;

  for (const seg of response.segments) {
    if (seg.speaker && !speakerMap.has(seg.speaker)) {
      speakerCounter++;
      speakerMap.set(seg.speaker, `Speaker ${speakerCounter}`);
    }
  }

  const hasSpeakers = speakerMap.size > 0;
  const lines: string[] = [];

  response.segments.forEach((seg, index) => {
    const cueNumber = index + 1;
    const startTime = formatSrtTime(seg.start);
    const endTime = formatSrtTime(seg.end);
    const text = seg.text.trim();
    if (!text) return;

    const speakerPrefix = hasSpeakers && seg.speaker ? `[${speakerMap.get(seg.speaker)}] ` : '';

    lines.push(`${cueNumber}`);
    lines.push(`${startTime} --> ${endTime}`);
    lines.push(`${speakerPrefix}${text}`);
    lines.push('');
  });

  return lines.join('\n');
}

/**
 * Render transcription as plain text.
 */
export function renderTxt(response: TranscriptionResponse): string {
  return response.text;
}
