import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  X,
  Play,
  Pause,
  Rewind,
  FastForward,
  Sparkles,
  MessageSquare,
  Clock,
  FileText,
  Bot,
  User,
  Send,
  Trash2,
  Edit2,
  Share,
  Loader2,
  Pencil,
  Check,
  XCircle,
  StopCircle,
  Plus,
  ChevronDown,
  RotateCw,
  Copy,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { AudioVisualizer } from '../AudioVisualizer';
import { useRecording } from '../../src/hooks/useRecording';
import { apiClient } from '../../src/api/client';
import { toast } from 'sonner';
import { useConfirm } from '../../src/hooks/useConfirm';
import { useWordHighlighter } from '../../src/hooks/useWordHighlighter';
import { getConfig } from '../../src/config/store';
import type { ChatMessage, Conversation, LLMModel } from '../../src/api/types';

/** Local type for chat message display (simpler than API's ChatMessage) */
interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  /** DB message ID, present for persisted messages — used for truncation. */
  id?: number;
}

interface AudioNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRecordingMutated?: () => void;
  note: {
    title: string;
    date?: string;
    duration: string;
    tag?: string;
    recordingId?: number;
  } | null;
}

interface ChatSession {
  id: number;
  title: string;
  type: 'summary' | 'chat';
  timestamp: string;
  updatedAt: string;
  model?: string | null;
}

interface ParsedLlmSegment {
  type: 'answer' | 'think';
  content: string;
  streaming?: boolean;
}

/** Format seconds to MM:SS display */
function formatRecSecs(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

/** Format a conversation timestamp for compact sidebar display */
function formatSessionTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function inferSessionType(title: string): 'summary' | 'chat' {
  return title.toLowerCase().includes('summary') ? 'summary' : 'chat';
}

function toChatSession(conversation: Conversation): ChatSession {
  return {
    id: conversation.id,
    title: conversation.title,
    type: inferSessionType(conversation.title),
    timestamp: formatSessionTime(conversation.updated_at),
    updatedAt: conversation.updated_at,
    model: conversation.model,
  };
}

function sortChatSessions(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
}

function toDisplayMessages(messages: ChatMessage[] | undefined): DisplayMessage[] {
  if (!messages) return [];
  return messages
    .filter(
      (m): m is ChatMessage & { role: DisplayMessage['role'] } =>
        m.role === 'user' || m.role === 'assistant',
    )
    .map((m) => ({ role: m.role, content: m.content, id: m.id }));
}

function parseLlmResponseSegments(rawText: string): ParsedLlmSegment[] {
  if (!rawText) return [];

  const segments: ParsedLlmSegment[] = [];
  const lower = rawText.toLowerCase();
  const openTag = '<think>';
  const closeTag = '</think>';
  let cursor = 0;

  while (cursor < rawText.length) {
    const openIndex = lower.indexOf(openTag, cursor);
    if (openIndex === -1) {
      const answerTail = rawText.slice(cursor);
      if (answerTail) segments.push({ type: 'answer', content: answerTail });
      break;
    }

    if (openIndex > cursor) {
      const answerChunk = rawText.slice(cursor, openIndex);
      if (answerChunk) segments.push({ type: 'answer', content: answerChunk });
    }

    const thinkStart = openIndex + openTag.length;
    const closeIndex = lower.indexOf(closeTag, thinkStart);
    if (closeIndex === -1) {
      segments.push({
        type: 'think',
        content: rawText.slice(thinkStart),
        streaming: true,
      });
      break;
    }

    segments.push({
      type: 'think',
      content: rawText.slice(thinkStart, closeIndex),
    });
    cursor = closeIndex + closeTag.length;
  }

  return segments.reduce<ParsedLlmSegment[]>((acc, segment) => {
    if (!segment.content && segment.type === 'answer') return acc;
    const previous = acc[acc.length - 1];
    if (previous && previous.type === segment.type && !previous.streaming && !segment.streaming) {
      previous.content += segment.content;
      return acc;
    }
    acc.push(segment);
    return acc;
  }, []);
}

const SUMMARY_MARKDOWN_COMPONENTS = {
  h1: ({ children }: any) => (
    <h1 className="mt-3 mb-2 text-xl font-semibold tracking-tight text-white">{children}</h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="mt-3 mb-2 text-xl font-semibold tracking-tight text-white">{children}</h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="mt-3 mb-2 text-xl font-semibold tracking-tight text-white">{children}</h3>
  ),
  p: ({ children }: any) => (
    <p className="text-lg leading-relaxed whitespace-pre-wrap text-slate-200">{children}</p>
  ),
  strong: ({ children }: any) => <strong className="font-bold text-white">{children}</strong>,
  em: ({ children }: any) => <em className="text-slate-200 italic">{children}</em>,
  code: ({ inline, children }: any) =>
    inline ? (
      <code className="text-accent-cyan rounded bg-black/30 px-1 py-0.5 font-mono text-xs">
        {children}
      </code>
    ) : (
      <code className="selectable-text rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-sm text-slate-200">
        {children}
      </code>
    ),
  pre: ({ children }: any) => <pre className="my-2 overflow-x-auto">{children}</pre>,
  ul: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  ol: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  li: ({ children }: any) => (
    <div className="text-lg leading-relaxed text-slate-200">• {children}</div>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="my-2 rounded border border-white/10 bg-black/20 px-3 py-2 text-slate-400">
      {children}
    </blockquote>
  ),
  a: ({ children, href }: any) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-accent-cyan hover:text-cyan-300 hover:underline"
    >
      {children}
    </a>
  ),
};

const CHAT_MARKDOWN_COMPONENTS = {
  h1: ({ children }: any) => (
    <h1 className="mt-3 mb-2 text-base font-semibold text-white">{children}</h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="mt-3 mb-2 text-base font-semibold text-white">{children}</h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="mt-3 mb-2 text-base font-semibold text-white">{children}</h3>
  ),
  p: ({ children }: any) => (
    <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-300">{children}</p>
  ),
  strong: ({ children }: any) => <strong className="font-bold text-white">{children}</strong>,
  em: ({ children }: any) => <em className="text-slate-200 italic">{children}</em>,
  code: ({ inline, children }: any) =>
    inline ? (
      <code className="text-accent-cyan rounded bg-black/30 px-1 py-0.5 font-mono text-xs">
        {children}
      </code>
    ) : (
      <code className="selectable-text rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs text-slate-200">
        {children}
      </code>
    ),
  pre: ({ children }: any) => <pre className="my-2 overflow-x-auto">{children}</pre>,
  ul: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  ol: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  li: ({ children }: any) => (
    <div className="text-sm leading-relaxed text-slate-300">• {children}</div>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="my-2 rounded border border-white/10 bg-black/20 px-3 py-2 text-slate-400">
      {children}
    </blockquote>
  ),
  a: ({ children, href }: any) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-accent-cyan hover:text-cyan-300 hover:underline"
    >
      {children}
    </a>
  ),
};

const THINK_MARKDOWN_COMPONENTS = {
  h1: ({ children }: any) => (
    <h1 className="mt-3 mb-2 text-sm font-semibold text-white">{children}</h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="mt-3 mb-2 text-sm font-semibold text-white">{children}</h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="mt-3 mb-2 text-sm font-semibold text-white">{children}</h3>
  ),
  p: ({ children }: any) => (
    <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-300">{children}</p>
  ),
  strong: ({ children }: any) => <strong className="font-bold text-white">{children}</strong>,
  em: ({ children }: any) => <em className="text-slate-200 italic">{children}</em>,
  code: ({ inline, children }: any) =>
    inline ? (
      <code className="text-accent-cyan rounded bg-black/30 px-1 py-0.5 font-mono text-xs">
        {children}
      </code>
    ) : (
      <code className="selectable-text rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs text-slate-200">
        {children}
      </code>
    ),
  pre: ({ children }: any) => <pre className="my-2 overflow-x-auto">{children}</pre>,
  ul: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  ol: ({ children }: any) => <div className="space-y-1 pl-4">{children}</div>,
  li: ({ children }: any) => (
    <div className="text-sm leading-relaxed text-slate-300">• {children}</div>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="my-2 rounded border border-white/10 bg-black/20 px-3 py-2 text-slate-400">
      {children}
    </blockquote>
  ),
  a: ({ children, href }: any) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-accent-cyan hover:text-cyan-300 hover:underline"
    >
      {children}
    </a>
  ),
};

function renderMarkdownBlock(content: string, tone: 'summary' | 'chat' | 'think'): React.ReactNode {
  const markdownComponents =
    tone === 'summary'
      ? SUMMARY_MARKDOWN_COMPONENTS
      : tone === 'chat'
        ? CHAT_MARKDOWN_COMPONENTS
        : THINK_MARKDOWN_COMPONENTS;

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {content}
    </ReactMarkdown>
  );
}

function renderLlmResponseContent({
  content,
  tone,
  showStreamingCursor = false,
  onAnswerClick,
}: {
  content: string;
  tone: 'summary' | 'chat';
  showStreamingCursor?: boolean;
  onAnswerClick?: () => void;
}): React.ReactNode {
  const segments = parseLlmResponseSegments(content);
  if (!content && !showStreamingCursor) return null;

  return (
    <div className="space-y-3">
      {segments.map((segment, index) =>
        segment.type === 'answer' ? (
          <div
            key={`answer-${index}`}
            className={onAnswerClick ? 'cursor-text' : undefined}
            onClick={onAnswerClick}
          >
            {renderMarkdownBlock(segment.content, tone)}
          </div>
        ) : (
          <details
            key={`think-${index}`}
            className="rounded-lg border border-white/10 bg-black/20 px-3 py-2"
          >
            <summary className="cursor-pointer text-xs font-semibold tracking-wide text-slate-400 select-none">
              {segment.streaming ? 'Reasoning (streaming)' : 'Reasoning'}
            </summary>
            <div className="mt-2">{renderMarkdownBlock(segment.content, 'think')}</div>
          </details>
        ),
      )}
      {showStreamingCursor && (
        <span className="bg-accent-magenta ml-1 inline-block h-4 w-2 animate-pulse select-none" />
      )}
    </div>
  );
}

function sanitizeFilename(input: string): string {
  const cleaned = input
    .trim()
    .replace(/[^\w.-]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return cleaned || 'session';
}

function formatExportStamp(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

/** Stable speaker colour from a consistent palette */
const SPEAKER_COLORS = [
  'text-accent-cyan',
  'text-accent-magenta',
  'text-green-400',
  'text-amber-400',
  'text-indigo-400',
  'text-rose-400',
];
const speakerColorMap = new Map<string, string>();
function speakerColor(name: string): string {
  let c = speakerColorMap.get(name);
  if (!c) {
    c = SPEAKER_COLORS[speakerColorMap.size % SPEAKER_COLORS.length];
    speakerColorMap.set(name, c);
  }
  return c;
}

export const AudioNoteModal: React.FC<AudioNoteModalProps> = ({
  isOpen,
  onClose,
  onRecordingMutated,
  note,
}) => {
  const { confirm, dialog: confirmDialog } = useConfirm();

  // Portal Container State
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);

  // Animation State
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  // Audio player state
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const transcriptContainerRef = useRef<HTMLDivElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [audioError, setAudioError] = useState<string | null>(null);
  const _progress = duration > 0 ? (currentTime / duration) * 100 : 0; // codeql[js/unused-local-variable] — will be consumed by the progress-bar UI once wired up

  // Web Audio API state for AudioVisualizer
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaSourceCreatedRef = useRef(false);
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);

  // Summary State
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [summaryText, setSummaryText] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSummaryEditing, setIsSummaryEditing] = useState(false);
  const [summaryEditText, setSummaryEditText] = useState('');
  const [isSummarySaving, setIsSummarySaving] = useState(false);
  const summaryEditRef = useRef<HTMLTextAreaElement>(null);
  const summarySaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Date editing state
  const [isDateEditing, setIsDateEditing] = useState(false);
  const [dateEditValue, setDateEditValue] = useState('');

  // LM Sidebar State
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [llmStatus, setLlmStatus] = useState<'active' | 'inactive'>('inactive');
  const [llmModel, setLlmModel] = useState<string | null>(null);

  // Per-conversation model selector state
  const [availableModels, setAvailableModels] = useState<LLMModel[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);

  // Context Menu State
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    conversationId: number;
  } | null>(null);
  // Inline rename dialog state (replaces window.prompt, which is blocked in Electron)
  const [renameDialog, setRenameDialog] = useState<{
    conversationId: number;
    currentTitle: string;
  } | null>(null);
  const [renameValue, setRenameValue] = useState('');

  // Chat Sessions — fetched from API when recording is available
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  // Chat input state
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<DisplayMessage[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);
  // Inline edit state for user messages
  const [editingMsgIndex, setEditingMsgIndex] = useState<number | null>(null);
  const [editingContent, setEditingContent] = useState('');
  // Ref for the chat text input — used to auto-focus it
  const chatInputRef = useRef<HTMLInputElement>(null);
  // Focus the chat input whenever the sidebar opens or a new session is created
  useEffect(() => {
    if (!isSidebarOpen) return;
    // Small delay so the sidebar animation has started and the element is rendered
    const t = setTimeout(() => chatInputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [isSidebarOpen]);
  // Whether the server has auto-title generation enabled (fetched once on open)
  const autoTitleEnabledRef = useRef(true);
  useEffect(() => {
    if (!isOpen) return;
    apiClient.getLLMStatus().then((status) => {
      autoTitleEnabledRef.current = status.auto_title_enabled ?? true;
    }).catch(() => { /* leave default true */ });
  }, [isOpen]);

  // Output formatting
  const [hideTimestamps, setHideTimestamps] = useState(false);
  useEffect(() => {
    if (!isOpen) return;
    getConfig<boolean>('output.hideTimestamps').then((v) => {
      if (v != null) setHideTimestamps(v);
    });
  }, [isOpen]);

  // Real recording data
  const {
    recording,
    transcription,
    loading: recordingLoading,
    audioUrl,
  } = useRecording(note?.recordingId ?? null);
  const segments = transcription?.segments ?? [];
  const hasDiarizationTranscript =
    Boolean(recording?.has_diarization) || segments.some((seg) => Boolean(seg.speaker));
  const hasWordTimestamps = segments.some((seg) => seg.words && seg.words.length > 0);
  const hasSegmentDetail = hasDiarizationTranscript || hasWordTimestamps;
  const plainTranscriptText = hasSegmentDetail
    ? ''
    : segments
        .map((seg) => seg.text.trim())
        .filter(Boolean)
        .join(' ')
        .trim();
  const isVibeVoiceRecording = recording?.transcription_backend === 'vibevoice_asr';
  const allowWordPlaybackHighlight = !isVibeVoiceRecording;
  const segmentWordOffsets = useMemo(() => {
    const offsets: number[] = [];
    let total = 0;
    for (const seg of segments) {
      offsets.push(total);
      total += seg.words?.length ?? 0;
    }
    return offsets;
  }, [segments]);
  useWordHighlighter({
    audioRef,
    segments,
    isPlaying,
    containerRef: transcriptContainerRef,
    enabled: allowWordPlaybackHighlight,
  });

  // Initialize Portal Target on Mount
  useEffect(() => {
    setPortalContainer(document.body);
  }, []);

  // Handle Mount/Unmount for Animations
  useEffect(() => {
    let rafId: number;
    let timer: ReturnType<typeof setTimeout>;

    if (isOpen) {
      setIsRendered(true);
      setIsVisible(false);
      setSummaryExpanded(false);
      setSummaryText('');
      setIsGenerating(false);
      apiClient
        .getLLMStatus()
        .then((s) => {
          setLlmStatus(s.available ? 'active' : 'inactive');
          setLlmModel(s.model ?? null);
        })
        .catch(() => setLlmStatus('inactive'));

      if (!modelsLoaded) {
        apiClient
          .getAvailableModels()
          .then((res) => {
            setAvailableModels([...(res.models ?? [])].sort((a, b) => a.id.localeCompare(b.id)));
          })
          .catch(() => {})
          .finally(() => setModelsLoaded(true));
      }

      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => {
        setIsRendered(false);
      }, 500);
    }
    return () => {
      cancelAnimationFrame(rafId);
      clearTimeout(timer);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    setAudioError(null);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);

    return () => {
      // Clean up Web Audio API resources when modal closes
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {});
        audioContextRef.current = null;
      }
      mediaSourceCreatedRef.current = false;
      setAnalyserNode(null);
    };
  }, [isOpen, note?.recordingId]);

  // Fetch conversations for this recording whenever modal opens or note changes
  useEffect(() => {
    if (!isOpen) return;

    setChatSessions([]);
    setChatMessages([]);
    setActiveConversationId(null);
    setChatInput('');
    setContextMenu(null);
    setSessionsError(null);

    if (!note?.recordingId) return;

    let cancelled = false;
    const loadSessions = async () => {
      setSessionsLoading(true);
      try {
        const data = await apiClient.listConversations(note.recordingId);
        if (cancelled) return;

        const mapped = sortChatSessions(data.conversations.map(toChatSession));
        setChatSessions(mapped);

        if (mapped.length > 0) {
          const firstConversationId = mapped[0].id;
          setActiveConversationId(firstConversationId);
          try {
            const conversation = await apiClient.getConversation(firstConversationId);
            if (cancelled) return;
            setChatMessages(toDisplayMessages(conversation.messages));
            setChatSessions((prev) =>
              sortChatSessions(
                prev.map((session) =>
                  session.id === conversation.id ? toChatSession(conversation) : session,
                ),
              ),
            );
          } catch {
            if (!cancelled) {
              setChatMessages([]);
              setSessionsError('Failed to load selected session.');
            }
          }
        }
      } catch {
        if (!cancelled) setSessionsError('Failed to load sessions.');
      } finally {
        if (!cancelled) setSessionsLoading(false);
      }
    };

    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, [isOpen, note?.recordingId]);

  // Stream summary from API (or show existing summary)
  useEffect(() => {
    if (!isGenerating) return;

    // If recording already has a summary, show it immediately
    if (recording?.summary) {
      let i = 0;
      const text = recording.summary;
      const interval = setInterval(() => {
        setSummaryText(text.slice(0, i));
        i++;
        if (i > text.length) {
          setIsGenerating(false);
          clearInterval(interval);
        }
      }, 15);
      return () => clearInterval(interval);
    }

    // Otherwise, stream from the LLM API
    if (note?.recordingId) {
      let cancelled = false;
      (async () => {
        try {
          const stream = apiClient.summarizeRecordingStream(note.recordingId!);
          let text = '';
          for await (const chunk of stream) {
            if (cancelled) break;
            text += chunk;
            setSummaryText(text);
          }
        } catch {
          if (!cancelled) setSummaryText('Failed to generate summary. Is the LLM server running?');
        } finally {
          if (!cancelled) setIsGenerating(false);
        }
      })();
      return () => {
        cancelled = true;
      };
    } else {
      // No recording ID — show fallback message
      const msg = 'Open a synced recording to generate an AI summary.';
      let i = 0;
      const interval = setInterval(() => {
        setSummaryText(msg.slice(0, i));
        i++;
        if (i > msg.length) {
          setIsGenerating(false);
          clearInterval(interval);
        }
      }, 20);
      return () => clearInterval(interval);
    }
  }, [isGenerating, note?.recordingId, recording?.summary]);

  // Close context menu on click anywhere
  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, []);

  const handleGenerateSummary = () => {
    setSummaryExpanded(true);
    setIsGenerating(true);
  };

  const handleStopGeneration = useCallback(() => {
    setIsGenerating(false);
  }, []);

  const handleEnterSummaryEdit = useCallback(() => {
    if (isGenerating) return;
    setIsSummaryEditing(true);
    setSummaryEditText(summaryText);
    // Focus the textarea after render
    setTimeout(() => summaryEditRef.current?.focus(), 50);
  }, [isGenerating, summaryText]);

  const handleSaveSummary = useCallback(
    async (text: string) => {
      if (!note?.recordingId) return;
      setIsSummarySaving(true);
      try {
        await apiClient.updateRecordingSummary(note.recordingId, text || undefined);
        setSummaryText(text);
      } catch {
        // silently fail — user can retry
      } finally {
        setIsSummarySaving(false);
      }
    },
    [note?.recordingId],
  );

  const handleExitSummaryEdit = useCallback(
    (save: boolean) => {
      if (summarySaveTimerRef.current) {
        clearTimeout(summarySaveTimerRef.current);
        summarySaveTimerRef.current = null;
      }
      if (save && summaryEditText !== summaryText) {
        handleSaveSummary(summaryEditText);
      }
      setIsSummaryEditing(false);
    },
    [summaryEditText, summaryText, handleSaveSummary],
  );

  const handleSummaryEditChange = useCallback(
    (text: string) => {
      setSummaryEditText(text);
      // Debounced auto-save (2s after user stops typing)
      if (summarySaveTimerRef.current) clearTimeout(summarySaveTimerRef.current);
      summarySaveTimerRef.current = setTimeout(() => {
        if (note?.recordingId && text !== summaryText) {
          handleSaveSummary(text);
        }
      }, 2000);
    },
    [note?.recordingId, summaryText, handleSaveSummary],
  );

  const handleClearSummary = useCallback(async () => {
    if (!note?.recordingId) return;
    if (
      !(await confirm('Clear the summary? This cannot be undone.', {
        danger: true,
        confirmLabel: 'Clear',
      }))
    )
      return;
    await handleSaveSummary('');
    setSummaryText('');
    setSummaryExpanded(false);
    setIsSummaryEditing(false);
  }, [note?.recordingId, handleSaveSummary]);

  const handleCloseAction = () => {
    if (isSidebarOpen) {
      setIsSidebarOpen(false);
    } else {
      onClose();
    }
  };

  const handleContextMenu = (e: React.MouseEvent, conversationId: number) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, conversationId });
  };

  const handleSelectSession = useCallback(async (conversationId: number) => {
    setContextMenu(null);
    setActiveConversationId(conversationId);
    setSessionsError(null);
    try {
      const conversation = await apiClient.getConversation(conversationId);
      setChatMessages(toDisplayMessages(conversation.messages));
      setChatSessions((prev) =>
        sortChatSessions(
          prev.map((session) =>
            session.id === conversation.id ? toChatSession(conversation) : session,
          ),
        ),
      );
    } catch {
      setChatMessages([]);
      setSessionsError('Failed to load selected session.');
    }
  }, []);

  // Per-conversation model change handler
  const handleModelChange = useCallback(
    async (newModel: string | null) => {
      if (!activeConversationId) return;
      try {
        await apiClient.updateConversation(activeConversationId, { model: newModel });
        setChatSessions((prev) =>
          prev.map((s) => (s.id === activeConversationId ? { ...s, model: newModel } : s)),
        );
      } catch {
        setSessionsError('Failed to update model.');
      }
      setModelDropdownOpen(false);
    },
    [activeConversationId],
  );

  const handleRefreshModels = useCallback(async () => {
    try {
      const res = await apiClient.getAvailableModels();
      setAvailableModels([...(res.models ?? [])].sort((a, b) => a.id.localeCompare(b.id)));
      setModelsLoaded(true);
    } catch {
      /* keep stale list */
    }
  }, []);

  const handleCreateSession = useCallback(async () => {
    if (!note?.recordingId) return;
    try {
      const conv = await apiClient.createConversation(note.recordingId, 'New Chat');
      const updatedAt = new Date().toISOString();
      const createdSession: ChatSession = {
        id: conv.conversation_id,
        title: conv.title || 'New Chat',
        type: inferSessionType(conv.title || 'New Chat'),
        timestamp: formatSessionTime(updatedAt),
        updatedAt,
      };
      setChatSessions((prev) =>
        sortChatSessions([
          createdSession,
          ...prev.filter((session) => session.id !== createdSession.id),
        ]),
      );
      setActiveConversationId(createdSession.id);
      setChatMessages([]);
      setSessionsError(null);
      setContextMenu(null);
      // Focus the input so the user can start typing immediately
      setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch {
      setSessionsError('Failed to create a new session.');
    }
  }, [note?.recordingId]);

  // Audio playback handlers
  const handlePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(() => {
        setAudioError(
          'Unable to start playback. Check that the audio file is available and the server is reachable.',
        );
      });
    }
  };

  const handleSeek = (delta: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Math.min(audio.duration || 0, audio.currentTime + delta));
  };

  const handleTimeUpdate = () => {
    const audio = audioRef.current;
    if (audio) setCurrentTime(audio.currentTime);
  };

  const handleLoadedMetadata = () => {
    const audio = audioRef.current;
    if (audio) {
      setDuration(audio.duration);
      setAudioError(null);

      // Set up Web Audio API pipeline for AudioVisualizer (only once per element)
      if (!mediaSourceCreatedRef.current) {
        try {
          const ctx = audioContextRef.current || new AudioContext();
          audioContextRef.current = ctx;
          const source = ctx.createMediaElementSource(audio);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 2048;
          source.connect(analyser);
          analyser.connect(ctx.destination);
          setAnalyserNode(analyser);
          mediaSourceCreatedRef.current = true;
        } catch {
          // MediaElementSource can only be created once — ignore if already done
        }
      }
    }
  };

  const handleAudioPlay = () => {
    setIsPlaying(true);
    setAudioError(null);
  };
  const handleAudioPause = () => setIsPlaying(false);
  const handleAudioEnded = () => {
    setIsPlaying(false);
    setCurrentTime(0);
  };
  const handleAudioError = () => {
    setIsPlaying(false);
    setAudioError(
      'Audio playback failed. The source may be unavailable or in an unsupported format.',
    );
  };

  // LLM Chat handler — sends user message and streams assistant response
  const handleSendMessage = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? chatInput).trim();
    if (!text || !note?.recordingId || isChatLoading) return;

    let conversationId = activeConversationId;
    if (!conversationId) {
      try {
        const conv = await apiClient.createConversation(note.recordingId, 'New Chat');
        conversationId = conv.conversation_id;
        const updatedAt = new Date().toISOString();
        const createdSession: ChatSession = {
          id: conversationId,
          title: conv.title || 'New Chat',
          type: inferSessionType(conv.title || 'New Chat'),
          timestamp: formatSessionTime(updatedAt),
          updatedAt,
        };
        setChatSessions((prev) =>
          sortChatSessions([
            createdSession,
            ...prev.filter((session) => session.id !== createdSession.id),
          ]),
        );
        setActiveConversationId(conversationId);
      } catch {
        setSessionsError('Failed to create a new session.');
        return;
      }
    }

    setSessionsError(null);
    const isFirstExchange = chatMessages.length === 0;
    setChatMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ]);
    setChatInput('');
    setIsChatLoading(true);
    let streamSucceeded = false;
    try {
      const stream = apiClient.chat({
        conversation_id: conversationId,
        user_message: text,
        include_transcription: true,
      });
      let fullResponse = '';
      for await (const chunk of stream) {
        fullResponse += chunk;
        setChatMessages((prev) => {
          const updated = [...prev];
          const lastMsg: DisplayMessage = { role: 'assistant', content: fullResponse };
          updated[updated.length - 1] = lastMsg;
          return updated;
        });
      }
      streamSucceeded = true;
    } catch {
      setChatMessages((prev) => {
        const updated = [...prev];
        const errorMsg: DisplayMessage = {
          role: 'assistant',
          content: 'Error: Failed to get response from LLM.',
        };
        updated[updated.length - 1] = errorMsg;
        return updated;
      });
    } finally {
      const updatedAt = new Date().toISOString();
      setChatSessions((prev) => {
        const current = prev.find((session) => session.id === conversationId);
        if (!current) return prev;
        const refreshed = {
          ...current,
          updatedAt,
          timestamp: formatSessionTime(updatedAt),
        };
        return sortChatSessions([
          refreshed,
          ...prev.filter((session) => session.id !== conversationId),
        ]);
      });
      setIsChatLoading(false);
    }
    // Auto-generate title after the first successful exchange (if enabled)
    if (streamSucceeded && isFirstExchange && conversationId && autoTitleEnabledRef.current) {
      try {
        const { title } = await apiClient.generateConversationTitle(conversationId);
        if (title) {
          const updatedAt = new Date().toISOString();
          setChatSessions((prev) =>
            sortChatSessions(
              prev.map((session) =>
                session.id === conversationId
                  ? {
                      ...session,
                      title,
                      type: inferSessionType(title),
                      updatedAt,
                      timestamp: formatSessionTime(updatedAt),
                    }
                  : session,
              ),
            ),
          );
        }
      } catch {
        // Title generation failure is non-fatal
      }
    }
  }, [chatInput, note?.recordingId, isChatLoading, activeConversationId, chatMessages]);

  /**
   * Truncate conversation history then resend:
   * - Edit mode (overrideText provided): `firstDeleteIndex` is the user message to replace.
   *   Slice from there, delete from DB at that user message ID, resend with new text.
   * - Regenerate mode (no overrideText): `firstDeleteIndex` is the assistant message to redo.
   *   Walk back to find the preceding user message, truncate from THERE (so the user message
   *   is also removed from UI and DB), then resend with its text. This ensures only one copy
   *   of the user message is added and transcription context is re-included.
   */
  const handleTruncateAndRetry = useCallback(
    async (firstDeleteIndex: number, overrideText?: string) => {
      if (isChatLoading || !activeConversationId) return;

      let truncateFromIndex = firstDeleteIndex;
      let retryText = overrideText;

      if (!retryText) {
        // Regenerate mode: walk back to find the preceding user message and
        // truncate from there so handleSendMessage doesn't create a duplicate.
        for (let i = firstDeleteIndex - 1; i >= 0; i--) {
          if (chatMessages[i].role === 'user') {
            retryText = chatMessages[i].content;
            truncateFromIndex = i;
            break;
          }
        }
      }
      if (!retryText) return;

      const msgToDelete = chatMessages[truncateFromIndex];
      const dbId = msgToDelete?.id;

      // Truncate optimistically in UI
      setChatMessages((prev) => prev.slice(0, truncateFromIndex));
      setEditingMsgIndex(null);
      setEditingContent('');

      // Truncate on the server (best-effort) if we have a DB ID
      if (dbId !== undefined) {
        try {
          await apiClient.deleteMessagesFrom(activeConversationId, dbId);
        } catch {
          // Non-fatal: server will reconcile on next load
        }
      }

      // Re-send directly (bypass chatInput state to avoid async timing issues)
      await handleSendMessage(retryText);
    },
    [isChatLoading, activeConversationId, chatMessages, handleSendMessage],
  );

  /** Called when the user confirms an inline edit of a user message. */
  const handleCommitEdit = useCallback(
    (msgIndex: number) => {
      const text = editingContent.trim();
      if (!text) return;
      handleTruncateAndRetry(msgIndex, text);
    },
    [editingContent, handleTruncateAndRetry],
  );

  // Session context-menu handlers
  const handleRenameSession = useCallback(() => {
    if (!contextMenu) return;
    const target = chatSessions.find((session) => session.id === contextMenu.conversationId);
    if (!target) {
      setContextMenu(null);
      return;
    }
    // Open inline rename dialog (window.prompt is blocked in Electron on macOS)
    setRenameValue(target.title);
    setRenameDialog({ conversationId: target.id, currentTitle: target.title });
    setContextMenu(null);
  }, [contextMenu, chatSessions]);

  const handleRenameCommit = useCallback(async () => {
    if (!renameDialog) return;
    const newTitle = renameValue.trim();
    if (!newTitle || newTitle === renameDialog.currentTitle) {
      setRenameDialog(null);
      return;
    }
    try {
      await apiClient.updateConversation(renameDialog.conversationId, { title: newTitle });
      const updatedAt = new Date().toISOString();
      setChatSessions((prev) =>
        sortChatSessions(
          prev.map((session) =>
            session.id === renameDialog.conversationId
              ? {
                  ...session,
                  title: newTitle,
                  type: inferSessionType(newTitle),
                  updatedAt,
                  timestamp: formatSessionTime(updatedAt),
                }
              : session,
          ),
        ),
      );
    } catch {
      toast.error('Failed to rename session.');
    }
    setRenameDialog(null);
  }, [renameDialog, renameValue]);

  const handleExportSession = useCallback(async () => {
    if (!contextMenu) return;
    const conversationId = contextMenu.conversationId;
    try {
      const conversation = await apiClient.getConversation(conversationId);
      const now = new Date();
      const lines: string[] = [
        'TranscriptionSuite Session Export',
        `Session: ${conversation.title}`,
        `Recording: ${recording?.title ?? note?.title ?? 'Unknown recording'}`,
        `Recording ID: ${conversation.recording_id}`,
        `Exported: ${now.toISOString()}`,
        '',
        'Messages',
        '--------',
      ];

      const messageLines = (conversation.messages ?? [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map(
          (m) =>
            `[${new Date(m.created_at).toLocaleString()}] ${m.role.toUpperCase()}: ${m.content}`,
        );

      if (messageLines.length === 0) {
        lines.push('(No chat messages yet)');
      } else {
        lines.push(...messageLines);
      }

      const filename = `${sanitizeFilename(conversation.title)}_${formatExportStamp(now)}.txt`;
      const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      toast.error('Failed to export session.');
    }
    setContextMenu(null);
  }, [contextMenu, recording?.title, note?.title]);

  const handleDeleteSession = useCallback(async () => {
    if (!contextMenu) return;
    const conversationId = contextMenu.conversationId;
    const target = chatSessions.find((session) => session.id === conversationId);
    if (
      !(await confirm(
        `Delete session "${target?.title ?? 'this session'}"? This cannot be undone.`,
        { danger: true, confirmLabel: 'Delete' },
      ))
    ) {
      setContextMenu(null);
      return;
    }

    try {
      await apiClient.deleteConversation(conversationId);
      const remaining = sortChatSessions(
        chatSessions.filter((session) => session.id !== conversationId),
      );
      setChatSessions(remaining);
      setContextMenu(null);

      if (activeConversationId === conversationId) {
        if (remaining.length === 0) {
          setActiveConversationId(null);
          setChatMessages([]);
          setSessionsError(null);
          return;
        }
        const fallbackId = remaining[0].id;
        setActiveConversationId(fallbackId);
        try {
          const fallbackConversation = await apiClient.getConversation(fallbackId);
          setChatMessages(toDisplayMessages(fallbackConversation.messages));
          setSessionsError(null);
        } catch {
          setChatMessages([]);
          setSessionsError('Failed to load selected session.');
        }
      }
    } catch {
      toast.error('Failed to delete session.');
      setContextMenu(null);
    }
  }, [contextMenu, chatSessions, activeConversationId]);

  const activeSession = chatSessions.find((session) => session.id === activeConversationId) ?? null;

  // Resolve the effective model for the active conversation
  const effectiveModel = activeSession?.model || llmModel || 'unknown';
  const hasModelOverride = Boolean(activeSession?.model);

  // Close model dropdown on outside click
  useEffect(() => {
    if (!modelDropdownOpen) return;
    const handler = () => setModelDropdownOpen(false);
    // Delay to avoid catching the opening click
    const id = setTimeout(() => document.addEventListener('click', handler), 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener('click', handler);
    };
  }, [modelDropdownOpen]);

  /** Open inline date editor with current date pre-filled */
  const handleDateEditOpen = useCallback(() => {
    if (!recording?.recorded_at) return;
    // Format as datetime-local input value: YYYY-MM-DDTHH:mm
    const d = new Date(recording.recorded_at);
    const pad = (n: number) => n.toString().padStart(2, '0');
    const val = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    setDateEditValue(val);
    setIsDateEditing(true);
  }, [recording?.recorded_at]);

  /** Save new date and close editor */
  const handleDateSave = useCallback(async () => {
    if (!note?.recordingId || !dateEditValue) return;
    try {
      const isoDate = new Date(dateEditValue).toISOString();
      await apiClient.updateRecordingDate(note.recordingId, isoDate);
      setIsDateEditing(false);
      onRecordingMutated?.();
      onClose(); // refresh
    } catch {
      toast.error('Failed to update date.');
    }
  }, [note?.recordingId, dateEditValue, onRecordingMutated, onClose]);

  if (!isRendered || !note || !portalContainer) return createPortal(confirmDialog, document.body);

  return (
    <>
      {/* Render confirmDialog and renameDialog via portals to document.body so they
          always appear above the modal (z-9999), regardless of stacking context. */}
      {createPortal(confirmDialog, document.body)}
      {renameDialog &&
        createPortal(
          <div className="fixed inset-0 z-10000 flex items-center justify-center p-4">
            <div
              className="absolute inset-0 bg-black/60 backdrop-blur-sm"
              onClick={() => setRenameDialog(null)}
            />
            <div className="relative flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl">
              <div className="flex items-center border-b border-white/10 bg-white/5 px-6 py-4">
                <span className="text-base font-semibold text-white">Rename Session</span>
              </div>
              <div className="bg-black/20 px-6 py-5">
                <input
                  autoFocus
                  type="text"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleRenameCommit();
                    if (e.key === 'Escape') setRenameDialog(null);
                  }}
                  className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4">
                <button
                  onClick={() => setRenameDialog(null)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRenameCommit}
                  className="bg-accent-cyan rounded-lg px-4 py-2 text-sm font-medium text-black hover:bg-cyan-300"
                >
                  Rename
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
      {createPortal(
        <div className="fixed inset-0 z-9999 flex items-center justify-center p-4 lg:p-8">
          {/* Backdrop */}
          <div
            className={`absolute inset-0 bg-black/40 backdrop-blur-md transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
            onClick={onClose}
          />

          {/* Main Modal Container */}
          <div
            className={`bg-glass-surface relative flex h-[85vh] w-full max-w-6xl overflow-hidden rounded-3xl border border-white/10 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'}`}
          >
            {/* Left Section: Content & Player */}
            <div className="flex min-w-0 flex-1 flex-col bg-linear-to-b from-white/5 to-transparent">
              {/* Header */}
              <div className="flex h-20 flex-none items-center justify-between border-b border-white/5 px-8 select-none">
                <div>
                  <h2 className="text-2xl font-bold tracking-tight text-white">
                    {recording?.title ?? note.title}
                  </h2>
                  <div className="mt-1 flex items-center gap-4 text-sm text-slate-400">
                    <span className="flex items-center gap-1.5">
                      <Clock size={14} />{' '}
                      {recording ? formatRecSecs(recording.duration_seconds) : note.duration}
                    </span>
                    <span className="h-1 w-1 rounded-full bg-slate-600"></span>
                    <span className="flex items-center gap-1.5">
                      <FileText size={14} />{' '}
                      {recording ? `${recording.word_count.toLocaleString()} words` : '— words'}
                    </span>
                    <span className="h-1 w-1 rounded-full bg-slate-600"></span>
                    {isDateEditing ? (
                      <span className="flex items-center gap-1.5">
                        <input
                          type="datetime-local"
                          value={dateEditValue}
                          onChange={(e) => setDateEditValue(e.target.value)}
                          className="focus:ring-accent-cyan rounded border border-white/20 bg-white/10 px-2 py-0.5 text-sm text-white scheme-dark outline-none focus:ring-1"
                          autoFocus
                        />
                        <button
                          onClick={handleDateSave}
                          className="hover:text-accent-cyan p-0.5 transition-colors"
                        >
                          <Check size={14} />
                        </button>
                        <button
                          onClick={() => setIsDateEditing(false)}
                          className="p-0.5 transition-colors hover:text-red-400"
                        >
                          <XCircle size={14} />
                        </button>
                      </span>
                    ) : (
                      <span
                        className="cursor-pointer text-slate-500 transition-colors hover:text-slate-300"
                        onClick={handleDateEditOpen}
                        title="Click to change date"
                      >
                        {recording
                          ? new Date(recording.recorded_at).toLocaleString()
                          : (note.date ?? '')}
                      </span>
                    )}
                    {note.tag && (
                      <span className="bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20 ml-2 rounded border px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase">
                        {note.tag}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {!isSidebarOpen && (
                    <>
                      <Button
                        variant="secondary"
                        className="h-10 text-slate-400 transition-all hover:text-white"
                        onClick={() => setIsSidebarOpen(true)}
                        icon={<MessageSquare size={18} />}
                      >
                        AI Assistant
                      </Button>
                      <div className="mx-1 h-8 w-px bg-white/10"></div>
                    </>
                  )}
                  <button
                    onClick={handleCloseAction}
                    className="rounded-full p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                  >
                    <X size={24} />
                  </button>
                </div>
              </div>

              {/* Scrollable Body */}
              <div
                ref={transcriptContainerRef}
                className="custom-scrollbar flex-1 space-y-8 overflow-y-auto p-8"
              >
                {/* 1. Audio Player Card */}
                <div className="group relative overflow-hidden rounded-2xl border border-white/5 bg-black/20 p-6 select-none">
                  {/* Hidden audio element for playback */}
                  {audioUrl && (
                    <audio
                      ref={audioRef}
                      src={audioUrl}
                      onTimeUpdate={handleTimeUpdate}
                      onLoadedMetadata={handleLoadedMetadata}
                      onPlay={handleAudioPlay}
                      onPause={handleAudioPause}
                      onEnded={handleAudioEnded}
                      onError={handleAudioError}
                      preload="metadata"
                      crossOrigin="anonymous"
                    />
                  )}
                  <div className="pointer-events-none absolute inset-0 opacity-30">
                    <AudioVisualizer analyserNode={analyserNode} className="h-full" />
                  </div>
                  <div className="relative z-10 flex flex-col items-center gap-4">
                    <div className="font-mono text-3xl font-light tracking-widest text-white">
                      {formatRecSecs(currentTime)}{' '}
                      <span className="text-lg text-slate-500">
                        / {duration > 0 ? formatRecSecs(duration) : note.duration}
                      </span>
                    </div>
                    <div className="flex items-center gap-6">
                      <button
                        onClick={() => handleSeek(-10)}
                        className="text-slate-400 transition-colors hover:text-white"
                        title="Rewind 10s"
                      >
                        <Rewind size={24} />
                      </button>
                      <button
                        onClick={handlePlayPause}
                        disabled={!audioUrl}
                        className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-black shadow-[0_0_20px_rgba(255,255,255,0.3)] transition-all hover:scale-105 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isPlaying ? (
                          <Pause size={24} fill="black" />
                        ) : (
                          <Play size={24} fill="black" className="ml-1" />
                        )}
                      </button>
                      <button
                        onClick={() => handleSeek(10)}
                        className="text-slate-400 transition-colors hover:text-white"
                        title="Forward 10s"
                      >
                        <FastForward size={24} />
                      </button>
                    </div>
                    {/* Seek bar */}
                    <input
                      type="range"
                      min={0}
                      max={duration || 100}
                      value={currentTime}
                      onChange={(e) => {
                        if (audioRef.current) audioRef.current.currentTime = Number(e.target.value);
                      }}
                      className="accent-accent-cyan h-1 w-full max-w-xs cursor-pointer rounded bg-white/10"
                    />
                    {audioError && <div className="text-xs text-red-400">{audioError}</div>}
                  </div>
                </div>

                {/* 2. AI Summary Section - Editable */}
                <div
                  className={`overflow-hidden rounded-2xl border border-white/10 transition-all duration-500 ease-in-out ${summaryExpanded ? 'from-accent-magenta/5 bg-linear-to-br to-purple-900/10' : 'bg-glass-100 hover:bg-white/5'}`}
                >
                  {!summaryExpanded ? (
                    <button
                      onClick={handleGenerateSummary}
                      className="text-accent-magenta group flex h-14 w-full items-center justify-center gap-3 transition-colors select-none hover:text-white"
                    >
                      <Sparkles size={18} className="group-hover:animate-spin-slow" />
                      <span className="font-medium tracking-wide">Generate AI Summary</span>
                    </button>
                  ) : (
                    <div className="selectable-text p-6">
                      <div className="mb-3 flex items-center justify-between select-none">
                        <div className="text-accent-magenta flex items-center gap-2">
                          <Sparkles size={16} />
                          <span className="text-xs font-bold tracking-widest uppercase">
                            AI Generated Summary
                          </span>
                        </div>
                        <div className="flex items-center gap-1">
                          {isGenerating && (
                            <button
                              onClick={handleStopGeneration}
                              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-red-400"
                              title="Stop generation"
                            >
                              <StopCircle size={14} />
                            </button>
                          )}
                          {!isGenerating && summaryText && !isSummaryEditing && (
                            <button
                              onClick={handleEnterSummaryEdit}
                              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                              title="Edit summary"
                            >
                              <Pencil size={14} />
                            </button>
                          )}
                          {isSummaryEditing && (
                            <>
                              <button
                                onClick={() => handleExitSummaryEdit(true)}
                                className="rounded-lg p-1.5 text-green-400 transition-colors hover:bg-white/10 hover:text-green-300"
                                title="Save"
                              >
                                <Check size={14} />
                              </button>
                              <button
                                onClick={() => handleExitSummaryEdit(false)}
                                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                                title="Cancel editing"
                              >
                                <XCircle size={14} />
                              </button>
                            </>
                          )}
                          {!isGenerating && summaryText && (
                            <button
                              onClick={handleClearSummary}
                              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-red-400"
                              title="Clear summary"
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                          {isSummarySaving && (
                            <Loader2 size={14} className="text-accent-magenta ml-1 animate-spin" />
                          )}
                        </div>
                      </div>
                      {isSummaryEditing ? (
                        <textarea
                          ref={summaryEditRef}
                          value={summaryEditText}
                          onChange={(e) => handleSummaryEditChange(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Escape') handleExitSummaryEdit(false);
                          }}
                          className="focus:ring-accent-magenta/50 min-h-32 w-full resize-y rounded-lg border border-white/10 bg-black/20 p-3 text-lg leading-relaxed text-slate-200 transition-all focus:ring-1 focus:outline-none"
                          placeholder="Edit summary..."
                        />
                      ) : (
                        renderLlmResponseContent({
                          content: summaryText,
                          tone: 'summary',
                          showStreamingCursor: isGenerating,
                          onAnswerClick: handleEnterSummaryEdit,
                        })
                      )}
                    </div>
                  )}
                </div>

                {/* 3. Transcript - Added selectable-text to paragraphs */}
                <div className="space-y-6">
                  <div className="pointer-events-none sticky top-0 z-10 py-4 select-none">
                    <span className="pointer-events-auto inline-flex items-center rounded-full border border-white/10 bg-[rgba(22,31,50,0.9)] px-4 py-1.5 text-xs font-bold tracking-widest text-slate-400 uppercase shadow-lg backdrop-blur-xl">
                      Transcript
                    </span>
                  </div>
                  {segments.length > 0 ? (
                    hasSegmentDetail ? (
                      segments.map((seg, i) => (
                        <div
                          key={i}
                          className={`group flex ${hasDiarizationTranscript ? 'gap-6' : ''}`}
                        >
                          {hasDiarizationTranscript && (
                            <div className="w-16 flex-none pt-1 text-right select-none">
                              {seg.speaker && (
                                <div
                                  className={`mb-1 text-xs font-bold ${speakerColor(seg.speaker)}`}
                                >
                                  {seg.speaker}
                                </div>
                              )}
                              {!hideTimestamps && (
                                <div className="font-mono text-[10px] text-slate-500">
                                  {formatRecSecs(seg.start)}
                                </div>
                              )}
                            </div>
                          )}
                          <div className="selectable-text min-w-0 flex-1 leading-relaxed text-slate-300 transition-colors group-hover:text-white">
                            {allowWordPlaybackHighlight && seg.words && seg.words.length > 0 ? (
                              <p className="flex flex-wrap">
                                {seg.words.map((w, wi) => (
                                  <span
                                    key={wi}
                                    data-word-idx={segmentWordOffsets[i] + wi}
                                    onClick={() => {
                                      if (audioRef.current) {
                                        audioRef.current.currentTime = w.start;
                                        audioRef.current.play().catch(() => {});
                                      }
                                    }}
                                    className="hover:bg-accent-cyan/20 hover:text-accent-cyan cursor-pointer rounded px-px transition-colors duration-150"
                                    title={
                                      hideTimestamps
                                        ? undefined
                                        : `${formatRecSecs(w.start)} → ${formatRecSecs(w.end)}`
                                    }
                                  >
                                    {w.word}
                                  </span>
                                ))}
                              </p>
                            ) : (
                              <p
                                className="hover:text-accent-cyan/80 cursor-pointer transition-colors"
                                onClick={() => {
                                  if (audioRef.current) {
                                    audioRef.current.currentTime = seg.start;
                                    audioRef.current.play().catch(() => {});
                                  }
                                }}
                                title={
                                  hideTimestamps ? undefined : `Seek to ${formatRecSecs(seg.start)}`
                                }
                              >
                                {seg.text}
                              </p>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="selectable-text min-w-0 leading-relaxed wrap-break-word whitespace-pre-wrap text-slate-300">
                        {plainTranscriptText}
                      </div>
                    )
                  ) : recordingLoading ? (
                    <div className="flex items-center justify-center py-12 text-slate-500">
                      <Loader2 size={20} className="mr-2 animate-spin" /> Loading transcript…
                    </div>
                  ) : (
                    <div className="py-12 text-center text-slate-500">No transcript available</div>
                  )}
                </div>
              </div>
            </div>

            {/* Right Section: LLM Sidebar - Chat messages marked selectable */}
            <div
              className={`flex flex-col border-l border-white/5 bg-[#0b1120] transition-all duration-500 ease-[cubic-bezier(0.33,1,0.68,1)] ${isSidebarOpen ? 'w-100 translate-x-0' : 'w-0 translate-x-10 overflow-hidden opacity-0'}`}
            >
              <div className="flex h-20 shrink-0 items-center justify-between border-b border-white/5 bg-white/2 px-5 select-none">
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-green-500/10 p-1.5 text-green-400">
                    <Bot size={18} />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">AI Assistant</div>
                    <div className="flex items-center gap-1.5">
                      <StatusLight
                        status={llmStatus}
                        className="h-1.5 w-1.5"
                        animate={llmStatus === 'active'}
                      />
                      <span className="text-[10px] tracking-wider text-slate-400 uppercase">
                        {llmStatus === 'active' ? 'Online' : 'Offline'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex min-w-100 flex-1 flex-col overflow-hidden">
                <div className="flex-none border-b border-white/5 bg-white/1 p-2 select-none">
                  <div className="flex items-center justify-between px-3 py-2">
                    <div className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
                      Sessions
                    </div>
                    <button
                      onClick={handleCreateSession}
                      title="New session"
                      className="rounded-md p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-50"
                      disabled={!note?.recordingId || sessionsLoading}
                    >
                      <Plus size={12} />
                    </button>
                  </div>
                  {sessionsLoading ? (
                    <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500">
                      <Loader2 size={12} className="animate-spin" /> Loading sessions...
                    </div>
                  ) : chatSessions.length === 0 ? (
                    <div className="px-3 py-2 text-xs text-slate-500">No sessions yet</div>
                  ) : (
                    <div className="space-y-1">
                      {chatSessions.map((session) => {
                        const isActive = activeConversationId === session.id;
                        return (
                          <div
                            key={session.id}
                            onClick={() => void handleSelectSession(session.id)}
                            onContextMenu={(e) => handleContextMenu(e, session.id)}
                            className={`group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'}`}
                          >
                            <div
                              className={`shrink-0 ${session.type === 'summary' ? 'text-accent-magenta' : 'text-accent-cyan'}`}
                            >
                              {session.type === 'summary' ? (
                                <Sparkles size={14} />
                              ) : (
                                <MessageSquare size={14} />
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-xs font-medium">{session.title}</div>
                              <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                                <span>{session.timestamp}</span>
                                {session.model && session.model !== llmModel && (
                                  <span className="text-accent-cyan/70 max-w-20 truncate rounded bg-white/5 px-1">
                                    {session.model}
                                  </span>
                                )}
                              </div>
                            </div>
                            {isActive && (
                              <div className="bg-accent-cyan h-1.5 w-1.5 rounded-full shadow-[0_0_5px_rgba(239,22,238,0.5)]"></div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {sessionsError && (
                    <div className="px-3 py-2 text-[10px] text-red-400">{sessionsError}</div>
                  )}
                </div>

                <div className="custom-scrollbar flex-1 space-y-4 overflow-y-auto p-4">
                  <div className="my-4 text-center text-xs text-slate-600 select-none">
                    {activeSession?.title ?? 'Current Session'}
                  </div>

                  {/* Welcome message */}
                  <div className="flex gap-3 pr-8">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 select-none">
                      <Bot size={14} className="text-white" />
                    </div>
                    <div className="selectable-text rounded-2xl rounded-tl-none border border-white/5 bg-white/5 p-3">
                      <p className="text-sm text-slate-300">
                        Hello! I've loaded the context for{' '}
                        <span className="text-accent-cyan font-medium select-none">
                          "{note.title}"
                        </span>
                        . Ask me anything about the speakers or topics discussed.
                      </p>
                    </div>
                  </div>

                  {/* Dynamic chat messages */}
                  {chatMessages.map((msg, idx) =>
                    msg.role === 'user' ? (
                      <div key={idx} className="group flex flex-row-reverse gap-3 pl-8">
                        <div className="bg-accent-cyan/20 flex h-8 w-8 shrink-0 items-center justify-center rounded-full select-none">
                          <User size={14} className="text-accent-cyan" />
                        </div>
                        <div className="flex min-w-0 flex-col items-end gap-1">
                          {editingMsgIndex === idx ? (
                            <div className="bg-accent-cyan/10 border-accent-cyan/10 w-full rounded-2xl rounded-tr-none border p-3">
                              <textarea
                                className="w-full resize-none bg-transparent text-sm text-white outline-none"
                                rows={3}
                                autoFocus
                                value={editingContent}
                                onChange={(e) => setEditingContent(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleCommitEdit(idx);
                                  }
                                  if (e.key === 'Escape') {
                                    setEditingMsgIndex(null);
                                    setEditingContent('');
                                  }
                                }}
                              />
                              <div className="mt-2 flex justify-end gap-2">
                                <button
                                  onClick={() => { setEditingMsgIndex(null); setEditingContent(''); }}
                                  className="rounded px-2 py-0.5 text-xs text-slate-400 hover:text-white"
                                >
                                  Cancel
                                </button>
                                <button
                                  onClick={() => handleCommitEdit(idx)}
                                  className="bg-accent-cyan rounded px-2 py-0.5 text-xs text-black"
                                >
                                  Send
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div className="bg-accent-cyan/10 border-accent-cyan/10 selectable-text rounded-2xl rounded-tr-none border p-3">
                              <p className="text-sm text-white">{msg.content}</p>
                            </div>
                          )}
                          {/* Hover action row — edit */}
                          {editingMsgIndex !== idx && (
                            <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                              <button
                                title="Edit message"
                                disabled={isChatLoading}
                                onClick={() => {
                                  setEditingMsgIndex(idx);
                                  setEditingContent(msg.content);
                                }}
                                className="rounded p-1 text-slate-500 hover:bg-white/10 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                <Pencil size={12} />
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div key={idx} className="group flex gap-3 pr-8">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 select-none">
                          <Bot size={14} className="text-white" />
                        </div>
                        <div className="flex min-w-0 flex-col gap-1">
                          <div className="selectable-text rounded-2xl rounded-tl-none border border-white/5 bg-white/5 p-3">
                            {msg.content ? (
                              renderLlmResponseContent({ content: msg.content, tone: 'chat' })
                            ) : isChatLoading && idx === chatMessages.length - 1 ? (
                              <Loader2 size={14} className="animate-spin text-slate-300" />
                            ) : null}
                          </div>
                          {/* Hover action row — copy + regenerate */}
                          {msg.content && (
                            <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                              <button
                                title="Copy response"
                                onClick={() => navigator.clipboard.writeText(msg.content)}
                                className="rounded p-1 text-slate-500 hover:bg-white/10 hover:text-slate-200"
                              >
                                <Copy size={12} />
                              </button>
                              <button
                                title="Regenerate"
                                disabled={isChatLoading}
                                onClick={() => handleTruncateAndRetry(idx)}
                                className="rounded p-1 text-slate-500 hover:bg-white/10 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                <RotateCw size={12} />
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    ),
                  )}
                </div>

                {/* Input Area */}
                <div className="border-t border-white/5 bg-white/2 p-4">
                  <div className="relative">
                    <input
                      ref={chatInputRef}
                      type="text"
                      placeholder="Ask about this note..."
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleSendMessage();
                        }
                      }}
                      disabled={isChatLoading || !note?.recordingId}
                      className="focus:border-accent-cyan/50 focus:ring-accent-cyan/20 w-full rounded-xl border border-white/10 bg-black/20 py-3 pr-12 pl-4 text-sm text-white placeholder-slate-500 transition-all focus:ring-1 focus:outline-none disabled:opacity-50"
                    />
                    <button
                      onClick={() => handleSendMessage()}
                      disabled={isChatLoading || !chatInput.trim()}
                      className="bg-accent-cyan absolute top-2 right-2 rounded-lg p-1.5 text-black transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Send size={14} />
                    </button>
                  </div>
                  <div className="mt-2 flex items-center justify-between px-1 select-none">
                    <div className="relative">
                      <button
                        onClick={() => activeConversationId && setModelDropdownOpen((v) => !v)}
                        disabled={!activeConversationId}
                        className={`flex items-center gap-1 rounded px-1 py-0.5 text-[10px] transition-colors ${
                          activeConversationId
                            ? 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                            : 'cursor-default text-slate-500'
                        } ${hasModelOverride ? 'text-accent-cyan' : ''}`}
                        title={
                          hasModelOverride
                            ? `Override: ${effectiveModel} (click to change)`
                            : `Using default: ${effectiveModel}`
                        }
                      >
                        Model: {effectiveModel}
                        {activeConversationId && <ChevronDown size={10} />}
                      </button>
                      {modelDropdownOpen && activeConversationId && (
                        <div className="absolute bottom-full left-0 z-50 mb-1 max-h-48 w-56 overflow-y-auto rounded-lg border border-white/10 bg-slate-900 py-1 shadow-xl">
                          <div className="flex items-center justify-between border-b border-white/5 px-3 py-1.5">
                            <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
                              Select Model
                            </span>
                            <button
                              onClick={handleRefreshModels}
                              className="rounded p-0.5 text-slate-500 hover:bg-white/10 hover:text-slate-300"
                              title="Refresh model list"
                            >
                              <RotateCw size={10} />
                            </button>
                          </div>
                          {hasModelOverride && (
                            <button
                              onClick={() => void handleModelChange(null)}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-slate-400 hover:bg-white/10 hover:text-white"
                            >
                              <XCircle size={12} /> Use default ({llmModel ?? 'auto'})
                            </button>
                          )}
                          {availableModels.map((m) => (
                            <button
                              key={m.id}
                              onClick={() => void handleModelChange(m.id)}
                              className={`flex w-full items-center px-3 py-1.5 text-left text-[11px] transition-colors hover:bg-white/10 hover:text-white ${
                                effectiveModel === m.id
                                  ? 'text-accent-cyan font-medium'
                                  : 'text-slate-400'
                              }`}
                            >
                              {m.id}
                            </button>
                          ))}
                          {availableModels.length === 0 && (
                            <div className="px-3 py-1.5 text-[10px] text-slate-500">
                              No models discovered — type a model ID below
                            </div>
                          )}
                          <div className="border-t border-white/5 px-2 py-1.5">
                            <input
                              type="text"
                              placeholder="Type model ID..."
                              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1 text-[11px] text-white placeholder-slate-600 focus:border-white/20 focus:outline-none"
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  const val = (e.target as HTMLInputElement).value.trim();
                                  if (val) void handleModelChange(val);
                                }
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                    <span className="text-[10px] text-slate-500">
                      {segments.length} segments context
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Context Menu Portal */}
          {contextMenu && (
            <div
              className="animate-in fade-in zoom-in-95 fixed z-10000 w-48 overflow-hidden rounded-xl border border-slate-900 bg-slate-900 py-1 shadow-2xl duration-100 select-none"
              style={{ top: contextMenu.y, left: contextMenu.x }}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={handleRenameSession}
                className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-300 hover:bg-white/10 hover:text-white"
              >
                <Edit2 size={14} /> Rename
              </button>
              <button
                onClick={handleExportSession}
                className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-300 hover:bg-white/10 hover:text-white"
              >
                <Share size={14} /> Export TXT
              </button>
              <div className="my-1 h-px bg-white/10"></div>
              <button
                onClick={handleDeleteSession}
                className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300"
              >
                <Trash2 size={14} /> Delete
              </button>
            </div>
          )}
        </div>,
        portalContainer,
      )}
    </>
  );
};
