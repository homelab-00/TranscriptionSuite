/**
 * AI prompt editors for Settings → AI (GH-254).
 *
 * Renders the *contents* of a Section; SettingsModal supplies the
 * <Section title="Prompts"> wrapper. Kept out of SettingsModal.tsx because
 * that file is already ~2450 lines and a render test of it would need
 * roughly twenty mocks — this one needs none.
 *
 * Both fields are PromptField instances, which is also what the title prompt
 * in the Automatic Title Generation section uses, so every prompt in the tab
 * shares one layout and one textarea style.
 */

import React from 'react';
import { PromptField } from './PromptField';

interface AiPromptsSectionProps {
  summaryPrompt: string;
  chatPrompt: string;
  summaryDefault: string;
  chatDefault: string;
  onSummaryPromptChange: (value: string) => void;
  onChatPromptChange: (value: string) => void;
}

export const AiPromptsSection: React.FC<AiPromptsSectionProps> = ({
  summaryPrompt,
  chatPrompt,
  summaryDefault,
  chatDefault,
  onSummaryPromptChange,
  onChatPromptChange,
}) => (
  <>
    <PromptField
      id="ai-summary-prompt"
      label="AI summary prompt"
      helpText="System prompt used when a recording is summarised — both the Generate button in a note and the automatic summary after transcription."
      value={summaryPrompt}
      defaultValue={summaryDefault}
      onChange={onSummaryPromptChange}
    />
    <PromptField
      id="ai-chat-prompt"
      label="AI chat prompt"
      helpText="System message that opens every conversation in the AI chat panel of a note."
      value={chatPrompt}
      defaultValue={chatDefault}
      onChange={onChatPromptChange}
    />
  </>
);
