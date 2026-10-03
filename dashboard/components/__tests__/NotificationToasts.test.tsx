import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { NotificationToasts } from '../ui/NotificationToasts';
import { useNotificationsStore } from '../../src/stores/notificationsStore';

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
});

describe('NotificationToasts', () => {
  it('renders nothing when there are no toasts', () => {
    const { container } = render(<NotificationToasts />);
    expect(container.firstChild).toBeNull();
  });

  it('shows a progress bar for an active notification that reports progress', () => {
    useNotificationsStore.getState().notify({
      id: 'salvage-1',
      category: 'transcription',
      title: 'Recovering transcription',
      progress: 40,
    });
    render(<NotificationToasts />);
    expect(screen.getByText('Recovering transcription')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
  });

  it('shows no bar for an active notification without a measured progress', () => {
    useNotificationsStore.getState().notify({
      id: 'server-start',
      category: 'server',
      title: 'Starting server...',
      detail: 'Loading model',
    });
    render(<NotificationToasts />);
    expect(screen.getByText('Starting server...')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('never shows a bar or sizes on a download row - the download bar owns that', () => {
    useNotificationsStore.getState().notify({
      id: 'download:x@1',
      category: 'download',
      title: 'parakeet downloaded',
      detail: '2.6 GB in 3m 12s',
      status: 'complete',
    });
    render(<NotificationToasts />);
    expect(screen.getByText('parakeet downloaded')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('dismiss hides the toast but keeps the record', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
    });
    render(<NotificationToasts />);
    fireEvent.click(screen.getByTitle('Dismiss'));
    expect(screen.queryByText('Downloading model')).not.toBeInTheDocument();
    const record = useNotificationsStore.getState().notifications.find((n) => n.id === 'dl-1');
    expect(record).toBeDefined();
    expect(record!.toastDismissed).toBe(true);
  });
});

describe('NotificationToasts auto-dismiss timer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('auto-dismisses a completed toast after 5000ms but keeps the record', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
      status: 'complete',
    });
    render(<NotificationToasts />);
    expect(screen.getByText('Downloading model')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.queryByText('Downloading model')).not.toBeInTheDocument();
    const record = useNotificationsStore.getState().notifications.find((n) => n.id === 'dl-1');
    expect(record).toBeDefined();
    expect(record!.toastDismissed).toBe(true);
  });

  it('does not restart the timer when the completed entry receives an unrelated patch', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
      status: 'complete',
    });
    render(<NotificationToasts />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText('Downloading model')).toBeInTheDocument();

    act(() => {
      useNotificationsStore.getState().updateNotification('dl-1', { detail: 'something' });
    });

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.queryByText('Downloading model')).not.toBeInTheDocument();
  });

  it('does not auto-dismiss an active toast', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
      status: 'active',
    });
    render(<NotificationToasts />);

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(screen.getByText('Downloading model')).toBeInTheDocument();
  });
});
