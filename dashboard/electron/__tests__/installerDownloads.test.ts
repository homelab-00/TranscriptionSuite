// @vitest-environment node

/**
 * GH-318 - the app-update pipeline (electron-updater and the macOS DMG
 * variant updater) reported into the DownloadHub. The UpdateBanner keeps its
 * own actionable failure toast, so these items never raise a second one.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DownloadHub, type DownloadItem } from '../downloadHub.js';
import { createInstallerDownloadAdapter } from '../installerDownloads.js';

let clock = 0;
let hub: DownloadHub;

const only = (): DownloadItem => {
  const items = hub.snapshot();
  expect(items).toHaveLength(1);
  return items[0];
};

beforeEach(() => {
  clock = 9_000_000;
  hub = new DownloadHub({ now: () => clock });
});

describe('createInstallerDownloadAdapter', () => {
  it('shows a preparing item while the updater checks, without an error toast', () => {
    const apply = createInstallerDownloadAdapter(hub, { cancel: vi.fn() });
    apply({ state: 'checking' });

    expect(only()).toMatchObject({
      id: 'app-update',
      kind: 'app-update',
      status: 'active',
      detail: 'Preparing',
      cancellable: true,
      errorToast: false,
    });
  });

  it('drops the item when the check finds nothing to download', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({ state: 'checking' });
    apply({ state: 'idle' });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('reports bytes and the updater speed while downloading', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({ state: 'checking' });
    clock += 5000;
    apply({
      state: 'downloading',
      version: '1.4.0',
      percent: 25,
      bytesPerSecond: 500,
      transferred: 1000,
      total: 4000,
    });

    expect(only()).toMatchObject({
      label: 'App update v1.4.0',
      bytesDone: 1000,
      bytesTotal: 4000,
      bytesPerSecond: 500,
      etaSeconds: 6,
    });
  });

  it('stays indeterminate when the total size is unknown', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({
      state: 'downloading',
      version: '1.4.0',
      percent: 0,
      bytesPerSecond: 0,
      transferred: 0,
      total: 0,
    });

    const item = only();
    expect(item.bytesTotal).toBeUndefined();
    expect(item.percent).toBeUndefined();
    expect(item.cancellable).toBe(false);
  });

  it('keeps the item running through verification and completes on downloaded', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({
      state: 'downloading',
      version: '1.4.0',
      percent: 100,
      bytesPerSecond: 1,
      transferred: 10,
      total: 10,
    });
    apply({ state: 'verifying', version: '1.4.0' });
    expect(only()).toMatchObject({ status: 'active', detail: 'Verifying' });

    apply({ state: 'downloaded', version: '1.4.0' });
    expect(only().status).toBe('complete');
  });

  it('completes when the DMG path returns to idle after downloading', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({
      state: 'downloading',
      version: '1.4.0',
      percent: 100,
      bytesPerSecond: 0,
      transferred: 10,
      total: 10,
    });
    apply({ state: 'verifying', version: '1.4.0' });
    apply({ state: 'idle' });

    expect(only().status).toBe('complete');
  });

  it('maps error and cancelled onto the running item', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({ state: 'checking' });
    apply({ state: 'error', message: 'Checksum verification failed' });
    expect(only()).toMatchObject({ status: 'error', error: 'Checksum verification failed' });

    clock += 60_000;
    apply({ state: 'checking' });
    apply({ state: 'cancelled' });
    expect(only().status).toBe('cancelled');
  });

  it('drops the item when the platform needs a manual download', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({ state: 'checking' });
    apply({
      state: 'manual-download-required',
      version: '1.4.0',
      downloadUrl: 'https://example.invalid',
      reason: 'read-only',
    });

    expect(hub.snapshot()).toHaveLength(0);
  });

  it('ignores an error with no update download in flight', () => {
    const apply = createInstallerDownloadAdapter(hub, {});
    apply({ state: 'error', message: 'Invalid update version' });

    expect(hub.snapshot()).toHaveLength(0);
  });
});
