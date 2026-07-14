import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// headlessui — same mock convention as ServerView.test.tsx: render-prop
// children are invoked with neutral defaults so option text lands in the DOM.
vi.mock('@headlessui/react', () => {
  const renderChildren = (
    children: React.ReactNode | ((args: any) => React.ReactNode),
    args: Record<string, unknown> = {},
  ): React.ReactNode =>
    typeof children === 'function' ? (children as (a: any) => React.ReactNode)(args) : children;
  const passthrough = ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, renderChildren(children));
  return {
    Listbox: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement('div', { 'data-value': value }, renderChildren(children, { open: true })),
    ListboxButton: ({ children }: { children: React.ReactNode }) =>
      React.createElement(
        'button',
        { type: 'button' },
        renderChildren(children, { open: true, focus: false, hover: false }),
      ),
    ListboxOptions: passthrough,
    ListboxOption: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement(
        'div',
        { 'data-value': value },
        renderChildren(children, { selected: false, focus: false, active: false }),
      ),
  };
});

import { CustomSelect } from '../ui/CustomSelect';

describe('CustomSelect option labels and descriptions (GH-213)', () => {
  it('renders optionLabel and optionDescription when provided, raw value otherwise', async () => {
    render(
      <CustomSelect
        value="Systran/faster-distil-whisper-small.en"
        onChange={() => {}}
        options={['Systran/faster-distil-whisper-small.en', 'None (Disabled)']}
        optionLabel={{
          'Systran/faster-distil-whisper-small.en': 'Faster Distil Whisper Small (English)',
        }}
        optionDescription={{
          'Systran/faster-distil-whisper-small.en': 'Systran/faster-distil-whisper-small.en',
        }}
        optionMeta={{
          'Systran/faster-distil-whisper-small.en': { badge: 'Downloaded 486 MB' },
        }}
      />,
    );
    fireEvent.click(screen.getByRole('button'));
    // label shows on both the closed button (selected value) and the option row
    const labels = await screen.findAllByText('Faster Distil Whisper Small (English)');
    expect(labels.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Downloaded 486 MB')).toBeInTheDocument();
    // sentinel falls back to raw string
    expect(screen.getByText('None (Disabled)')).toBeInTheDocument();
  });

  it('renders the label instead of the raw value on the closed button', () => {
    render(
      <CustomSelect
        value="a/model-big"
        onChange={() => {}}
        options={['a/model-big']}
        optionLabel={{ 'a/model-big': 'Big Model' }}
      />,
    );
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Big Model');
    expect(button.textContent).not.toContain('a/model-big');
  });

  it('omits the description line when it equals the shown label', () => {
    render(
      <CustomSelect
        value="plain"
        onChange={() => {}}
        options={['plain']}
        optionDescription={{ plain: 'plain' }}
      />,
    );
    // exactly one occurrence: the option row's primary line (plus the button)
    const matches = screen.getAllByText('plain');
    // button text + single option line, but never a duplicated description line
    expect(matches.length).toBeLessThanOrEqual(2);
  });
});
