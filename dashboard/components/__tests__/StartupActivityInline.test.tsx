/**
 * StartupActivityInline — inline mirror of active download/startup activity
 * for the Server tab (GH-207).
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';

import { StartupActivityInline } from '../views/server/StartupActivityInline';
import { useActivityStore } from '../../src/stores/activityStore';

beforeEach(() => {
  useActivityStore.setState({ items: [] });
});

describe('StartupActivityInline (GH-207)', () => {
  it('renders label, percentage, and sizes for an active download item', () => {
    useActivityStore.getState().addActivity({
      id: 'model-load-parakeet',
      category: 'download',
      label: 'Downloading parakeet-tdt-0.6b-v2...',
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
    useActivityStore.getState().addActivity({
      id: 'model-load-x',
      category: 'download',
      label: 'Loading test-model into memory...',
      status: 'active',
    });
    render(<StartupActivityInline />);

    expect(screen.getByText('Loading test-model into memory...')).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).toBeNull();
  });

  it('renders nothing when all items are complete', () => {
    useActivityStore.getState().addActivity({
      id: 'model-load-x',
      category: 'download',
      label: 'test-model ready',
      status: 'complete',
    });
    const { container } = render(<StartupActivityInline />);

    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for dismissed items', () => {
    useActivityStore.getState().addActivity({
      id: 'model-load-x',
      category: 'download',
      label: 'Downloading x...',
      status: 'active',
    });
    useActivityStore.getState().dismissActivity('model-load-x');
    const { container } = render(<StartupActivityInline />);

    expect(container).toBeEmptyDOMElement();
  });
});
