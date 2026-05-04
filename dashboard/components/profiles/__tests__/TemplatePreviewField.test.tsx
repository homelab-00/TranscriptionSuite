/**
 * TemplatePreviewField tests (Issue #104, Story 3.3).
 *
 * Covers:
 *   - AC1: preview renders the rendered filename inline
 *   - AC2: synchronous render — assert preview updates on each keystroke
 *   - AC3: invalid template surfaces inline + onValidityChange notifies
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TemplatePreviewField } from '../TemplatePreviewField';

describe('TemplatePreviewField — AC3.3.AC1 inline preview', () => {
  it('renders preview against the fixed sample recording', () => {
    render(<TemplatePreviewField template="{date} - {title}.txt" onTemplateChange={vi.fn()} />);
    // Preview format: "Preview: 2026-05-08 - Sample title.txt"
    expect(screen.getByText(/2026-05-08 - Sample title\.txt/)).toBeInTheDocument();
  });

  it('renders model placeholder against the sample model id', () => {
    render(<TemplatePreviewField template="{title} - {model}.txt" onTemplateChange={vi.fn()} />);
    expect(screen.getByText(/Sample title - parakeet-tdt-0\.6b-v2\.txt/)).toBeInTheDocument();
  });
});

describe('TemplatePreviewField — AC3.3.AC2 synchronous updates', () => {
  it('updates preview on every keystroke (no debounce)', () => {
    let template = '{title}.txt';
    const handle = vi.fn((next: string) => {
      template = next;
    });
    const { rerender } = render(
      <TemplatePreviewField template={template} onTemplateChange={handle} />,
    );
    expect(screen.getByText(/Sample title\.txt/)).toBeInTheDocument();

    rerender(<TemplatePreviewField template="{date}-{title}.txt" onTemplateChange={handle} />);
    expect(screen.getByText(/2026-05-08-Sample title\.txt/)).toBeInTheDocument();
  });

  it('forwards input changes via onTemplateChange', () => {
    const onTemplateChange = vi.fn();
    render(<TemplatePreviewField template="{title}.txt" onTemplateChange={onTemplateChange} />);
    fireEvent.change(screen.getByLabelText('Filename template'), {
      target: { value: '{date}.md' },
    });
    expect(onTemplateChange).toHaveBeenCalledWith('{date}.md');
  });
});

describe('TemplatePreviewField — AC3.3.AC3 invalid template surfacing', () => {
  it('shows inline error for unknown placeholder', () => {
    render(<TemplatePreviewField template="{date} {nonexistent}.txt" onTemplateChange={vi.fn()} />);
    expect(screen.getByText(/Invalid:/)).toBeInTheDocument();
    expect(screen.getByText(/\{nonexistent\}/)).toBeInTheDocument();
  });

  it('lists multiple unknown placeholders', () => {
    render(<TemplatePreviewField template="{foo} {bar}.txt" onTemplateChange={vi.fn()} />);
    expect(screen.getByText(/\{foo\}, \{bar\}/)).toBeInTheDocument();
  });

  it('calls onValidityChange(false) when template is invalid', () => {
    const onValidityChange = vi.fn();
    render(
      <TemplatePreviewField
        template="{nope}.txt"
        onTemplateChange={vi.fn()}
        onValidityChange={onValidityChange}
      />,
    );
    expect(onValidityChange).toHaveBeenCalledWith(false);
  });

  it('calls onValidityChange(true) when template is valid', () => {
    const onValidityChange = vi.fn();
    render(
      <TemplatePreviewField
        template="{date}.txt"
        onTemplateChange={vi.fn()}
        onValidityChange={onValidityChange}
      />,
    );
    expect(onValidityChange).toHaveBeenLastCalledWith(true);
  });

  it('input has aria-invalid when template is invalid', () => {
    render(<TemplatePreviewField template="{nope}.txt" onTemplateChange={vi.fn()} />);
    expect(screen.getByLabelText('Filename template')).toHaveAttribute('aria-invalid', 'true');
  });
});

describe('TemplatePreviewField — Story 3.6 sticky-OK notice', () => {
  it('does not render notice by default', () => {
    render(<TemplatePreviewField template="{date}.txt" onTemplateChange={vi.fn()} />);
    expect(screen.queryByText(/applies to future transcriptions/)).not.toBeInTheDocument();
  });

  it('renders notice when showForwardOnlyNotice=true', () => {
    render(
      <TemplatePreviewField
        template="{date}.txt"
        onTemplateChange={vi.fn()}
        showForwardOnlyNotice
        onAckForwardOnly={vi.fn()}
      />,
    );
    expect(screen.getByText(/applies to future transcriptions/)).toBeInTheDocument();
  });

  it('OK button calls onAckForwardOnly', () => {
    const onAck = vi.fn();
    render(
      <TemplatePreviewField
        template="{date}.txt"
        onTemplateChange={vi.fn()}
        showForwardOnlyNotice
        onAckForwardOnly={onAck}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    expect(onAck).toHaveBeenCalled();
  });
});
