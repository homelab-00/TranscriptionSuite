/**
 * a11yLabels tests (Issue #104, Story 1.8 AC3).
 */

import { describe, expect, it } from 'vitest';

import { downloadButtonLabel, folderPickerButtonLabel, retryButtonLabel } from '../a11yLabels';

describe('downloadButtonLabel', () => {
  it.each([
    ['transcript', 'Download transcript as plain text'],
    ['summary', 'Download summary as plain text'],
    ['audio', 'Download recording audio file'],
  ] as const)('%s → %s', (kind, expected) => {
    expect(downloadButtonLabel(kind)).toBe(expected);
  });

  it('never returns the bare word "Download"', () => {
    for (const kind of ['transcript', 'summary', 'audio'] as const) {
      const label = downloadButtonLabel(kind);
      expect(label.toLowerCase()).not.toBe('download');
      expect(label.length).toBeGreaterThan('Download'.length);
    }
  });
});

describe('retryButtonLabel', () => {
  it.each([
    ['summary', 'Retry AI summary'],
    ['export', 'Retry transcript export'],
    ['webhook', 'Retry webhook delivery'],
  ] as const)('%s → %s', (kind, expected) => {
    expect(retryButtonLabel(kind)).toBe(expected);
  });
});

describe('folderPickerButtonLabel', () => {
  it('formats the target into "Choose <target> folder"', () => {
    expect(folderPickerButtonLabel('destination')).toBe('Choose destination folder');
    expect(folderPickerButtonLabel('output')).toBe('Choose output folder');
  });
});
