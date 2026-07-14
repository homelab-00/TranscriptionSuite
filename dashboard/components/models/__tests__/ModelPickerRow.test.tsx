import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  capabilities: { translation: true, liveMode: false, diarization: true, languageCount: 25 },
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
  it('is collapsed by default, showing the name but not the description', () => {
    setup();

    expect(screen.getByText('Canary 1B V2')).toBeInTheDocument();
    expect(screen.queryByText(MODEL.description)).not.toBeInTheDocument();
  });

  it('reveals the full detail when expanded', async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole('button', { name: /details/i }));

    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
  });

  it('selects the model when the radio is clicked', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('radio', { name: /Canary 1B V2/ }));

    expect(props.onSelect).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the selected row as checked', () => {
    setup({ selected: true });

    expect(screen.getByRole('radio', { name: /Canary 1B V2/ })).toBeChecked();
  });

  it('does not allow selection while the server is running', async () => {
    const user = userEvent.setup();
    const props = setup({ disabled: true });

    await user.click(screen.getByRole('radio', { name: /Canary 1B V2/ }));

    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it('offers Download for an absent model', async () => {
    const user = userEvent.setup();
    const props = setup();

    await user.click(screen.getByRole('button', { name: /download/i }));

    expect(props.onDownload).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('offers Remove instead of Download once the model is cached', async () => {
    const user = userEvent.setup();
    const props = setup({ cached: true });

    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /remove/i }));

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
});
