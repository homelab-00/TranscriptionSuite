// @vitest-environment node

/**
 * GH-318 - mapping of server startup-events.jsonl lines into DownloadHub
 * items. The rule under test: an item exists only when the server shows
 * evidence of an actual download, so a cached model load never raises the
 * download bar. Covers both the current protocol (numeric bytes + phase) and
 * the legacy one (percent + pre-formatted size strings) so the dashboard
 * keeps working against an older server image.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { DownloadHub, type DownloadItem } from '../downloadHub.js';
import { applyServerDownloadEvent } from '../serverDownloadEvents.js';

let clock = 0;
let hub: DownloadHub;

const only = (): DownloadItem => {
  const items = hub.snapshot();
  expect(items).toHaveLength(1);
  return items[0];
};

beforeEach(() => {
  clock = 5_000_000;
  hub = new DownloadHub({ now: () => clock });
});

describe('applyServerDownloadEvent', () => {
  it('ignores non-download categories', () => {
    applyServerDownloadEvent(hub, {
      id: 'lifespan-start',
      category: 'server',
      label: 'Starting',
      status: 'active',
    });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('does not create an item for a load with no download evidence', () => {
    applyServerDownloadEvent(hub, {
      id: 'model-load-nvidia--parakeet',
      category: 'download',
      label: 'Loading parakeet...',
      status: 'active',
    });
    applyServerDownloadEvent(hub, {
      id: 'model-load-nvidia--parakeet',
      category: 'download',
      label: 'parakeet loaded from cache',
      status: 'complete',
    });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('never treats the model preload error as a download', () => {
    applyServerDownloadEvent(hub, {
      id: 'model-preload-error',
      category: 'download',
      label: 'Model preload failed',
      status: 'error',
    });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('creates a server item with bytes from the current protocol', () => {
    applyServerDownloadEvent(hub, {
      id: 'model-load-nvidia--parakeet',
      category: 'download',
      label: 'Downloading parakeet...',
      name: 'parakeet',
      kind: 'model',
      phase: 'download',
      status: 'active',
      downloadedBytes: 1024,
      totalBytes: 4096,
    });

    expect(only()).toMatchObject({
      id: 'model-load-nvidia--parakeet',
      kind: 'model',
      source: 'server',
      label: 'parakeet',
      status: 'active',
      bytesDone: 1024,
      bytesTotal: 4096,
    });
  });

  it('falls back to percent and size text for a legacy server', () => {
    applyServerDownloadEvent(hub, {
      id: 'model-load-nvidia--parakeet',
      category: 'download',
      label: 'Downloading parakeet...',
      status: 'active',
      progress: 42,
      downloadedSize: '1.1 GB',
      totalSize: '2.6 GB',
    });

    const item = only();
    expect(item).toMatchObject({
      kind: 'model',
      label: 'parakeet',
      percent: 42,
      detail: '1.1 GB / 2.6 GB',
    });
    expect(item.bytesTotal).toBeUndefined();
  });

  it('takes the kind from the event and infers it from the id otherwise', () => {
    applyServerDownloadEvent(hub, {
      id: 'alignment/el',
      category: 'download',
      label: 'Downloading...',
      name: 'Alignment model (el)',
      kind: 'alignment-model',
      phase: 'download',
      status: 'active',
    });
    applyServerDownloadEvent(hub, {
      id: 'bootstrap-deps',
      category: 'download',
      label: 'Installing dependencies',
      phase: 'download',
      status: 'active',
    });
    applyServerDownloadEvent(hub, {
      id: 'bootstrap-nemo',
      category: 'download',
      label: 'NeMo Toolkit',
      phase: 'download',
      status: 'active',
    });

    const kinds = Object.fromEntries(hub.snapshot().map((i) => [i.id, i.kind]));
    expect(kinds).toEqual({
      'alignment/el': 'alignment-model',
      'bootstrap-deps': 'server-deps',
      'bootstrap-nemo': 'feature-deps',
    });
  });

  it('completes the download when the server moves on to loading into memory', () => {
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Downloading m...',
      phase: 'download',
      status: 'active',
      downloadedBytes: 10,
      totalBytes: 10,
    });
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Loading m into memory...',
      phase: 'load',
      status: 'active',
    });

    expect(only().status).toBe('complete');
  });

  it('completes on the legacy 100 percent load marker', () => {
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Downloading m...',
      status: 'active',
      progress: 80,
    });
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Loading m into memory...',
      status: 'active',
      progress: 100,
    });

    expect(only().status).toBe('complete');
  });

  it('completes and fails a running item on terminal events', () => {
    applyServerDownloadEvent(hub, {
      id: 'ok',
      category: 'download',
      label: 'Downloading ok...',
      phase: 'download',
      status: 'active',
    });
    applyServerDownloadEvent(hub, {
      id: 'ok',
      category: 'download',
      label: 'ok ready',
      status: 'complete',
    });
    applyServerDownloadEvent(hub, {
      id: 'bad',
      category: 'download',
      label: 'Downloading bad...',
      phase: 'download',
      status: 'active',
    });
    applyServerDownloadEvent(hub, {
      id: 'bad',
      category: 'download',
      label: 'Failed to load bad',
      status: 'error',
    });

    const byId = Object.fromEntries(hub.snapshot().map((i) => [i.id, i]));
    expect(byId.ok.status).toBe('complete');
    expect(byId.bad).toMatchObject({ status: 'error', error: 'Failed to load bad' });
  });

  it('counts a load failure after the bytes arrived as a finished download', () => {
    // The download itself succeeded; what failed is loading the weights
    // (CUDA OOM, bad file). That is reported as a server warning, not as a
    // failed download.
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Downloading m...',
      phase: 'download',
      status: 'active',
      downloadedBytes: 10,
      totalBytes: 10,
    });
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Failed to load m',
      phase: 'load',
      status: 'error',
      error: 'RuntimeError: CUDA out of memory',
    });

    expect(only().status).toBe('complete');
  });

  it('fails the item with the server error text when the download itself broke', () => {
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Downloading m...',
      phase: 'download',
      status: 'active',
      downloadedBytes: 4,
      totalBytes: 10,
    });
    applyServerDownloadEvent(hub, {
      id: 'm',
      category: 'download',
      label: 'Failed to load m',
      phase: 'download',
      status: 'error',
      error: 'ConnectionError: connection reset',
    });

    expect(only()).toMatchObject({
      status: 'error',
      error: 'ConnectionError: connection reset',
    });
  });

  it('ignores terminal events for ids that never downloaded', () => {
    applyServerDownloadEvent(hub, {
      id: 'ghost',
      category: 'download',
      label: 'Failed to load ghost',
      status: 'error',
    });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('passes a wheel/package detail line through', () => {
    applyServerDownloadEvent(hub, {
      id: 'bootstrap-deps',
      category: 'download',
      label: 'Installing dependencies',
      name: 'Runtime dependencies',
      phase: 'download',
      status: 'active',
      downloadedBytes: 100,
      totalBytes: 400,
      detail: 'torch, nvidia-cudnn-cu12',
    });

    expect(only()).toMatchObject({
      label: 'Runtime dependencies',
      detail: 'torch, nvidia-cudnn-cu12',
    });
  });
});
