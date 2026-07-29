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
    onMainModelSelectionChange: vi.fn(),
    onMainCustomModelChange: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<MainModelPicker {...props} />);
  return props;
}

function expand() {
  fireEvent.click(screen.getByRole('button', { name: /change model/i }));
}

describe('MainModelPicker', () => {
  it('starts collapsed, summarizing only the selected model', () => {
    setup();

    expect(screen.getByText(/Parakeet/)).toBeInTheDocument();
    expect(screen.queryByText(/Canary/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^select /i })).not.toBeInTheDocument();
  });

  it('expands to the full card list on click and collapses again', () => {
    setup();

    expand();
    expect(screen.getByText(/Canary/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /hide models/i }));
    expect(screen.queryByText(/Canary/)).not.toBeInTheDocument();
  });

  it('lists both models behind the merged NeMo family tile', () => {
    setup();
    expand();

    expect(screen.getAllByText(/Parakeet/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Canary/)).toBeInTheDocument();
  });

  it('does not leak models from other families', () => {
    setup();
    expand();

    expect(screen.queryByText(/Faster Whisper/)).not.toBeInTheDocument();
  });

  it('scopes the list to whichever family is selected', () => {
    setup({ selectedFamily: 'sensevoice', mainModelSelection: 'iic/SenseVoiceSmall' });
    expand();

    expect(screen.getAllByText(/SenseVoice/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Parakeet/)).not.toBeInTheDocument();
  });

  it('reports the model id when a card is selected', () => {
    const props = setup();
    expand();

    fireEvent.click(screen.getByRole('button', { name: /select canary/i }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the currently selected model with a Main badge', () => {
    setup();
    expand();

    // Parakeet is selected: badge in the summary and a pressed card.
    expect(screen.getAllByText('Main').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /select parakeet/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /select canary/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('switches to the custom option when the custom card is chosen', () => {
    const props = setup();
    expand();

    fireEvent.click(screen.getByRole('button', { name: /select custom/i }));

    expect(props.onMainModelSelectionChange).toHaveBeenCalledWith(MAIN_MODEL_CUSTOM_OPTION);
  });

  it('hides the free-text repo input while a registry model is selected', () => {
    setup();
    expand();

    expect(screen.queryByPlaceholderText('owner/model-name')).not.toBeInTheDocument();
  });

  it('shows the free-text repo input while the custom option is active', () => {
    setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION });
    expand();

    expect(screen.getByPlaceholderText('owner/model-name')).toBeInTheDocument();
  });

  it('summarizes a custom selection in the collapsed header', () => {
    setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION, mainCustomModel: 'me/my-model' });

    expect(screen.getByText('Custom: me/my-model')).toBeInTheDocument();
  });

  it('reports edits to the custom repo', () => {
    const props = setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION });
    expand();

    fireEvent.change(screen.getByPlaceholderText('owner/model-name'), {
      target: { value: 'me/my-model' },
    });

    expect(props.onMainCustomModelChange).toHaveBeenCalledWith('me/my-model');
  });

  it('locks every card against selection while the server is running', () => {
    const props = setup({ isRunning: true });
    expand();

    const cards = screen.getAllByRole('button', { name: /^select /i });
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      expect(card).toHaveAttribute('aria-disabled', 'true');
      fireEvent.click(card);
    }
    expect(props.onMainModelSelectionChange).not.toHaveBeenCalled();
  });

  it('reflects cached state per model', () => {
    setup({
      modelCacheStatus: { 'nvidia/canary-1b-v2': { exists: true, size: '4.1 GB' } },
    });
    expand();

    // Canary is cached, so it offers Remove. Parakeet is not — and there is no
    // Download action; missing models are fetched at server start.
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });

  it('renders nothing but the custom card when no family is selected', () => {
    setup({ selectedFamily: null });
    expand();

    expect(screen.getByRole('button', { name: /select custom/i })).toBeInTheDocument();
    expect(screen.queryByText(/Parakeet/)).not.toBeInTheDocument();
  });

  it('shows the current custom repo in the input', () => {
    setup({ mainModelSelection: MAIN_MODEL_CUSTOM_OPTION, mainCustomModel: 'me/my-model' });
    expand();

    expect(screen.getByDisplayValue('me/my-model')).toBeInTheDocument();
  });

  it('locks the custom repo input too while the server is running', () => {
    setup({
      mainModelSelection: MAIN_MODEL_CUSTOM_OPTION,
      mainCustomModel: 'me/my-model',
      isRunning: true,
    });
    expand();

    expect(screen.getByPlaceholderText('owner/model-name')).toBeDisabled();
  });
});
