/**
 * LiveTranscriptView — the live-mode transcript area, shared by both layout
 * branches in SessionView (the popped-out window and the inline GlassCard).
 *
 * Three states:
 *   - active capture (isLive)            → streaming sentences + partial, read-only
 *   - stopped with captured content      → editable FindReplaceTextEditor
 *   - stopped/off with no content        → idle placeholder
 *
 * Editing is client-only (drives the Copy button); nothing is persisted.
 */

import { type RefObject } from 'react';
import { Loader2, Activity, Radio } from 'lucide-react';
import type { LiveModeState } from '../../src/hooks/useLiveMode';
import { FindReplaceTextEditor } from '../editor/FindReplaceTextEditor';

interface LiveTranscriptViewProps {
  live: LiveModeState;
  isLive: boolean;
  hideTimestamps: boolean;
  serverRunning: boolean;
  isRemoteMode: boolean;
  serverReady: boolean;
  liveModelDisabled: boolean;
  liveModeWhisperOnlyCompatible: boolean;
  liveModeUnsupportedMessage: string;
  /** Auto-scroll target for the streaming view. */
  transcriptRef: RefObject<HTMLDivElement | null>;
  /** Client-only edited text (seeded from live.getText() once stopped). */
  editedLiveText: string;
  onEditedLiveChange: (next: string) => void;
}

const AREA_CLASS =
  'custom-scrollbar selectable-text relative min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300 shadow-inner';

export function LiveTranscriptView({
  live,
  isLive,
  hideTimestamps,
  serverRunning,
  isRemoteMode,
  serverReady,
  liveModelDisabled,
  liveModeWhisperOnlyCompatible,
  liveModeUnsupportedMessage,
  transcriptRef,
  editedLiveText,
  onEditedLiveChange,
}: LiveTranscriptViewProps) {
  // Editable only once capture has stopped and there is captured content.
  const hasCapturedContent = live.sentences.length > 0;
  if (!isLive && hasCapturedContent) {
    return (
      <FindReplaceTextEditor
        value={editedLiveText}
        onChange={onEditedLiveChange}
        autoGrow={false}
        ariaLabel="Live transcript"
        className="selectable-text relative min-h-0 flex-1 rounded-xl border border-white/5 bg-black/20 p-4 shadow-inner"
        textClassName="custom-scrollbar overflow-y-auto font-mono text-sm leading-relaxed text-slate-300"
      />
    );
  }

  return (
    <div ref={transcriptRef} className={AREA_CLASS}>
      {(serverRunning || isRemoteMode) && serverReady && liveModelDisabled && (
        <div className="mb-3 text-xs text-amber-300">Live model not selected.</div>
      )}
      {!liveModelDisabled && !liveModeWhisperOnlyCompatible && (
        <div className="mb-3 text-xs text-red-400">{liveModeUnsupportedMessage}</div>
      )}
      {isLive || live.sentences.length > 0 || live.partial ? (
        <>
          {live.statusMessage && (
            <div className="text-accent-cyan mb-3 flex animate-pulse items-center gap-2">
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">{live.statusMessage}</span>
            </div>
          )}
          {live.sentences.map((s, i) => (
            <div key={i} className="mb-2">
              {!hideTimestamps && (
                <span className="mr-2 text-slate-500 select-none">
                  {new Date(s.timestamp).toLocaleTimeString('en-US', { hour12: false })}
                </span>
              )}
              <span>{s.text}</span>
            </div>
          ))}
          {live.partial && (
            <div className="mb-2 opacity-60">
              {!hideTimestamps && (
                <span className="mr-2 text-slate-500 select-none">
                  {new Date().toLocaleTimeString('en-US', { hour12: false })}
                </span>
              )}
              <span className="italic">{live.partial}</span>
              <span className="bg-accent-cyan ml-0.5 inline-block h-4 w-1.5 animate-pulse align-text-bottom"></span>
            </div>
          )}
          {live.sentences.length === 0 && !live.partial && !live.statusMessage && (
            <div className="absolute inset-4 flex flex-col items-center justify-center space-y-3 text-slate-600 opacity-60 select-none">
              <Activity size={32} strokeWidth={1} className="animate-pulse" />
              <p>Listening... speak to see transcription.</p>
            </div>
          )}
          {live.error && <div className="mt-2 text-xs text-red-400">{live.error}</div>}
        </>
      ) : (
        <div className="absolute inset-4 flex items-center justify-center">
          <div className="flex flex-col items-center space-y-3 text-center text-slate-600 opacity-60 select-none">
            <Radio size={48} strokeWidth={1} />
            <p>Live mode is off. Toggle the switch to start.</p>
          </div>
        </div>
      )}
    </div>
  );
}
