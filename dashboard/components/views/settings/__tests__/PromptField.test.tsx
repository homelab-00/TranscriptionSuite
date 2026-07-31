/**
 * PromptField — the shared prompt editor used by every prompt in Settings → AI
 * (GH-254 follow-up).
 *
 * Extracted so the summary, chat and title prompts are identical by
 * construction: same label row, same Reset affordance, same textarea styling
 * including the opt-in custom scrollbar. The title prompt previously had none
 * of those and showed a native browser scrollbar.
 */

import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { PromptField } from '../PromptField';

describe('PromptField', () => {
  it('renders the label, helper text and current value', () => {
    const { getByLabelText, getByText } = render(
      <PromptField
        id="test-prompt"
        label="Test prompt"
        helpText="What this prompt does."
        value="Current value."
        defaultValue="The default."
        onChange={vi.fn()}
      />,
    );

    expect((getByLabelText('Test prompt') as HTMLTextAreaElement).value).toBe('Current value.');
    expect(getByText('What this prompt does.')).toBeTruthy();
  });

  it('emits edits verbatim', () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(
      <PromptField
        id="test-prompt"
        label="Test prompt"
        helpText="Help."
        value=""
        defaultValue="The default."
        onChange={onChange}
      />,
    );

    fireEvent.change(getByLabelText('Test prompt'), { target: { value: 'Typed text.' } });

    expect(onChange).toHaveBeenCalledWith('Typed text.');
  });

  it('reset emits the supplied default', () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(
      <PromptField
        id="test-prompt"
        label="Test prompt"
        helpText="Help."
        value="Custom."
        defaultValue="The default."
        onChange={onChange}
      />,
    );

    fireEvent.click(getByLabelText('Reset Test prompt to default'));

    expect(onChange).toHaveBeenCalledWith('The default.');
  });

  it('opts into the custom scrollbar so long prompts do not show a native one', () => {
    const { getByLabelText } = render(
      <PromptField
        id="test-prompt"
        label="Test prompt"
        helpText="Help."
        value="Long value."
        defaultValue="The default."
        onChange={vi.fn()}
      />,
    );

    expect(getByLabelText('Test prompt').className).toContain('custom-scrollbar');
  });
});
