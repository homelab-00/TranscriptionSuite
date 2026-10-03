import { describe, it, expect } from 'vitest';
import {
  aggregateDownloads,
  describeProgress,
  formatBytes,
  formatDuration,
  itemFraction,
} from '../downloadProgress';

function item(patch: Partial<DownloadItem>): DownloadItem {
  return {
    id: 'a',
    runId: 'a@1',
    kind: 'model',
    source: 'server',
    label: 'A',
    status: 'active',
    cancellable: false,
    startedAt: 0,
    updatedAt: 0,
    errorToast: true,
    ...patch,
  };
}

describe('formatBytes', () => {
  it('formats with binary units and one decimal above bytes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1024 * 1024 * 312)).toBe('312.0 MB');
    expect(formatBytes(1024 ** 3 * 2.6)).toBe('2.6 GB');
  });
});

describe('formatDuration', () => {
  it('uses the two most significant units', () => {
    expect(formatDuration(8)).toBe('8s');
    expect(formatDuration(130)).toBe('2m 10s');
    expect(formatDuration(3720)).toBe('1h 2m');
  });
});

describe('itemFraction', () => {
  it('prefers bytes over a coarse percent', () => {
    expect(itemFraction(item({ bytesDone: 25, bytesTotal: 100, percent: 90 }))).toBe(0.25);
  });

  it('falls back to the percent when bytes are unknown', () => {
    expect(itemFraction(item({ percent: 40 }))).toBe(0.4);
  });

  it('is null when nothing measurable is known', () => {
    expect(itemFraction(item({}))).toBeNull();
    expect(itemFraction(item({ bytesDone: 50 }))).toBeNull();
  });

  it('clamps to the 0-1 range', () => {
    expect(itemFraction(item({ bytesDone: 150, bytesTotal: 100 }))).toBe(1);
  });
});

describe('aggregateDownloads', () => {
  it('weights by bytes when every active item reports bytes', () => {
    const agg = aggregateDownloads([
      item({ runId: '1', bytesDone: 100, bytesTotal: 100, bytesPerSecond: 10 }),
      item({ runId: '2', bytesDone: 0, bytesTotal: 300, bytesPerSecond: 20 }),
    ]);

    expect(agg.fraction).toBe(0.25);
    expect(agg.bytesDone).toBe(100);
    expect(agg.bytesTotal).toBe(400);
    expect(agg.bytesPerSecond).toBe(30);
    expect(agg.etaSeconds).toBe(10);
  });

  it('averages fractions without an ETA when some items only have a percent', () => {
    const agg = aggregateDownloads([
      item({ runId: '1', bytesDone: 100, bytesTotal: 100 }),
      item({ runId: '2', percent: 50 }),
    ]);

    expect(agg.fraction).toBe(0.75);
    expect(agg.bytesTotal).toBeUndefined();
    expect(agg.etaSeconds).toBeUndefined();
  });

  it('is indeterminate as soon as one active item is indeterminate', () => {
    const agg = aggregateDownloads([
      item({ runId: '1', bytesDone: 100, bytesTotal: 200 }),
      item({ runId: '2' }),
    ]);

    expect(agg.fraction).toBeNull();
    expect(agg.activeCount).toBe(2);
    expect(agg.determinateCount).toBe(1);
  });

  it('leaves failed and finished items out of the aggregate', () => {
    const agg = aggregateDownloads([
      item({ runId: '1', bytesDone: 50, bytesTotal: 100 }),
      item({ runId: '2', status: 'error' }),
      item({ runId: '3', status: 'complete', bytesDone: 10, bytesTotal: 10 }),
    ]);

    expect(agg.activeCount).toBe(1);
    expect(agg.fraction).toBe(0.5);
  });

  it('is indeterminate with no active items', () => {
    expect(aggregateDownloads([item({ status: 'error' })]).fraction).toBeNull();
  });
});

describe('describeProgress', () => {
  it('joins percent, bytes, speed and time left', () => {
    expect(
      describeProgress({
        fraction: 0.42,
        bytesDone: 1024 ** 3,
        bytesTotal: 1024 ** 3 * 2,
        bytesPerSecond: 1024 * 1024 * 12,
        etaSeconds: 130,
      }),
    ).toBe('42% · 1.0 GB / 2.0 GB · 12.0 MB/s · 2m 10s left');
  });

  it('shows only the downloaded bytes when the total is unknown', () => {
    expect(describeProgress({ fraction: null, bytesDone: 1536 })).toBe('1.5 KB');
  });

  it('is empty when nothing is known', () => {
    expect(describeProgress({ fraction: null })).toBe('');
  });
});
