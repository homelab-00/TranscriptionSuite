/**
 * StartupActivityInline — inline mirror of active download/startup activity
 * for the Server tab (GH-207).
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';

import { StartupActivityInline } from '../views/server/StartupActivityInline';
import { useNotificationsStore } from '../../src/stores/notificationsStore';

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
});

describe('StartupActivityInline (GH-207)', () => {
  it('renders label, percentage, and sizes for an active download item', () => {
    useNotificationsStore.getState().notify({
      id: 'model-load-parakeet',
      category: 'download',
      title: 'Downloading parakeet-tdt-0.6b-v2...',
      status: 'active',
      progress: 37,
      downloadedSize: '1.1 GB',
      totalSize: '2.9 GB',
    });
    render(<StartupActivityInline />);

    expect(screen.getByText('Downloading parakeet-tdt-0.6b-v2...')).toBeInTheDocument();
    expect(screen.getByText('37%')).toBeInTheDocument();
    expect(screen.getByText('1.1 GB / 2.9 GB')).toBeInTheDocument();
  });

  it('renders an active item without progress data as label only', () => {
    useNotificationsStore.getState().notify({
      id: 'model-load-x',
      category: 'download',
      title: 'Loading test-model into memory...',
      status: 'active',
    });
    render(<StartupActivityInline />);

    expect(screen.getByText('Loading test-model into memory...')).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).toBeNull();
  });

  it('renders nothing when all items are complete', () => {
    useNotificationsStore.getState().notify({
      id: 'model-load-x',
      category: 'download',
      title: 'test-model ready',
      status: 'complete',
    });
    const { container } = render(<StartupActivityInline />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders only download/server items, not other active categories', () => {
    useNotificationsStore.getState().notify({
      id: 'docker-image-latest',
      category: 'download',
      title: 'Downloading server image...',
      status: 'active',
    });
    useNotificationsStore.getState().notify({
      id: 'rec-1',
      category: 'recording',
      title: 'Recording live note...',
      status: 'active',
    });
    render(<StartupActivityInline />);

    expect(screen.getByText('Downloading server image...')).toBeInTheDocument();
    expect(screen.queryByText('Recording live note...')).toBeNull();
  });

  it('renders nothing for items whose toast is dismissed', () => {
    useNotificationsStore.getState().notify({
      id: 'model-load-x',
      category: 'download',
      title: 'Downloading x...',
      status: 'active',
    });
    useNotificationsStore.getState().dismissToast('model-load-x');
    const { container } = render(<StartupActivityInline />);

    expect(container).toBeEmptyDOMElement();
  });
});
