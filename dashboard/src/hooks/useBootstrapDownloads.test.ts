/**
 * useBootstrapDownloads — IPC-to-activity-store bridge (GH-207).
 *
 * Covers the legacy-card dedupe (a granular `model-load-*` event dismisses
 * the coarse `model-preload` spinner card) and byte-progress forwarding on
 * the legacy download-event bridge (GGML downloads).
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useBootstrapDownloads } from './useBootstrapDownloads';
import { useActivityStore } from '../stores/activityStore';

type Callback = (event: Record<string, unknown>) => void;

let downloadEventCallback: Callback | null = null;
let activityEventCallback: Callback | null = null;

beforeEach(() => {
  useActivityStore.setState({ items: [] });
  downloadEventCallback = null;
  activityEventCallback = null;
  (window as unknown as { electronAPI: unknown }).electronAPI = {
    docker: {
      onDownloadEvent: (cb: Callback) => {
        downloadEventCallback = cb;
        return vi.fn();
      },
      onActivityEvent: (cb: Callback) => {
        activityEventCallback = cb;
        return vi.fn();
      },
    },
  };
});

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

describe('useBootstrapDownloads (GH-207)', () => {
  it('dismisses the legacy model-preload card when a granular model-load-* event arrives', () => {
    renderHook(() => useBootstrapDownloads());

    downloadEventCallback!({
      action: 'start',
      id: 'model-preload',
      type: 'model-preload',
      label: 'Loading Model',
    });
    expect(useActivityStore.getState().items.find((i) => i.id === 'model-preload')?.dismissed).toBe(
      false,
    );

    activityEventCallback!({
      id: 'model-load-nvidia--parakeet-tdt-0.6b-v2',
      category: 'download',
      label: 'Downloading parakeet-tdt-0.6b-v2...',
      status: 'active',
      progress: 10,
    });

    const items = useActivityStore.getState().items;
    expect(items.find((i) => i.id === 'model-preload')?.dismissed).toBe(true);
    expect(items.find((i) => i.id === 'model-load-nvidia--parakeet-tdt-0.6b-v2')?.dismissed).toBe(
      false,
    );
  });

  it('is a no-op when a granular event arrives without a legacy card present', () => {
    renderHook(() => useBootstrapDownloads());

    activityEventCallback!({
      id: 'model-load-large-v3-turbo',
      category: 'download',
      label: 'Downloading large-v3-turbo...',
      status: 'active',
    });

    const items = useActivityStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe('model-load-large-v3-turbo');
  });

  it('forwards byte progress fields on legacy download events (GGML path)', () => {
    renderHook(() => useBootstrapDownloads());

    downloadEventCallback!({
      action: 'start',
      id: 'ggml-download-ggml-large-v3.bin',
      type: 'model-preload',
      label: 'Downloading ggml-large-v3.bin...',
      progress: 55,
      downloadedSize: '1.6 GB',
      totalSize: '2.9 GB',
    });

    const item = useActivityStore
      .getState()
      .items.find((i) => i.id === 'ggml-download-ggml-large-v3.bin');
    expect(item).toBeDefined();
    expect(item!.progress).toBe(55);
    expect(item!.downloadedSize).toBe('1.6 GB');
    expect(item!.totalSize).toBe('2.9 GB');
  });
});
