/**
 * AiPromptsSection — Settings → AI prompt editors (GH-254).
 *
 * Presentational component: props in, callbacks out. What matters is that
 * edits propagate verbatim and that Reset emits the server-supplied default
 * rather than a hardcoded copy of the prompt text.
 */

import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { AiPromptsSection } from '../AiPromptsSection';

const DEFAULTS = {
  summaryDefault: 'Summarize this transcription concisely.',
  chatDefault: 'You are a helpful assistant.',
};

describe('AiPromptsSection', () => {
  it('renders the current prompt values', () => {
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt="Fasse auf Deutsch zusammen."
        chatPrompt="Answer in English."
        onSummaryPromptChange={vi.fn()}
        onChatPromptChange={vi.fn()}
        {...DEFAULTS}
      />,
    );

    expect((getByLabelText('AI summary prompt') as HTMLTextAreaElement).value).toBe(
      'Fasse auf Deutsch zusammen.',
    );
    expect((getByLabelText('AI chat prompt') as HTMLTextAreaElement).value).toBe(
      'Answer in English.',
    );
  });

  it('emits edits to the summary prompt', () => {
    const onSummaryPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt=""
        chatPrompt=""
        onSummaryPromptChange={onSummaryPromptChange}
        onChatPromptChange={vi.fn()}
        {...DEFAULTS}
      />,
    );

    fireEvent.change(getByLabelText('AI summary prompt'), {
      target: { value: 'Bullet points only.' },
    });

    expect(onSummaryPromptChange).toHaveBeenCalledWith('Bullet points only.');
  });

  it('emits edits to the chat prompt', () => {
    const onChatPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt=""
        chatPrompt=""
        onSummaryPromptChange={vi.fn()}
        onChatPromptChange={onChatPromptChange}
        {...DEFAULTS}
      />,
    );

    fireEvent.change(getByLabelText('AI chat prompt'), { target: { value: 'Be terse.' } });

    expect(onChatPromptChange).toHaveBeenCalledWith('Be terse.');
  });

  it('reset emits the server-supplied default, not a hardcoded copy', () => {
    const onSummaryPromptChange = vi.fn();
    const onChatPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt="Custom."
        chatPrompt="Custom."
        onSummaryPromptChange={onSummaryPromptChange}
        onChatPromptChange={onChatPromptChange}
        {...DEFAULTS}
      />,
    );

    fireEvent.click(getByLabelText('Reset AI summary prompt to default'));
    fireEvent.click(getByLabelText('Reset AI chat prompt to default'));

    expect(onSummaryPromptChange).toHaveBeenCalledWith(DEFAULTS.summaryDefault);
    expect(onChatPromptChange).toHaveBeenCalledWith(DEFAULTS.chatDefault);
  });
});
