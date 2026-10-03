// @vitest-environment node

/**
 * GH-318 - DownloadHub is the single main-process registry every download
 * source reports into. These tests lock in the lifecycle (begin / update /
 * terminal), the per-item broadcast throttle, speed + ETA derivation, the
 * snapshot retention window and the cancel plumbing.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DownloadHub, type DownloadChange, type DownloadItem } from '../downloadHub.js';

let clock = 0;
let changes: DownloadChange[] = [];
let hub: DownloadHub;

const upserts = (): DownloadItem[] => changes.flatMap((c) => (c.type === 'upsert' ? [c.item] : []));
const last = (): DownloadItem => upserts()[upserts().length - 1];

beforeEach(() => {
  clock = 1_000_000;
  changes = [];
  hub = new DownloadHub({ now: () => clock });
  hub.setBroadcaster((change) => changes.push(change));
});

describe('DownloadHub lifecycle', () => {
  it('broadcasts an active indeterminate item on begin', () => {
    hub.begin({ id: 'server-image:latest', kind: 'server-image', label: 'Server image (latest)' });

    expect(upserts()).toHaveLength(1);
    expect(last()).toMatchObject({
      id: 'server-image:latest',
      kind: 'server-image',
      source: 'app',
      label: 'Server image (latest)',
      status: 'active',
      cancellable: false,
      errorToast: true,
      startedAt: 1_000_000,
    });
    expect(last().bytesDone).toBeUndefined();
    expect(last().percent).toBeUndefined();
  });

  it('returns the running item when begin is called again with the same id', () => {
    hub.begin({ id: 'a', kind: 'model', label: 'A' });
    hub.begin({ id: 'a', kind: 'model', label: 'A' });

    expect(upserts()).toHaveLength(1);
    expect(hub.snapshot()).toHaveLength(1);
  });

  it('opens a new run with a new runId after the previous run ended', () => {
    const first = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    const firstRunId = last().runId;
    first.complete();
    clock += 10;
    hub.begin({ id: 'a', kind: 'model', label: 'A' });

    expect(last().status).toBe('active');
    expect(last().runId).not.toBe(firstRunId);
  });

  it('marks complete, error and cancelled with an end timestamp', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    clock += 5;
    a.complete('2.6 GB');
    expect(last()).toMatchObject({ status: 'complete', detail: '2.6 GB', endedAt: 1_000_005 });

    const b = hub.begin({ id: 'b', kind: 'model', label: 'B' });
    b.fail('network down');
    expect(last()).toMatchObject({ status: 'error', error: 'network down' });

    const c = hub.begin({ id: 'c', kind: 'model', label: 'C' });
    c.cancel('Cancelled by user');
    expect(last()).toMatchObject({ status: 'cancelled', detail: 'Cancelled by user' });
  });

  it('ignores updates and terminal calls from a handle whose run already ended', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    a.complete();
    const count = upserts().length;

    a.update({ bytesDone: 5, bytesTotal: 10 });
    a.fail('late');

    expect(upserts()).toHaveLength(count);
    expect(last().status).toBe('complete');
  });

  it('does not let a stale handle touch a newer run with the same id', () => {
    const stale = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    stale.complete();
    hub.begin({ id: 'a', kind: 'model', label: 'A' });

    stale.fail('late');

    expect(last().status).toBe('active');
  });

  it('removes a discarded item without a terminal state', () => {
    const a = hub.begin({ id: 'a', kind: 'app-update', label: 'Update' });
    const runId = last().runId;
    a.discard();

    expect(changes[changes.length - 1]).toEqual({ type: 'remove', runId });
    expect(hub.snapshot()).toHaveLength(0);
  });

  it('exposes a handle for a running id and nothing for an unknown one', () => {
    hub.begin({ id: 'a', kind: 'model', label: 'A' });

    expect(hub.active('a')).toBeDefined();
    expect(hub.active('missing')).toBeUndefined();

    hub.active('a')?.complete();
    expect(hub.active('a')).toBeUndefined();
  });

  it('survives a broadcaster that throws', () => {
    hub.setBroadcaster(() => {
      throw new Error('window destroyed');
    });

    expect(() => hub.begin({ id: 'a', kind: 'model', label: 'A' }).complete()).not.toThrow();
  });
});

describe('DownloadHub progress', () => {
  it('throttles progress broadcasts to one per 250ms per item', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    a.update({ bytesDone: 1, bytesTotal: 100 });
    clock += 100;
    a.update({ bytesDone: 2, bytesTotal: 100 });
    clock += 100;
    a.update({ bytesDone: 3, bytesTotal: 100 });
    expect(upserts()).toHaveLength(2); // begin + first update

    clock += 100; // 300ms since the first update
    a.update({ bytesDone: 4, bytesTotal: 100 });
    expect(upserts()).toHaveLength(3);
    expect(last().bytesDone).toBe(4);
  });

  it('carries the latest throttled progress into the terminal broadcast', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    a.update({ bytesDone: 1, bytesTotal: 100 });
    clock += 10;
    a.update({ bytesDone: 100, bytesTotal: 100 });
    a.complete();

    expect(last()).toMatchObject({ status: 'complete', bytesDone: 100, bytesTotal: 100 });
  });

  it('derives speed and ETA from byte samples once enough time has passed', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    a.update({ bytesDone: 0, bytesTotal: 10_000 });
    for (let i = 1; i <= 4; i += 1) {
      clock += 1000;
      a.update({ bytesDone: i * 1000, bytesTotal: 10_000 });
    }

    expect(last().bytesPerSecond).toBeCloseTo(1000, 0);
    expect(last().etaSeconds).toBeCloseTo(6, 0);
  });

  it('reports no ETA when the total is unknown', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    for (let i = 1; i <= 4; i += 1) {
      clock += 1000;
      a.update({ bytesDone: i * 1000 });
    }

    expect(last().bytesPerSecond).toBeGreaterThan(0);
    expect(last().etaSeconds).toBeUndefined();
  });

  it('prefers a speed supplied by the source', () => {
    const a = hub.begin({ id: 'a', kind: 'app-update', label: 'Update' });
    clock += 4000;
    a.update({ bytesDone: 500, bytesTotal: 1500, bytesPerSecond: 250 });

    expect(last().bytesPerSecond).toBe(250);
    expect(last().etaSeconds).toBe(4);
  });

  it('keeps a layer/package percent separate from bytes and clamps it', () => {
    const a = hub.begin({ id: 'a', kind: 'server-image', label: 'Image' });
    clock += 300;
    a.update({ percent: 140, detail: 'Extracting' });

    expect(last()).toMatchObject({ percent: 100, detail: 'Extracting' });
    expect(last().bytesTotal).toBeUndefined();
  });

  it('broadcasts a label change immediately even inside the throttle window', () => {
    const a = hub.begin({ id: 'a', kind: 'model', label: 'A' });
    a.update({ bytesDone: 1, bytesTotal: 100 });
    clock += 10;
    a.update({ label: 'A (renamed)' });

    expect(last().label).toBe('A (renamed)');
  });
});

describe('DownloadHub snapshot and cancel', () => {
  it('returns active items plus items that ended in the last 30s', () => {
    hub.begin({ id: 'running', kind: 'model', label: 'Running' });
    hub.begin({ id: 'old', kind: 'model', label: 'Old' }).complete();
    clock += 31_000;
    hub.begin({ id: 'recent', kind: 'model', label: 'Recent' }).fail('boom');

    expect(
      hub
        .snapshot()
        .map((i) => i.id)
        .sort(),
    ).toEqual(['recent', 'running']);
  });

  it('runs the registered cancel callback and reports whether one existed', () => {
    const cancel = vi.fn();
    hub.begin({ id: 'a', kind: 'server-image', label: 'A', cancel });
    hub.begin({ id: 'b', kind: 'model', label: 'B' });

    expect(last().cancellable).toBe(false);
    expect(hub.snapshot().find((i) => i.id === 'a')?.cancellable).toBe(true);
    expect(hub.cancel('a')).toBe(true);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(hub.cancel('b')).toBe(false);
    expect(hub.cancel('missing')).toBe(false);
  });

  it('ends every running item of one source without touching the other', () => {
    hub.begin({ id: 'srv', kind: 'model', label: 'Model', source: 'server' });
    hub.begin({ id: 'app', kind: 'server-image', label: 'Image' });

    hub.endAllFromSource('server', 'Server stopped');

    const byId = Object.fromEntries(hub.snapshot().map((i) => [i.id, i]));
    expect(byId.srv).toMatchObject({ status: 'cancelled', detail: 'Server stopped' });
    expect(byId.app.status).toBe('active');
  });
});
