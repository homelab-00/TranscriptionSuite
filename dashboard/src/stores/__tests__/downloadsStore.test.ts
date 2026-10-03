import { describe, it, expect, beforeEach } from 'vitest';
import { useDownloadsStore } from '../downloadsStore';

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

const items = (): DownloadItem[] => useDownloadsStore.getState().items;

describe('downloadsStore', () => {
  beforeEach(() => useDownloadsStore.setState({ items: [] }));

  it('adds a new item and replaces it by runId on later updates', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ updatedAt: 1, bytesDone: 1 }));
    store.upsert(item({ updatedAt: 2, bytesDone: 5 }));

    expect(items()).toHaveLength(1);
    expect(items()[0].bytesDone).toBe(5);
  });

  it('ignores an update older than what it already holds', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ updatedAt: 10, bytesDone: 9 }));
    store.upsert(item({ updatedAt: 4, bytesDone: 2 }));

    expect(items()[0].bytesDone).toBe(9);
  });

  it('keeps a failed item until it is dismissed', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ status: 'error', error: 'boom', updatedAt: 1 }));
    expect(items()).toHaveLength(1);

    store.dismiss('a@1');
    expect(items()).toHaveLength(0);
  });

  it('drops a cancelled item straight away', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ updatedAt: 1 }));
    store.upsert(item({ status: 'cancelled', updatedAt: 2 }));

    expect(items()).toHaveLength(0);
  });

  it('replaces an older failed run when the same id starts again', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ runId: 'a@1', status: 'error', updatedAt: 1 }));
    store.upsert(item({ runId: 'a@2', status: 'active', updatedAt: 2 }));

    expect(items().map((i) => i.runId)).toEqual(['a@2']);
  });

  it('ignores a late event for a run that a newer run already replaced', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ runId: 'a@2', startedAt: 20, updatedAt: 20 }));
    store.upsert(item({ runId: 'a@1', startedAt: 10, status: 'error', updatedAt: 30 }));

    expect(items().map((i) => i.runId)).toEqual(['a@2']);
  });

  it('keeps items ordered by start time', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({ id: 'late', runId: 'late@1', startedAt: 20 }));
    store.upsert(item({ id: 'early', runId: 'early@1', startedAt: 10 }));

    expect(items().map((i) => i.id)).toEqual(['early', 'late']);
  });

  it('removes by runId and tolerates an unknown one', () => {
    const store = useDownloadsStore.getState();
    store.upsert(item({}));
    store.remove('nope');
    expect(items()).toHaveLength(1);

    store.remove('a@1');
    expect(items()).toHaveLength(0);
  });
});
