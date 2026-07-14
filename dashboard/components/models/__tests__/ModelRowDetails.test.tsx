import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ModelRowDetails } from '../ModelRowDetails';
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

describe('ModelRowDetails', () => {
  it('shows the repo id, parameter count, language count and description', () => {
    render(<ModelRowDetails model={MODEL} cached={false} />);

    expect(screen.getByText('nvidia/canary-1b-v2')).toBeInTheDocument();
    expect(screen.getByText('1B params')).toBeInTheDocument();
    expect(screen.getByText('25 languages')).toBeInTheDocument();
    expect(screen.getByText(MODEL.description)).toBeInTheDocument();
  });

  it('renders only the capability badges the model actually has', () => {
    render(<ModelRowDetails model={MODEL} cached={false} />);

    expect(screen.getByText('Translation (between languages)')).toBeInTheDocument();
    expect(screen.getByText('Diarization')).toBeInTheDocument();
    expect(screen.queryByText('Live Mode')).not.toBeInTheDocument();
  });

  // ModelInfo has no size field, so a size can only ever be shown for a model
  // that is already cached.
  it('shows no size when the model is not cached', () => {
    render(<ModelRowDetails model={MODEL} cached={false} cacheSize="4.1 GB" />);

    expect(screen.queryByText(/Downloaded/)).not.toBeInTheDocument();
  });

  it('shows the on-disk size once the model is cached', () => {
    render(<ModelRowDetails model={MODEL} cached={true} cacheSize="4.1 GB" />);

    expect(screen.getByText('Downloaded 4.1 GB')).toBeInTheDocument();
  });
});
