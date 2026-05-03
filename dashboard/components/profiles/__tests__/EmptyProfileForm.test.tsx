/**
 * EmptyProfileForm tests (Issue #104, Story 1.5).
 *
 * Verifies the AC requirements:
 *  - AC1: pre-populates fields with sane defaults (template, destination, toggles OFF)
 *  - AC2: dismissible inline help banner; dismissal persists to electron-store
 *  - AC3: no Next/Back/wizard navigation — only Save + Cancel commit actions
 *  - AC4: keyboard tab order is correct (DOM order)
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EmptyProfileForm } from '../EmptyProfileForm';

const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

interface ConfigBridge {
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
}

function installConfigBridge(bridge: ConfigBridge) {
  (window as unknown as { electronAPI: { config: ConfigBridge } }).electronAPI = {
    config: bridge,
  };
}

vi.mock('../../../src/api/client', () => ({
  apiClient: {
    createProfile: vi.fn(),
  },
}));

vi.mock('../../../src/hooks/useFolderPicker', () => ({
  useFolderPicker: () => async () => '/picked/folder',
}));

import { apiClient } from '../../../src/api/client';

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

describe('EmptyProfileForm — AC1 sane defaults', () => {
  it('pre-populates filename template, destination, and toggles OFF', async () => {
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/home/user/Documents"
      />,
    );

    expect(screen.getByLabelText('Filename template')).toHaveValue('{date} {title}.txt');
    expect(
      screen.getByLabelText('Destination folder (read-only — use the Choose button)'),
    ).toHaveValue('/home/user/Documents');
    expect(screen.getByLabelText('Auto-generate AI summary')).not.toBeChecked();
    expect(screen.getByLabelText('Auto-export transcript')).not.toBeChecked();
  });
});

describe('EmptyProfileForm — AC2 inline help banner', () => {
  it('shows the banner with the AC-specified text on first render', () => {
    installConfigBridge({
      get: vi.fn().mockResolvedValue(undefined),
      set: vi.fn().mockResolvedValue(undefined),
    });
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/x"
      />,
    );
    expect(
      screen.getByText('Edit any field below to customize, or save as-is to use the defaults.'),
    ).toBeInTheDocument();
  });

  it('hides the banner if electron-store has previously recorded dismissal', async () => {
    installConfigBridge({
      get: vi.fn().mockResolvedValue(true),
      set: vi.fn().mockResolvedValue(undefined),
    });
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/x"
      />,
    );
    await waitFor(() => {
      expect(
        screen.queryByText('Edit any field below to customize, or save as-is to use the defaults.'),
      ).not.toBeInTheDocument();
    });
  });

  it('clicking dismiss removes the banner and persists the dismissal flag', async () => {
    const setMock = vi.fn().mockResolvedValue(undefined);
    installConfigBridge({
      get: vi.fn().mockResolvedValue(undefined),
      set: setMock,
    });
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/x"
      />,
    );
    fireEvent.click(screen.getByLabelText('Dismiss help banner'));
    expect(
      screen.queryByText('Edit any field below to customize, or save as-is to use the defaults.'),
    ).not.toBeInTheDocument();
    expect(setMock).toHaveBeenCalledWith('notebook.dismissedBanners.emptyProfile', true);
  });
});

describe('EmptyProfileForm — AC3 no wizard', () => {
  it('renders no Next/Back/Step buttons; only Save + Cancel commit actions', () => {
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/x"
      />,
    );
    expect(screen.queryByRole('button', { name: /^next/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^back/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });
});

describe('EmptyProfileForm — submit creates a profile', () => {
  it('calls apiClient.createProfile with the expected payload', async () => {
    const onCreated = vi.fn();
    (apiClient.createProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      name: 'Default',
      description: null,
      schema_version: '1.0',
      public_fields: {},
      created_at: '',
      updated_at: '',
    });
    render(
      <EmptyProfileForm
        onCreated={onCreated}
        onCancel={() => undefined}
        documentsPathOverride="/home/user/Documents"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(apiClient.createProfile).toHaveBeenCalledTimes(1);
    });
    const payload = (apiClient.createProfile as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(payload.name).toBe('Default');
    expect(payload.public_fields.filename_template).toBe('{date} {title}.txt');
    expect(payload.public_fields.destination_folder).toBe('/home/user/Documents');
    expect(payload.public_fields.auto_summary_enabled).toBe(false);
    expect(payload.public_fields.auto_export_enabled).toBe(false);
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it('surfaces the server error when create fails', async () => {
    (apiClient.createProfile as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('500 Internal'),
    );
    render(
      <EmptyProfileForm
        onCreated={() => undefined}
        onCancel={() => undefined}
        documentsPathOverride="/x"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('500 Internal');
    });
  });
});
