/**
 * ModelProfileSelector tests (Issue #104, Stories 8.3 + 8.4).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ModelProfileSelector } from '../ModelProfileSelector';
import { type ModelProfile } from '../../../src/services/modelProfileStore';

const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

interface FakeBridge {
  values: Map<string, unknown>;
  get: ReturnType<typeof vi.fn>;
  set: ReturnType<typeof vi.fn>;
}

function installFakeBridge(initial: Record<string, unknown> = {}): FakeBridge {
  const values = new Map<string, unknown>(Object.entries(initial));
  const bridge: FakeBridge = {
    values,
    get: vi.fn(async (key: string) => values.get(key)),
    set: vi.fn(async (key: string, value: unknown) => {
      values.set(key, value);
    }),
  };
  (window as unknown as { electronAPI: { config: FakeBridge } }).electronAPI = {
    config: bridge,
  };
  return bridge;
}

const SAMPLE_PROFILES: ModelProfile[] = [
  {
    id: 'mp_fast',
    name: 'Fast English',
    sttModel: 'nvidia/parakeet-tdt-0.6b-v2',
    sttLanguage: 'en',
    translateTarget: null,
    createdAt: '2025-01-15T12:00:00Z',
    updatedAt: '2025-01-15T12:00:00Z',
  },
  {
    id: 'mp_multi',
    name: 'Multilingual',
    sttModel: 'nvidia/canary-1b-flash',
    sttLanguage: 'auto',
    translateTarget: 'en',
    createdAt: '2025-01-15T12:00:00Z',
    updatedAt: '2025-01-15T12:00:00Z',
  },
];

beforeEach(() => {
  installFakeBridge();
});

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

describe('ModelProfileSelector', () => {
  it('shows "No model profiles" when none exist (AC8.3 AC1 empty state)', async () => {
    render(<ModelProfileSelector liveModeActive={false} onSwitch={async () => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/no model profiles/i)).toBeInTheDocument();
    });
  });

  it('lists profiles and highlights the persisted active id (AC8.4 first-paint)', async () => {
    installFakeBridge({
      'notebook.modelProfiles': SAMPLE_PROFILES,
      'notebook.activeModelProfileId': 'mp_multi',
    });
    render(<ModelProfileSelector liveModeActive={false} onSwitch={async () => {}} />);
    await waitFor(() => {
      expect(screen.getByLabelText('Active model profile')).toHaveValue('mp_multi');
    });
  });

  it('switches active profile and persists to electron-store (AC8.3 AC2 + AC8.4)', async () => {
    const bridge = installFakeBridge({
      'notebook.modelProfiles': SAMPLE_PROFILES,
      'notebook.activeModelProfileId': 'mp_fast',
    });
    const onSwitch = vi.fn().mockResolvedValue(undefined);
    render(<ModelProfileSelector liveModeActive={false} onSwitch={onSwitch} />);

    await waitFor(() => {
      expect(screen.getByLabelText('Active model profile')).toHaveValue('mp_fast');
    });

    fireEvent.change(screen.getByLabelText('Active model profile'), {
      target: { value: 'mp_multi' },
    });

    await waitFor(() => {
      expect(onSwitch).toHaveBeenCalledTimes(1);
      expect(onSwitch.mock.calls[0][0].id).toBe('mp_multi');
    });
    await waitFor(() => {
      expect(bridge.values.get('notebook.activeModelProfileId')).toBe('mp_multi');
    });
  });

  it('AC8.3 AC3 — rejects switch while live mode is active and emits onRejected', async () => {
    installFakeBridge({
      'notebook.modelProfiles': SAMPLE_PROFILES,
      'notebook.activeModelProfileId': 'mp_fast',
    });
    const onSwitch = vi.fn().mockResolvedValue(undefined);
    const onRejected = vi.fn();
    render(<ModelProfileSelector liveModeActive onSwitch={onSwitch} onRejected={onRejected} />);

    await waitFor(() => {
      expect(screen.getByLabelText('Active model profile')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Active model profile'), {
      target: { value: 'mp_multi' },
    });

    expect(onSwitch).not.toHaveBeenCalled();
    expect(onRejected).toHaveBeenCalledWith('Stop live mode before switching the model');
  });

  it('emits onRejected when onSwitch throws (regression: do not swallow errors)', async () => {
    installFakeBridge({
      'notebook.modelProfiles': SAMPLE_PROFILES,
      'notebook.activeModelProfileId': 'mp_fast',
    });
    const onSwitch = vi.fn().mockRejectedValue(new Error('GPU OOM'));
    const onRejected = vi.fn();
    render(
      <ModelProfileSelector liveModeActive={false} onSwitch={onSwitch} onRejected={onRejected} />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Active model profile')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Active model profile'), {
      target: { value: 'mp_multi' },
    });

    await waitFor(() => {
      expect(onRejected).toHaveBeenCalledWith(expect.stringContaining('GPU OOM'));
    });
  });

  it('shows "Switching model…" spinner while onSwitch is in flight', async () => {
    installFakeBridge({
      'notebook.modelProfiles': SAMPLE_PROFILES,
      'notebook.activeModelProfileId': 'mp_fast',
    });
    let resolveSwitch: () => void = () => {};
    const onSwitch = vi.fn().mockReturnValue(
      new Promise<void>((res) => {
        resolveSwitch = res;
      }),
    );
    render(<ModelProfileSelector liveModeActive={false} onSwitch={onSwitch} />);

    await waitFor(() => {
      expect(screen.getByLabelText('Active model profile')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Active model profile'), {
      target: { value: 'mp_multi' },
    });

    await waitFor(() => {
      expect(screen.getByText('Switching model…')).toBeInTheDocument();
    });

    resolveSwitch();
    await waitFor(() => {
      expect(screen.queryByText('Switching model…')).not.toBeInTheDocument();
    });
  });
});
