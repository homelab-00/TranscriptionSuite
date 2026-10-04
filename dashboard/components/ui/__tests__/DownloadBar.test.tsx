/**
 * GH-318 - the universal download bar. One strip for every download in the
 * app: hidden when idle, a single row for one download, an expandable list
 * for several.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { DownloadBar } from '../DownloadBar';
import { useDownloadsStore } from '../../../src/stores/downloadsStore';

function item(patch: Partial<DownloadItem>): DownloadItem {
  return {
    id: 'a',
    runId: 'a@1',
    kind: 'model',
    source: 'server',
    label: 'parakeet',
    status: 'active',
    cancellable: false,
    startedAt: 0,
    updatedAt: 0,
    errorToast: true,
    ...patch,
  };
}

const cancel = vi.fn(async () => true);

beforeEach(() => {
  cancel.mockClear();
  useDownloadsStore.setState({ items: [] });
  (window as { electronAPI?: unknown }).electronAPI = {
    downloads: { cancel, getSnapshot: vi.fn(), onChanged: vi.fn() },
  };
});

afterEach(() => {
  delete (window as { electronAPI?: unknown }).electronAPI;
});

describe('DownloadBar', () => {
  it('renders nothing when no download is running', () => {
    const { container } = render(<DownloadBar />);

    expect(container.firstChild).toBeNull();
  });

  it('shows a single download with its percent and bytes', () => {
    useDownloadsStore.setState({
      items: [item({ bytesDone: 1024 ** 3, bytesTotal: 1024 ** 3 * 2 })],
    });
    render(<DownloadBar />);

    expect(screen.getByRole('region', { name: 'Downloads' })).toBeInTheDocument();
    expect(screen.getByText('Downloading parakeet')).toBeInTheDocument();
    expect(screen.getByText('50% · 1.0 GB / 2.0 GB')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
  });

  it('shows an indeterminate bar when the source cannot report progress', () => {
    useDownloadsStore.setState({ items: [item({ label: 'Server image (latest)' })] });
    render(<DownloadBar />);

    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  });

  it('shows the detail line of the running download', () => {
    useDownloadsStore.setState({ items: [item({ detail: 'torch, nvidia-cudnn-cu12' })] });
    render(<DownloadBar />);

    expect(screen.getByText('torch, nvidia-cudnn-cu12')).toBeInTheDocument();
  });

  it('cancels a cancellable download through the hub', () => {
    useDownloadsStore.setState({ items: [item({ id: 'server-image:latest', cancellable: true })] });
    render(<DownloadBar />);

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(cancel).toHaveBeenCalledWith('server-image:latest');
  });

  it('offers no cancel button for a download that cannot be cancelled', () => {
    useDownloadsStore.setState({ items: [item({})] });
    render(<DownloadBar />);

    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('keeps a failed download visible with its error until dismissed', () => {
    useDownloadsStore.setState({ items: [item({ status: 'error', error: 'network down' })] });
    render(<DownloadBar />);

    expect(screen.getByText('parakeet download failed')).toBeInTheDocument();
    expect(screen.getByText('network down')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(useDownloadsStore.getState().items).toHaveLength(0);
  });

  it('confirms a finished download', () => {
    useDownloadsStore.setState({ items: [item({ status: 'complete' })] });
    render(<DownloadBar />);

    expect(screen.getByText('parakeet downloaded')).toBeInTheDocument();
  });

  it('summarises several downloads and lists them when expanded', () => {
    useDownloadsStore.setState({
      items: [
        item({ id: 'a', runId: 'a@1', label: 'parakeet', bytesDone: 50, bytesTotal: 100 }),
        item({ id: 'b', runId: 'b@1', label: 'Server image (latest)', startedAt: 5 }),
      ],
    });
    render(<DownloadBar />);

    expect(screen.getByText('2 downloads')).toBeInTheDocument();
    // One indeterminate item makes the aggregate indeterminate.
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');

    const toggle = screen.getByRole('button', { name: 'Show all downloads' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);

    const list = screen.getByRole('list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(within(list).getByText('parakeet')).toBeInTheDocument();
    expect(within(list).getByText('Server image (latest)')).toBeInTheDocument();
    expect(within(list).getAllByRole('progressbar')[0]).toHaveAttribute('aria-valuenow', '50');
  });

  it('counts failures separately in the summary', () => {
    useDownloadsStore.setState({
      items: [
        item({ id: 'a', runId: 'a@1' }),
        item({ id: 'b', runId: 'b@1', status: 'error', error: 'boom', startedAt: 5 }),
      ],
    });
    render(<DownloadBar />);

    expect(screen.getByText('1 download, 1 failed')).toBeInTheDocument();
  });
});
