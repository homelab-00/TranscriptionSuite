/**
 * Client-side formatters for transcription results.
 *
 * These work with the API response format (TranscriptionResponse) — not
 * the database format used by server-side subtitle_export.py.
 */

import type { TranscriptionResponse } from '../api/types';

/**
 * Build a speaker normalization map (raw label → "Speaker N") by first appearance order.
 */
function buildSpeakerMap(response: TranscriptionResponse): Map<string, string> {
  const map = new Map<string, string>();
  let counter = 0;
  for (const seg of response.segments) {
    if (seg.speaker && !map.has(seg.speaker)) {
      map.set(seg.speaker, `Speaker ${++counter}`);
    }
  }
  return map;
}

/**
 * Format seconds as SRT timestamp: HH:MM:SS,mmm
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
 * Format seconds as ASS timestamp: H:MM:SS.cc (centiseconds)
 * Matches _format_ass_timestamp() in server/backend/core/subtitle_export.py.
 */
function formatAssTime(seconds: number): string {
  const totalCs = Math.max(0, Math.round(seconds * 100));
  const cs = totalCs % 100;
  const totalSec = Math.floor(totalCs / 100);
  const s = totalSec % 60;
  const totalMin = Math.floor(totalSec / 60);
  const m = totalMin % 60;
  const h = Math.floor(totalMin / 60);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

/**
 * Escape text for ASS: backslashes, curly braces, and literal newlines.
 * Matches _escape_ass_text() in server/backend/core/subtitle_export.py.
 */
function escapeAssText(text: string): string {
  return text
    .replace(/\\/g, '\\\\')
    .replace(/\{/g, '\\{')
    .replace(/\}/g, '\\}')
    .replace(/\n/g, '\\N');
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

  const speakerMap = buildSpeakerMap(response);
  const hasSpeakers = speakerMap.size > 0;
  const lines: string[] = [];

  response.segments.forEach((seg, index) => {
    const text = seg.text.trim();
    if (!text) return;

    const speakerPrefix = hasSpeakers && seg.speaker ? `[${speakerMap.get(seg.speaker)}] ` : '';

    lines.push(`${index + 1}`);
    lines.push(`${formatSrtTime(seg.start)} --> ${formatSrtTime(seg.end)}`);
    lines.push(`${speakerPrefix}${text}`);
    lines.push('');
  });

  return lines.join('\n');
}

/**
 * Render transcription as ASS subtitle format.
 *
 * Header and style match render_ass() in server/backend/core/subtitle_export.py.
 * Speaker labels use the same [Speaker N] normalization as renderSrt.
 */
export function renderAss(response: TranscriptionResponse, title = 'Export'): string {
  const safeTitle = title.replace(/\n/g, ' ').trim() || 'Export';

  const lines = [
    '[Script Info]',
    `Title: ${safeTitle}`,
    'ScriptType: v4.00+',
    'WrapStyle: 0',
    'ScaledBorderAndShadow: yes',
    '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
    'Style: Default,Arial,42,&H00FFFFFF,&H0000FFFF,&H001A1A1A,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,24,1',
    '',
    '[Events]',
    'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
  ];

  if (response.segments && response.segments.length > 0) {
    const speakerMap = buildSpeakerMap(response);
    const hasSpeakers = speakerMap.size > 0;

    for (const seg of response.segments) {
      const text = seg.text.trim();
      if (!text) continue;
      const speakerPrefix = hasSpeakers && seg.speaker ? `[${speakerMap.get(seg.speaker)}] ` : '';
      const escaped = escapeAssText(`${speakerPrefix}${text}`);
      lines.push(
        `Dialogue: 0,${formatAssTime(seg.start)},${formatAssTime(seg.end)},Default,,0,0,0,,${escaped}`,
      );
    }
  }

  return lines.join('\n');
}

/**
 * Render transcription as plain text.
 */
export function renderTxt(response: TranscriptionResponse): string {
  return response.text;
}

/**
 * Determine the output filename and rendered content for a transcription result.
 *
 * Centralizes the hideTimestamps / diarization / format branching that was
 * previously duplicated in importQueueStore and useSessionImportQueue.
 */
export function resolveTranscriptionOutput(
  filename: string,
  transcription: TranscriptionResponse,
  options: {
    hideTimestamps: boolean;
    diarizedFormat: 'srt' | 'ass';
  },
): { outputFilename: string; content: string } {
  const stem = filename.replace(/\.[^.]+$/, '');

  if (options.hideTimestamps) {
    return { outputFilename: `${stem}.txt`, content: renderTxt(transcription) };
  }

  const hasSegments =
    transcription.segments && transcription.segments.some((s) => s.text.trim().length > 0);

  if (hasSegments) {
    const outputFilename = `${stem}.${options.diarizedFormat}`;
    const content =
      options.diarizedFormat === 'ass' ? renderAss(transcription, stem) : renderSrt(transcription);
    return { outputFilename, content };
  }

  return { outputFilename: `${stem}.txt`, content: renderTxt(transcription) };
}
