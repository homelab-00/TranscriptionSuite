import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ModelPickerRow } from '../ModelPickerRow';
import type { ModelInfo } from '../../../src/services/modelRegistry';

const MODEL: ModelInfo = {
  id: 'nvidia/canary-1b-v2',
  displayName: 'Canary 1B V2',
  family: 'nemo',
  description: 'NVIDIA multitask ASR and translation model.',
  parameterCount: '1B',
  huggingfaceUrl: 'https://huggingface.co/nvidia/canary-1b-v2',
  capabilities: {
    translation: 'multilingual',
    liveMode: false,
    diarization: true,
    languageCount: 25,
  },
  roles: ['main'],
};

function setup(overrides: Partial<React.ComponentProps<typeof ModelPickerRow>> = {}) {
  const props = {
    model: MODEL,
    selected: false,
    cached: false,
    downloading: false,
    canManage: true,
    disabled: false,
    onSelect: vi.fn(),
    onDownload: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<ModelPickerRow {...props} />);
  return props;
}

describe('ModelPickerRow', () => {
  it('shows the full detail block on the card itself', () => {
    setup();

    expect(screen.getByText('Canary 1B V2')).toBeInTheDocument();
    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
  });

  it('selects the model via the Select button', () => {
    const props = setup();

    fireEvent.click(screen.getByRole('button', { name: /select canary/i }));

    expect(props.onSelect).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the selected card with a Main badge instead of a Select button', () => {
    setup({ selected: true });

    expect(screen.getByText('Main')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /select canary/i })).not.toBeInTheDocument();
  });

  it('does not allow selection while the server is running', () => {
    setup({ disabled: true });

    expect(screen.getByRole('button', { name: /select canary/i })).toBeDisabled();
  });

  it('offers Download for an absent model', () => {
    const props = setup();

    fireEvent.click(screen.getByRole('button', { name: /download/i }));

    expect(props.onDownload).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('offers Remove instead of Download once the model is cached', () => {
    const props = setup({ cached: true });

    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(props.onRemove).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('shows an in-flight state while downloading, with no action available', () => {
    setup({ downloading: true });

    expect(screen.getByText(/downloading/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^download$/i })).not.toBeInTheDocument();
  });

  // Cache operations are host-local on Metal and work with the server stopped,
  // so canManage is tracked separately from disabled.
  it('blocks download when cache management is unavailable', () => {
    setup({ canManage: false });

    expect(screen.getByRole('button', { name: /download/i })).toBeDisabled();
  });

  // The two locks are independent on purpose. Cache operations on Metal are
  // host-local and work with the server stopped, so a card that is locked for
  // selection must still be downloadable. Varying one flag at a time cannot
  // catch a regression that couples them.
  it('still allows download while selection is locked', () => {
    const props = setup({ disabled: true, canManage: true });

    expect(screen.getByRole('button', { name: /select canary/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /download/i }));

    expect(props.onDownload).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('still allows remove while selection is locked', () => {
    const props = setup({ disabled: true, canManage: true, cached: true });

    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(props.onRemove).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('links out to the model page on HuggingFace', () => {
    const openExternal = vi.fn();
    (window as any).electronAPI = { app: { openExternal } };
    setup();

    fireEvent.click(screen.getByTitle('View on HuggingFace'));

    expect(openExternal).toHaveBeenCalledWith('https://huggingface.co/nvidia/canary-1b-v2');
    delete (window as any).electronAPI;
  });
});
