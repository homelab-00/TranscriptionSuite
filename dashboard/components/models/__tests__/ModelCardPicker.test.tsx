import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ModelCardPicker } from '../ModelCardPicker';
import type { ModelInfo } from '../../../src/services/modelRegistry';

const MODELS: ModelInfo[] = [
  {
    id: 'Systran/faster-whisper-medium',
    displayName: 'Faster Whisper Medium',
    family: 'whisper',
    description: 'Good balance of accuracy and speed.',
    parameterCount: '769M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-medium',
    capabilities: {
      translation: 'toEnglish',
      liveMode: true,
      diarization: true,
      languageCount: 99,
    },
    roles: ['main', 'live'],
  },
  {
    id: 'Systran/faster-whisper-small',
    displayName: 'Faster Whisper Small',
    family: 'whisper',
    description: 'Lightweight model suitable for real-time use.',
    parameterCount: '244M',
    huggingfaceUrl: 'https://huggingface.co/Systran/faster-whisper-small',
    capabilities: {
      translation: 'toEnglish',
      liveMode: true,
      diarization: true,
      languageCount: 99,
    },
    roles: ['main', 'live'],
  },
];

function setup(overrides: Partial<React.ComponentProps<typeof ModelCardPicker>> = {}) {
  const props = {
    models: MODELS,
    selection: 'Systran/faster-whisper-medium',
    badgeLabel: 'Live',
    isRunning: false,
    canManage: true,
    modelCacheStatus: {},
    downloadingIds: new Set<string>(),
    onSelectionChange: vi.fn(),
    onDownload: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<ModelCardPicker {...props} />);
  return props;
}

function expand() {
  fireEvent.click(screen.getByRole('button', { name: /change model/i }));
}

describe('ModelCardPicker', () => {
  it('is collapsed by default, showing only the selection summary', () => {
    setup();

    expect(screen.getByRole('button', { name: /change model/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(screen.getByText('Faster Whisper Medium')).toBeInTheDocument();
    expect(screen.queryByText('Faster Whisper Small')).not.toBeInTheDocument();
  });

  it('reveals the full card list when toggled', () => {
    setup();
    expand();

    expect(screen.getByRole('button', { name: /hide models/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByText('Faster Whisper Small')).toBeInTheDocument();
  });

  it('stamps the configured badge label on summary and selected card', () => {
    setup();
    expand();

    expect(screen.getAllByText('Live').length).toBe(2);
    expect(screen.queryByText('Main')).not.toBeInTheDocument();
  });

  it('omits the custom card when no custom option is configured', () => {
    setup();
    expand();

    expect(screen.queryByText('Custom (HuggingFace repo)')).not.toBeInTheDocument();
  });

  it('renders the custom card when a custom option is configured', () => {
    setup({
      custom: { value: 'Custom (HuggingFace repo)', text: '', onTextChange: vi.fn() },
    });
    expand();

    expect(screen.getByRole('button', { name: /select custom/i })).toBeInTheDocument();
  });

  it('falls back to a placeholder summary for an unknown selection', () => {
    setup({ selection: 'Default (Loading...)' });

    expect(screen.getByText('Select a model')).toBeInTheDocument();
    expect(screen.queryByText('Live')).not.toBeInTheDocument();
  });

  it('reports selection from a card', () => {
    const props = setup();
    expand();

    fireEvent.click(screen.getByRole('button', { name: /select faster whisper small/i }));

    expect(props.onSelectionChange).toHaveBeenCalledWith('Systran/faster-whisper-small');
  });

  it('still allows browsing the list while the server is running', () => {
    setup({ isRunning: true });
    expand();

    expect(screen.getByText('Faster Whisper Small')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /select faster whisper small/i })).toBeDisabled();
  });
});
