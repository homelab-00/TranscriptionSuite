import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MainModelPicker } from '../MainModelPicker';
import { MAIN_MODEL_CUSTOM_OPTION } from '../../../../src/services/modelSelection';

function setup(overrides: Partial<React.ComponentProps<typeof MainModelPicker>> = {}) {
  const props = {
    selectedFamily: 'nemo' as const,
    mainModelSelection: 'nvidia/parakeet-tdt-0.6b-v3',
    mainCustomModel: '',
    isRunning: false,
    canManage: true,
    modelCacheStatus: {},
    downloadingIds: new Set<string>(),
    onMainModelSelectionChange: vi.fn(),
    onMainCustomModelChange: vi.fn(),
    onDownload: vi.fn(),
    onRemove: vi.fn(),
    onOpenManager: vi.fn(),
    ...overrides,
  };
  render(<MainModelPicker {...props} />);
  return props;
}

describe('MainModelPicker', () => {
  it('lists both models behind the merged NeMo family tile', () => {
    setup();

    expect(screen.getByRole('radio', { name: /Parakeet/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Canary/ })).toBeInTheDocument();
  });

  it('does not leak models from other families', () => {
    setup();

    expect(screen.queryByRole('radio', { name: /Whisper/ })).not.toBeInTheDocument();
  });

  it('scopes the list to whichever family is selected', () => {
    setup({ selectedFamily: 'sensevoice', mainModelSelection: 'iic/SenseVoiceSmall' });

    expect(screen.getByRole('radio', { name: /SenseVoice/ })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /Parakeet/ })).not.toBeInTheDocument();
  });

  it('reports the model id when a row is selected', () => {
    const props = setup();

    fireEvent.click(screen.getByRole('radio', { name: /Canary/ }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the currently selected model as checked', () => {
    setup();

    expect(screen.getByRole('radio', { name: /Parakeet/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Canary/ })).not.toBeChecked();
  });

  it('switches to the custom option when the custom row is chosen', () => {
    const props = setup();

    fireEvent.click(screen.getByRole('radio', { name: /custom/i }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith(MAIN_MODEL_CUSTOM_OPTION);
  });

  it('shows the free-text repo input only while the custom option is active', () => {
    setup();
    expect(screen.queryByPlaceholderText('owner/model-name')).not.toBeInTheDocument();

    setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION });
    expect(screen.getByPlaceholderText('owner/model-name')).toBeInTheDocument();
  });

  it('reports edits to the custom repo', () => {
    const props = setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION });

    fireEvent.change(screen.getByPlaceholderText('owner/model-name'), {
      target: { value: 'me/my-model' },
    });

    expect(props.onMainCustomModelChange).toHaveBeenCalledWith('me/my-model');
  });

  it('locks every row while the server is running', () => {
    setup({ isRunning: true });

    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).toBeDisabled();
    }
  });

  it('reflects cached state per model', () => {
    setup({
      modelCacheStatus: { 'nvidia/canary-1b-v2': { exists: true, size: '4.1 GB' } },
    });

    // Canary is cached, so it offers Remove. Parakeet is not, so it offers Download.
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download/i })).toBeInTheDocument();
  });

  it('opens the full manager on request', () => {
    const props = setup();

    fireEvent.click(screen.getByRole('button', { name: /manage all models/i }));

    expect(props.onOpenManager).toHaveBeenCalled();
  });

  it('renders nothing but the custom row when no family is selected', () => {
    setup({ selectedFamily: null });

    expect(screen.getByRole('radio', { name: /custom/i })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /Parakeet/ })).not.toBeInTheDocument();
  });
});
