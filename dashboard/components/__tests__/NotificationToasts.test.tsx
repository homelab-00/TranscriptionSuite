import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

  it('shows an active notification with its progress bar', () => {
    useNotificationsStore.getState().notify({
      id: 'dl-1',
      category: 'download',
      title: 'Downloading model',
      progress: 40,
    });
    render(<NotificationToasts />);
    expect(screen.getByText('Downloading model')).toBeInTheDocument();
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
