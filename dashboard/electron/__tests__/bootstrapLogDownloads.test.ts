// @vitest-environment node

/**
 * GH-318 - container log lines from the bootstrap dependency installs,
 * reported into the DownloadHub. The log parser is the fallback signal for
 * these installs: it knows only start / complete / fail, so the items it
 * creates are indeterminate.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { DownloadHub, type DownloadItem } from '../downloadHub.js';
import { applyBootstrapLogLine } from '../bootstrapLogDownloads.js';

let hub: DownloadHub;

const only = (): DownloadItem => {
  const items = hub.snapshot();
  expect(items).toHaveLength(1);
  return items[0];
};

beforeEach(() => {
  hub = new DownloadHub({ now: () => 1_000 });
});

describe('applyBootstrapLogLine', () => {
  it('starts an indeterminate server item when the runtime dependency install begins', () => {
    applyBootstrapLogLine(hub, '2026-10-03 [bootstrap] Installing Python runtime dependencies...');

    const item = only();
    expect(item).toMatchObject({
      id: 'bootstrap-deps',
      kind: 'server-deps',
      source: 'server',
      label: 'Runtime dependencies',
      status: 'active',
    });
    expect(item.percent).toBeUndefined();
    expect(item.bytesTotal).toBeUndefined();
  });

  it('completes the item on the matching installed line', () => {
    applyBootstrapLogLine(hub, '[bootstrap] Installing Python runtime dependencies');
    applyBootstrapLogLine(hub, '[bootstrap] Runtime dependencies installed (42.0s)');

    expect(only().status).toBe('complete');
  });

  it('tracks an optional feature install as feature-deps', () => {
    applyBootstrapLogLine(hub, '[bootstrap] Installing NeMo toolkit (this can take a while)');

    expect(only()).toMatchObject({
      id: 'bootstrap-nemo',
      kind: 'feature-deps',
      label: 'NeMo toolkit',
    });
  });

  it('fails the item with the error text that follows the marker', () => {
    applyBootstrapLogLine(hub, '[bootstrap] Installing VibeVoice-ASR');
    applyBootstrapLogLine(
      hub,
      '[bootstrap] VibeVoice-ASR installation failed: git clone exited with 128',
    );

    expect(only()).toMatchObject({ status: 'error', error: 'git clone exited with 128' });
  });

  it('does not invent an item from a completion line with no install in flight', () => {
    applyBootstrapLogLine(hub, '[bootstrap] Runtime dependencies installed');

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('ignores model load lines - loading from the cache is not a download', () => {
    applyBootstrapLogLine(hub, 'Loading transcription model from cache');
    applyBootstrapLogLine(hub, 'STT model loaded and ready');

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('ignores unrelated log lines', () => {
    applyBootstrapLogLine(hub, 'INFO:     Uvicorn running on http://0.0.0.0:9786');

    expect(hub.snapshot()).toHaveLength(0);
  });
});
