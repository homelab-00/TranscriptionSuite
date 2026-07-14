/**
 * ActivityNotifications — progress bar visibility (GH-207).
 *
 * The bar must be data-driven: shown when an active download item carries
 * progress data, hidden when it does not — regardless of legacyType. The old
 * logic hard-coded `legacyType !== 'model-preload'`, which suppressed real
 * byte progress on GGML downloads and rendered a fake indeterminate bar on
 * legacy items with no progress data at all.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';

import { ActivityNotifications } from '../ui/ActivityNotifications';
import { useActivityStore } from '../../src/stores/activityStore';

const PROGRESS_BAR_SELECTOR = '.h-1';

beforeEach(() => {
  useActivityStore.setState({ items: [] });
});

describe('ActivityNotifications progress bar (GH-207)', () => {
  it('shows the progress bar and sizes for an active download item carrying progress data', () => {
    useActivityStore.getState().addActivity({
      id: 'model-load-x',
      category: 'download',
      label: 'Downloading x...',
      status: 'active',
      progress: 42,
      downloadedSize: '300 MB',
      totalSize: '700 MB',
    });
    const { container } = render(<ActivityNotifications />);

    expect(container.querySelector(PROGRESS_BAR_SELECTOR)).not.toBeNull();
    expect(screen.getByText(/300 MB \/ 700 MB/)).toBeInTheDocument();
  });

  it('shows the progress bar for a model-preload-typed item that carries progress data (GGML path)', () => {
    useActivityStore.getState().addActivity({
      id: 'ggml-download-ggml-large-v3.bin',
      category: 'download',
      label: 'Downloading ggml-large-v3.bin...',
      status: 'active',
      legacyType: 'model-preload',
      progress: 55,
      downloadedSize: '1.6 GB',
      totalSize: '2.9 GB',
    });
    const { container } = render(<ActivityNotifications />);

    expect(container.querySelector(PROGRESS_BAR_SELECTOR)).not.toBeNull();
    expect(screen.getByText(/1\.6 GB \/ 2\.9 GB/)).toBeInTheDocument();
  });

  it('shows no progress bar for a legacy spinner-only item without progress data', () => {
    useActivityStore.getState().addActivity({
      id: 'model-preload',
      category: 'download',
      label: 'Loading Model',
      status: 'active',
      legacyType: 'model-preload',
    });
    const { container } = render(<ActivityNotifications />);

    expect(container.querySelector(PROGRESS_BAR_SELECTOR)).toBeNull();
  });

  it('shows no progress bar for a legacy docker-image item without progress data', () => {
    useActivityStore.getState().addActivity({
      id: 'docker-pull',
      category: 'download',
      label: 'Pulling server image...',
      status: 'active',
      legacyType: 'docker-image',
    });
    const { container } = render(<ActivityNotifications />);

    expect(container.querySelector(PROGRESS_BAR_SELECTOR)).toBeNull();
  });
});
