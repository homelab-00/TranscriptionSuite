/**
 * AI prompt editors for Settings → AI (GH-254).
 *
 * Renders the *contents* of a Section; SettingsModal supplies the
 * <Section title="Prompts"> wrapper. Kept out of SettingsModal.tsx because
 * that file is already ~2450 lines and a render test of it would need
 * roughly twenty mocks — this one needs none.
 *
 * The default texts are supplied by the server (GET /api/llm/status) rather
 * than hardcoded here, so "Reset to default" can never drift from what the
 * backend actually falls back to.
 */

import React from 'react';
import { RotateCw } from 'lucide-react';
import { Button } from '../../ui/Button';

interface AiPromptsSectionProps {
  summaryPrompt: string;
  chatPrompt: string;
  summaryDefault: string;
  chatDefault: string;
  onSummaryPromptChange: (value: string) => void;
  onChatPromptChange: (value: string) => void;
}

const TEXTAREA_CLASS =
  'focus:border-accent-cyan/50 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none';

export const AiPromptsSection: React.FC<AiPromptsSectionProps> = ({
  summaryPrompt,
  chatPrompt,
  summaryDefault,
  chatDefault,
  onSummaryPromptChange,
  onChatPromptChange,
}) => (
  <>
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor="ai-summary-prompt" className="text-sm text-slate-200">
          AI summary prompt
        </label>
        <Button
          variant="secondary"
          size="sm"
          icon={<RotateCw size={14} />}
          aria-label="Reset AI summary prompt to default"
          onClick={() => onSummaryPromptChange(summaryDefault)}
        >
          Reset to default
        </Button>
      </div>
      <p className="mb-3 text-xs text-slate-400">
        System prompt used when a recording is summarised — both the Generate button in a note and
        the automatic summary after transcription.
      </p>
      <textarea
        id="ai-summary-prompt"
        aria-label="AI summary prompt"
        rows={4}
        value={summaryPrompt}
        onChange={(e) => onSummaryPromptChange(e.target.value)}
        placeholder={summaryDefault}
        className={TEXTAREA_CLASS}
      />
    </div>

    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor="ai-chat-prompt" className="text-sm text-slate-200">
          AI chat prompt
        </label>
        <Button
          variant="secondary"
          size="sm"
          icon={<RotateCw size={14} />}
          aria-label="Reset AI chat prompt to default"
          onClick={() => onChatPromptChange(chatDefault)}
        >
          Reset to default
        </Button>
      </div>
      <p className="mb-3 text-xs text-slate-400">
        System message that opens every conversation in a note's AI chat panel.
      </p>
      <textarea
        id="ai-chat-prompt"
        aria-label="AI chat prompt"
        rows={4}
        value={chatPrompt}
        onChange={(e) => onChatPromptChange(e.target.value)}
        placeholder={chatDefault}
        className={TEXTAREA_CLASS}
      />
    </div>
  </>
);
