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
    canManage: true,
    disabled: false,
    onSelect: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<ModelPickerRow {...props} />);
  return props;
}

const card = () => screen.getByRole('button', { name: /select canary/i });

describe('ModelPickerRow', () => {
  it('shows the full detail block on the card itself', () => {
    setup();

    expect(screen.getByText('Canary 1B V2')).toBeInTheDocument();
    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
  });

  it('selects the model by clicking anywhere on the card', () => {
    const props = setup();

    fireEvent.click(card());

    expect(props.onSelect).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('selects the model via the keyboard', () => {
    const props = setup();

    fireEvent.keyDown(card(), { key: 'Enter' });

    expect(props.onSelect).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('marks the selected card with a badge and pressed state', () => {
    setup({ selected: true });

    expect(screen.getByText('Main')).toBeInTheDocument();
    expect(card()).toHaveAttribute('aria-pressed', 'true');
  });

  it('does not allow selection while the server is running', () => {
    const props = setup({ disabled: true });

    expect(card()).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(card());

    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it('never offers a Download action — downloads happen at server start', () => {
    setup();

    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });

  it('offers Remove once the model is cached', () => {
    const props = setup({ cached: true });

    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(props.onRemove).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('hides Remove for a model that is not cached', () => {
    setup();

    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
  });

  // The card itself is the select control, so the nested Remove button must
  // not also select the model it removes.
  it('does not select the model when Remove is clicked', () => {
    const props = setup({ cached: true });

    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(props.onSelect).not.toHaveBeenCalled();
  });

  // Cache operations are host-local on Metal and work with the server stopped,
  // so canManage is tracked separately from disabled.
  it('blocks remove when cache management is unavailable', () => {
    setup({ cached: true, canManage: false });

    expect(screen.getByRole('button', { name: /remove/i })).toBeDisabled();
  });

  // The two locks are independent on purpose. Cache operations on Metal are
  // host-local and work with the server stopped, so a card that is locked for
  // selection must still allow removal.
  it('still allows remove while selection is locked', () => {
    const props = setup({ disabled: true, canManage: true, cached: true });

    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    expect(props.onRemove).toHaveBeenCalledWith('nvidia/canary-1b-v2');
  });

  it('links out to the model page on HuggingFace without selecting', () => {
    const openExternal = vi.fn();
    (window as any).electronAPI = { app: { openExternal } };
    const props = setup();

    fireEvent.click(screen.getByTitle('View on HuggingFace'));

    expect(openExternal).toHaveBeenCalledWith('https://huggingface.co/nvidia/canary-1b-v2');
    expect(props.onSelect).not.toHaveBeenCalled();
    delete (window as any).electronAPI;
  });
});
