// @vitest-environment node

/**
 * GH-318 - container log lines from the bootstrap dependency installs,
 * reported into the DownloadHub. The log parser is the fallback signal for
 * these installs: it knows only start / complete / fail, so the items it
 * creates are indeterminate.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { DownloadHub, type DownloadItem } from '../downloadHub.js';
import { applyBootstrapLogLine, BootstrapLogTracker } from '../bootstrapLogDownloads.js';
import type { StartupEvent } from '../startupEventWatcher.js';

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

describe('BootstrapLogTracker', () => {
  it('ignores a line it has already seen, so a replayed log stream adds nothing', () => {
    // The log stream restarts with --since <session start> (e.g. when the
    // Logs view subscribes after the container exited) and replays every
    // line. Lines carry timestamps, so a repeat is exactly that: a repeat.
    const tracker = new BootstrapLogTracker(hub);
    const lines = [
      '2026-10-03T10:00:00.000Z [bootstrap] Installing NeMo toolkit for NVIDIA Parakeet support...',
      '2026-10-03T10:04:00.000Z [bootstrap] NeMo toolkit installed',
    ];

    for (const line of lines) tracker.apply(line);
    for (const line of lines) tracker.apply(line);

    expect(hub.snapshot()).toHaveLength(1);
    expect(hub.snapshot()[0].status).toBe('complete');
  });

  it('still tracks a second real install with a new timestamp', () => {
    const tracker = new BootstrapLogTracker(hub);
    tracker.apply('2026-10-03T10:00:00.000Z [bootstrap] Installing NeMo toolkit');
    tracker.apply('2026-10-03T10:04:00.000Z [bootstrap] NeMo toolkit installed');
    tracker.apply('2026-10-03T12:00:00.000Z [bootstrap] Installing NeMo toolkit');

    expect(hub.snapshot().filter((i) => i.status === 'active')).toHaveLength(1);
  });

  it('raises a failed model preload as a server warning, not as a download', () => {
    // The only signal of a failed preload on a server whose startup events
    // do not reach the dashboard (older images on Linux).
    const events: StartupEvent[] = [];
    const tracker = new BootstrapLogTracker(hub, (event) => events.push(event));
    const line =
      '2026-10-03T10:05:00.000Z ERROR Model preload failed for model=large-v3 — continuing startup without a model';

    tracker.apply(line);
    tracker.apply(line);

    expect(hub.snapshot()).toHaveLength(0);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      id: 'model-preload-error',
      category: 'warning',
      status: 'error',
      severity: 'error',
    });
    expect(events[0].label).toMatch(/model preload failed/i);
  });

  it('survives a listener that throws', () => {
    const tracker = new BootstrapLogTracker(hub, () => {
      throw new Error('window gone');
    });

    expect(() => tracker.apply('ERROR Model preload failed for model=x')).not.toThrow();
  });
});
