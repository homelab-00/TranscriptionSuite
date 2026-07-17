import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { HfTokenExplainer, HF_TERMS_URL, HF_TOKENS_URL } from '../ui/HfTokenExplainer';

describe('HfTokenExplainer (GH-208)', () => {
  it('explains the why, read-only sufficiency, local inference, and token-free alternatives', () => {
    render(<HfTokenExplainer onOpenLink={vi.fn()} />);
    expect(screen.getByText(/gated pyannote model/i)).toBeInTheDocument();
    expect(screen.getAllByText(/read.?only/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/runs entirely locally/i)).toBeInTheDocument();
    expect(screen.getByText(/vibevoice/i)).toBeInTheDocument();
    expect(screen.getByText(/sensevoice/i)).toBeInTheDocument();
  });

  it('links to both the model terms page and the token creation page', () => {
    const onOpenLink = vi.fn();
    render(<HfTokenExplainer onOpenLink={onOpenLink} />);
    fireEvent.click(screen.getByRole('button', { name: /accept the model terms/i }));
    expect(onOpenLink).toHaveBeenCalledWith(HF_TERMS_URL);
    fireEvent.click(screen.getByRole('button', { name: /create a read-only token/i }));
    expect(onOpenLink).toHaveBeenCalledWith(HF_TOKENS_URL);
  });
});
