/**
 * RemoteClientSettingsCard — the client-side remote connection settings shown
 * in the Server tab while the Remote runtime tile is selected.
 *
 * Verifies: hydration from connection.* config, the SettingsModal-inherited
 * validation rules (blank host per profile, port range), and the apply
 * contract (config writes + apiClient re-sync).
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../../../../src/api/client', () => ({
  apiClient: {
    checkConnection: vi
      .fn()
      .mockResolvedValue({ reachable: false, ready: false, status: null, error: null }),
    syncFromConfig: vi.fn().mockResolvedValue(undefined),
    setAuthToken: vi.fn(),
  },
}));

vi.mock('../../../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
  DEFAULT_SERVER_PORT: 9786,
}));

vi.mock('../../../../src/hooks/useClipboard', () => ({
  writeToClipboard: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Plain <select> stand-in so profile switching works without headlessui.
vi.mock('../../../ui/CustomSelect', () => ({
  CustomSelect: ({
    value,
    onChange,
    options,
  }: {
    value: string;
    onChange: (v: string) => void;
    options: string[];
  }) =>
    React.createElement(
      'select',
      {
        'aria-label': 'Remote Profile',
        value,
        onChange: (e: React.ChangeEvent<HTMLSelectElement>) => onChange(e.target.value),
      },
      options.map((o) => React.createElement('option', { key: o, value: o }, o)),
    ),
}));

import { RemoteClientSettingsCard } from '../RemoteClientSettingsCard';
import { getConfig, setConfig } from '../../../../src/config/store';
import { apiClient } from '../../../../src/api/client';
import { toast } from 'sonner';

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(RemoteClientSettingsCard, { title: '4. Remote Connection' }),
    ),
  );
  return { qc, ...utils };
}

function seedStoredConnection() {
  vi.mocked(getConfig).mockImplementation(async (key: string) => {
    if (key === 'connection.remoteProfile') return 'tailscale';
    if (key === 'connection.remoteHost') return 'gpu-box.tail1234.ts.net';
    if (key === 'connection.lanHost') return '';
    if (key === 'connection.authToken') return 'remote-token';
    if (key === 'connection.port') return 9786;
    return undefined;
  });
}

describe('RemoteClientSettingsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getConfig).mockResolvedValue(undefined);
    vi.mocked(setConfig).mockResolvedValue(undefined);
  });

  it('hydrates the stored connection settings into the fields', async () => {
    seedStoredConnection();
    renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('gpu-box.tail1234.ts.net')).toBeDefined();
    });
    expect(screen.getByDisplayValue('remote-token')).toBeDefined();
    expect(screen.getByDisplayValue('9786')).toBeDefined();
  });

  it('prompts for host + token while unconfigured and blocks Apply with a validation toast', async () => {
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/hostname and auth token, then press Apply/)).toBeDefined();
    });
    fireEvent.click(screen.getByText('Apply').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        'Tailscale remote mode requires a host or IP address.',
      );
    });
    expect(setConfig).not.toHaveBeenCalled();
  });

  it('requires a LAN host when the LAN profile is selected', async () => {
    seedStoredConnection();
    renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('gpu-box.tail1234.ts.net')).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText('Remote Profile'), { target: { value: 'LAN' } });
    expect(screen.getByText('LAN Host / IP')).toBeDefined();
    fireEvent.click(screen.getByText('Apply').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('LAN remote mode requires a host or IP address.');
    });
    expect(setConfig).not.toHaveBeenCalled();
  });

  it('rejects an out-of-range port', async () => {
    seedStoredConnection();
    renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('9786')).toBeDefined();
    });
    fireEvent.change(screen.getByDisplayValue('9786'), { target: { value: '0' } });
    fireEvent.click(screen.getByText('Apply').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Port must be a number between 1 and 65535.');
    });
    expect(setConfig).not.toHaveBeenCalled();
  });

  it('applies a valid configuration: writes connection.* keys and re-syncs the api client', async () => {
    seedStoredConnection();
    renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('gpu-box.tail1234.ts.net')).toBeDefined();
    });
    fireEvent.click(screen.getByText('Apply').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(vi.mocked(setConfig).mock.calls).toEqual(
        expect.arrayContaining([
          ['connection.remoteProfile', 'tailscale'],
          ['connection.remoteHost', 'gpu-box.tail1234.ts.net'],
          ['connection.authToken', 'remote-token'],
          ['connection.port', 9786],
          ['connection.useHttps', true],
          ['connection.useRemote', true],
        ]),
      );
    });
    expect(apiClient.syncFromConfig).toHaveBeenCalled();
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('remote-token');
    expect(toast.success).toHaveBeenCalledWith('Remote connection settings applied.');
  });

  it('surfaces a save failure and re-enables the Apply button', async () => {
    seedStoredConnection();
    vi.mocked(setConfig).mockRejectedValue(new Error('ipc down'));
    renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('gpu-box.tail1234.ts.net')).toBeDefined();
    });
    fireEvent.click(screen.getByText('Apply').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Could not save the remote connection settings.');
    });
    // The applying state cleared: the button shows its label again, enabled.
    const applyButton = screen.getByText('Apply').closest('button') as HTMLButtonElement;
    expect(applyButton.disabled).toBe(false);
  });

  it('mirrors the auth token cache while pristine but never clobbers unapplied typing', async () => {
    seedStoredConnection();
    const { qc } = renderCard();
    await waitFor(() => {
      expect(screen.getByDisplayValue('remote-token')).toBeDefined();
    });
    // Pristine field: a cache update (e.g. useAuthTokenSync detection) flows in.
    act(() => {
      qc.setQueryData(['authToken'], 'detected-token');
    });
    await waitFor(() => {
      expect(screen.getByDisplayValue('detected-token')).toBeDefined();
    });
    // Dirty field: unapplied user typing wins over later cache writes.
    fireEvent.change(screen.getByDisplayValue('detected-token'), {
      target: { value: 'typed-token' },
    });
    act(() => {
      qc.setQueryData(['authToken'], 'clobber-attempt');
    });
    await waitFor(() => {
      expect(screen.getByDisplayValue('typed-token')).toBeDefined();
    });
    expect(screen.queryByDisplayValue('clobber-attempt')).toBeNull();
  });

  it('warns when a bare tailnet name is entered as the host', async () => {
    vi.mocked(getConfig).mockImplementation(async (key: string) => {
      if (key === 'connection.remoteHost') return 'tail1234.ts.net';
      if (key === 'connection.remoteProfile') return 'tailscale';
      return undefined;
    });
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/This looks like a tailnet name/)).toBeDefined();
    });
  });
});
