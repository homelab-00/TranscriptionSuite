
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Play, Pause, Rewind, FastForward, Sparkles, MessageSquare, Clock, FileText, Bot, User, Send, Settings2, MoreHorizontal, Trash2, Edit2, Share, Loader2, Pencil, Check, XCircle, StopCircle } from 'lucide-react';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { useRecording } from '../../src/hooks/useRecording';
import { apiClient } from '../../src/api/client';
import type { Conversation } from '../../src/api/types';

/** Local type for chat message display (simpler than API's ChatMessage) */
interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface AudioNoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  note: {
    title: string;
    date?: string;
    duration: string;
    tag?: string;
    recordingId?: number;
  } | null;
}

interface ChatSession {
    id: string;
    title: string;
    type: 'summary' | 'chat';
    timestamp: string;
    active: boolean;
}

/** Format seconds to MM:SS display */
function formatRecSecs(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

/** Stable speaker colour from a consistent palette */
const SPEAKER_COLORS = ['text-accent-cyan', 'text-accent-magenta', 'text-green-400', 'text-amber-400', 'text-indigo-400', 'text-rose-400'];
const speakerColorMap = new Map<string, string>();
function speakerColor(name: string): string {
  let c = speakerColorMap.get(name);
  if (!c) {
    c = SPEAKER_COLORS[speakerColorMap.size % SPEAKER_COLORS.length];
    speakerColorMap.set(name, c);
  }
  return c;
}

export const AudioNoteModal: React.FC<AudioNoteModalProps> = ({ isOpen, onClose, note }) => {
  // Portal Container State
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);

  // Animation State
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  
  // Audio player state
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  
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

  // Context Menu State
  const [contextMenu, setContextMenu] = useState<{x: number, y: number, id: string} | null>(null);

  // Chat Sessions — fetched from API when recording is available
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);

  // Chat input state
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<DisplayMessage[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);

  // Real recording data
  const { recording, transcription, loading: recordingLoading, audioUrl } = useRecording(note?.recordingId ?? null);
  const segments = transcription?.segments ?? [];

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
      apiClient.getLLMStatus()
        .then(s => { setLlmStatus(s.available ? 'active' : 'inactive'); setLlmModel(s.model ?? null); })
        .catch(() => setLlmStatus('inactive'));

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

  // Fetch conversations when recording is available
  useEffect(() => {
    if (!note?.recordingId) return;
    apiClient.listConversations(note.recordingId).then(data => {
      setChatSessions(data.conversations.map(c => ({
        id: String(c.id),
        title: c.title,
        type: (c.title.toLowerCase().includes('summary') ? 'summary' : 'chat') as 'summary' | 'chat',
        timestamp: new Date(c.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        active: false,
      })));
    }).catch(() => {});
  }, [note?.recordingId]);

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
        if (i > text.length) { setIsGenerating(false); clearInterval(interval); }
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
      return () => { cancelled = true; };
    } else {
      // No recording ID — show fallback message
      const msg = 'Open a synced recording to generate an AI summary.';
      let i = 0;
      const interval = setInterval(() => {
        setSummaryText(msg.slice(0, i)); i++;
        if (i > msg.length) { setIsGenerating(false); clearInterval(interval); }
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

  const handleSaveSummary = useCallback(async (text: string) => {
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
  }, [note?.recordingId]);

  const handleExitSummaryEdit = useCallback((save: boolean) => {
    if (summarySaveTimerRef.current) {
      clearTimeout(summarySaveTimerRef.current);
      summarySaveTimerRef.current = null;
    }
    if (save && summaryEditText !== summaryText) {
      handleSaveSummary(summaryEditText);
    }
    setIsSummaryEditing(false);
  }, [summaryEditText, summaryText, handleSaveSummary]);

  const handleSummaryEditChange = useCallback((text: string) => {
    setSummaryEditText(text);
    // Debounced auto-save (2s after user stops typing)
    if (summarySaveTimerRef.current) clearTimeout(summarySaveTimerRef.current);
    summarySaveTimerRef.current = setTimeout(() => {
      if (note?.recordingId && text !== summaryText) {
        handleSaveSummary(text);
      }
    }, 2000);
  }, [note?.recordingId, summaryText, handleSaveSummary]);

  const handleClearSummary = useCallback(async () => {
    if (!note?.recordingId) return;
    const confirmed = window.confirm('Clear the summary? This cannot be undone.');
    if (!confirmed) return;
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

  const handleContextMenu = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, id });
  };

  // Audio playback handlers
  const handlePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(() => {});
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
    if (audio) setDuration(audio.duration);
  };

  const handleAudioPlay = () => setIsPlaying(true);
  const handleAudioPause = () => setIsPlaying(false);
  const handleAudioEnded = () => { setIsPlaying(false); setCurrentTime(0); };

  // LLM Chat handler — sends user message and streams assistant response
  const handleSendMessage = useCallback(async () => {
    const text = chatInput.trim();
    if (!text || !note?.recordingId || isChatLoading) return;

    // Add user message to display
    const userMsg: DisplayMessage = { role: 'user', content: text };
    setChatMessages(prev => [...prev, userMsg]);
    setChatInput('');
    setIsChatLoading(true);

    // Prepare assistant placeholder
    const assistantMsg: DisplayMessage = { role: 'assistant', content: '' };
    setChatMessages(prev => [...prev, assistantMsg]);

    try {
      // Ensure we have a conversation
      let convId = activeConversationId;
      if (!convId) {
        const conv = await apiClient.createConversation(note.recordingId, 'Chat');
        convId = conv.conversation_id;
        setActiveConversationId(convId);
      }

      const stream = apiClient.chat({
        conversation_id: convId,
        user_message: text,
        include_transcription: true,
      });
      let fullResponse = '';
      for await (const chunk of stream) {
        fullResponse += chunk;
        setChatMessages(prev => {
          const updated = [...prev];
          const lastMsg: DisplayMessage = { role: 'assistant', content: fullResponse };
          updated[updated.length - 1] = lastMsg;
          return updated;
        });
      }
    } catch (err) {
      setChatMessages(prev => {
        const updated = [...prev];
        const errorMsg: DisplayMessage = { role: 'assistant', content: 'Error: Failed to get response from LLM.' };
        updated[updated.length - 1] = errorMsg;
        return updated;
      });
    } finally {
      setIsChatLoading(false);
    }
  }, [chatInput, note?.recordingId, isChatLoading, activeConversationId]);

  // Context menu handlers
  const handleRename = useCallback(async () => {
    if (!note?.recordingId) return;
    const newTitle = window.prompt('Enter new title:', recording?.title ?? note.title);
    if (!newTitle || newTitle === (recording?.title ?? note.title)) return;
    try {
      await apiClient.updateRecordingTitle(note.recordingId, newTitle);
      // Close modal to refresh — parent should refetch
      onClose();
    } catch {
      alert('Failed to rename recording.');
    }
    setContextMenu(null);
  }, [note?.recordingId, recording?.title, note?.title, onClose]);

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
      onClose(); // refresh
    } catch {
      alert('Failed to update date.');
    }
  }, [note?.recordingId, dateEditValue, onClose]);

  const handleExport = useCallback(async (format: 'txt' | 'srt' | 'ass' = 'txt') => {
    if (!note?.recordingId) return;
    const url = apiClient.getExportUrl(note.recordingId, format);
    window.open(url, '_blank');
    setContextMenu(null);
  }, [note?.recordingId]);

  const handleDelete = useCallback(async () => {
    if (!note?.recordingId) return;
    const confirmed = window.confirm(`Delete "${recording?.title ?? note.title}"? This cannot be undone.`);
    if (!confirmed) return;
    try {
      await apiClient.deleteRecording(note.recordingId);
      onClose();
    } catch {
      alert('Failed to delete recording.');
    }
    setContextMenu(null);
  }, [note?.recordingId, recording?.title, note?.title, onClose]);

  if (!isRendered || !note || !portalContainer) return null;

  return createPortal(
    <div className="fixed inset-0 z-9999 flex items-center justify-center p-4 lg:p-8">
      {/* Backdrop */}
      <div className={`absolute inset-0 bg-black/40 backdrop-blur-md transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`} onClick={onClose} />

      {/* Main Modal Container */}
      <div className={`relative w-full max-w-6xl h-[85vh] bg-glass-surface backdrop-blur-xl border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'}`}>
        
        {/* Left Section: Content & Player */}
        <div className="flex-1 flex flex-col min-w-0 bg-linear-to-b from-white/5 to-transparent">
            {/* Header */}
            <div className="flex-none h-20 px-8 border-b border-white/5 flex items-center justify-between select-none">
                <div>
                    <h2 className="text-2xl font-bold text-white tracking-tight">{recording?.title ?? note.title}</h2>
                    <div className="flex items-center gap-4 text-sm text-slate-400 mt-1">
                        <span className="flex items-center gap-1.5"><Clock size={14}/> {recording ? formatRecSecs(recording.duration_seconds) : note.duration}</span>
                        <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                        <span className="flex items-center gap-1.5"><FileText size={14}/> {recording ? `${recording.word_count.toLocaleString()} words` : '— words'}</span>
                        <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                        {isDateEditing ? (
                          <span className="flex items-center gap-1.5">
                            <input
                              type="datetime-local"
                              value={dateEditValue}
                              onChange={(e) => setDateEditValue(e.target.value)}
                              className="bg-white/10 border border-white/20 rounded px-2 py-0.5 text-sm text-white outline-none focus:ring-1 focus:ring-accent-cyan [color-scheme:dark]"
                              autoFocus
                            />
                            <button onClick={handleDateSave} className="p-0.5 hover:text-accent-cyan transition-colors"><Check size={14} /></button>
                            <button onClick={() => setIsDateEditing(false)} className="p-0.5 hover:text-red-400 transition-colors"><XCircle size={14} /></button>
                          </span>
                        ) : (
                          <span
                            className="text-slate-500 hover:text-slate-300 cursor-pointer transition-colors"
                            onClick={handleDateEditOpen}
                            title="Click to change date"
                          >
                            {recording ? new Date(recording.recorded_at).toLocaleString() : note.date ?? ''}
                          </span>
                        )}
                        {note.tag && <span className="ml-2 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20">{note.tag}</span>}
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {!isSidebarOpen && (
                        <>
                            <Button variant="secondary" className="h-10 transition-all text-slate-400 hover:text-white" onClick={() => setIsSidebarOpen(true)} icon={<MessageSquare size={18} />}>AI Assistant</Button>
                            <div className="w-px h-8 bg-white/10 mx-1"></div>
                        </>
                    )}
                    <button onClick={handleCloseAction} className="p-2 hover:bg-white/10 rounded-full text-slate-400 hover:text-white transition-colors"><X size={24} /></button>
                </div>
            </div>

            {/* Scrollable Body */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-8 space-y-8">
                {/* 1. Audio Player Card */}
                <div className="bg-black/20 rounded-2xl border border-white/5 p-6 relative overflow-hidden group select-none">
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
                         preload="metadata"
                       />
                     )}
                     <div className="absolute inset-0 flex items-center justify-center opacity-20 pointer-events-none gap-1">
                        {Array.from({ length: 60 }).map((_, i) => (
                            <div key={i} className="w-1 bg-accent-cyan rounded-full transition-all duration-300" style={{ height: `${20 + Math.random() * 60}%`, opacity: i > progress / 1.6 ? 0.3 : 1 }}></div>
                        ))}
                     </div>
                     <div className="relative z-10 flex flex-col items-center gap-4">
                        <div className="text-3xl font-mono text-white font-light tracking-widest">{formatRecSecs(currentTime)} <span className="text-slate-500 text-lg">/ {duration > 0 ? formatRecSecs(duration) : note.duration}</span></div>
                        <div className="flex items-center gap-6">
                            <button onClick={() => handleSeek(-10)} className="text-slate-400 hover:text-white transition-colors" title="Rewind 10s"><Rewind size={24} /></button>
                            <button onClick={handlePlayPause} disabled={!audioUrl} className="w-14 h-14 rounded-full bg-white text-black flex items-center justify-center hover:scale-105 active:scale-95 transition-all shadow-[0_0_20px_rgba(255,255,255,0.3)] disabled:opacity-50 disabled:cursor-not-allowed">{isPlaying ? <Pause size={24} fill="black" /> : <Play size={24} fill="black" className="ml-1" />}</button>
                            <button onClick={() => handleSeek(10)} className="text-slate-400 hover:text-white transition-colors" title="Forward 10s"><FastForward size={24} /></button>
                        </div>
                        {/* Seek bar */}
                        <input
                          type="range"
                          min={0}
                          max={duration || 100}
                          value={currentTime}
                          onChange={(e) => { if (audioRef.current) audioRef.current.currentTime = Number(e.target.value); }}
                          className="w-full max-w-xs h-1 accent-accent-cyan bg-white/10 rounded cursor-pointer"
                        />
                     </div>
                </div>

                {/* 2. AI Summary Section - Editable */}
                <div className={`transition-all duration-500 ease-in-out border border-white/10 rounded-2xl overflow-hidden ${summaryExpanded ? 'bg-linear-to-br from-accent-magenta/5 to-purple-900/10' : 'bg-glass-100 hover:bg-white/5'}`}>
                    {!summaryExpanded ? (
                        <button onClick={handleGenerateSummary} className="w-full h-14 flex items-center justify-center gap-3 text-accent-magenta hover:text-white transition-colors group select-none">
                            <Sparkles size={18} className="group-hover:animate-spin-slow" />
                            <span className="font-medium tracking-wide">Generate AI Summary</span>
                        </button>
                    ) : (
                        <div className="p-6 selectable-text">
                            <div className="flex items-center justify-between mb-3 select-none">
                                <div className="flex items-center gap-2 text-accent-magenta">
                                    <Sparkles size={16} />
                                    <span className="text-xs font-bold uppercase tracking-widest">AI Generated Summary</span>
                                </div>
                                <div className="flex items-center gap-1">
                                    {isGenerating && (
                                        <button onClick={handleStopGeneration} className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-red-400 transition-colors" title="Stop generation">
                                            <StopCircle size={14} />
                                        </button>
                                    )}
                                    {!isGenerating && summaryText && !isSummaryEditing && (
                                        <button onClick={handleEnterSummaryEdit} className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors" title="Edit summary">
                                            <Pencil size={14} />
                                        </button>
                                    )}
                                    {isSummaryEditing && (
                                        <>
                                            <button onClick={() => handleExitSummaryEdit(true)} className="p-1.5 rounded-lg hover:bg-white/10 text-green-400 hover:text-green-300 transition-colors" title="Save">
                                                <Check size={14} />
                                            </button>
                                            <button onClick={() => handleExitSummaryEdit(false)} className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors" title="Cancel editing">
                                                <XCircle size={14} />
                                            </button>
                                        </>
                                    )}
                                    {!isGenerating && summaryText && (
                                        <button onClick={handleClearSummary} className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-red-400 transition-colors" title="Clear summary">
                                            <Trash2 size={14} />
                                        </button>
                                    )}
                                    {isSummarySaving && (
                                        <Loader2 size={14} className="animate-spin text-accent-magenta ml-1" />
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
                                    className="w-full min-h-32 bg-black/20 border border-white/10 rounded-lg p-3 text-slate-200 leading-relaxed text-lg resize-y focus:outline-none focus:ring-1 focus:ring-accent-magenta/50 transition-all"
                                    placeholder="Edit summary..."
                                />
                            ) : (
                                <p className="text-slate-200 leading-relaxed text-lg cursor-text" onClick={handleEnterSummaryEdit}>
                                    {summaryText}
                                    {isGenerating && <span className="inline-block w-2 h-4 bg-accent-magenta ml-1 animate-pulse select-none"/>}
                                </p>
                            )}
                        </div>
                    )}
                </div>

                {/* 3. Transcript - Added selectable-text to paragraphs */}
                <div className="space-y-6">
                    <div className="sticky top-0 z-10 py-4 pointer-events-none select-none">
                        <span className="inline-flex items-center px-4 py-1.5 rounded-full bg-[#161f32]/90 backdrop-blur-xl border border-white/10 text-xs font-bold text-slate-400 uppercase tracking-widest shadow-lg pointer-events-auto">Transcript</span>
                    </div>
                    {segments.length > 0 ? segments.map((seg, i) => (
                        <div key={i} className="flex gap-6 group">
                            <div className="w-16 flex-none text-right pt-1 select-none">
                                {seg.speaker && <div className={`text-xs font-bold mb-1 ${speakerColor(seg.speaker)}`}>{seg.speaker}</div>}
                                <div className="text-[10px] text-slate-500 font-mono">{formatRecSecs(seg.start)}</div>
                            </div>
                            <div className="flex-1 text-slate-300 leading-relaxed group-hover:text-white transition-colors selectable-text">
                                {seg.words && seg.words.length > 0 ? (
                                  <p>
                                    {seg.words.map((w, wi) => (
                                      <span
                                        key={wi}
                                        onClick={() => {
                                          if (audioRef.current) {
                                            audioRef.current.currentTime = w.start;
                                            audioRef.current.play().catch(() => {});
                                          }
                                        }}
                                        className={`cursor-pointer rounded px-px transition-colors duration-150 hover:bg-accent-cyan/20 hover:text-accent-cyan ${
                                          audioRef.current && currentTime >= w.start && currentTime < w.end
                                            ? 'bg-accent-cyan/30 text-accent-cyan font-medium'
                                            : ''
                                        }`}
                                        title={`${formatRecSecs(w.start)} → ${formatRecSecs(w.end)}`}
                                      >{w.word}</span>
                                    ))}
                                  </p>
                                ) : (
                                  <p
                                    className="cursor-pointer hover:text-accent-cyan/80 transition-colors"
                                    onClick={() => {
                                      if (audioRef.current) {
                                        audioRef.current.currentTime = seg.start;
                                        audioRef.current.play().catch(() => {});
                                      }
                                    }}
                                    title={`Seek to ${formatRecSecs(seg.start)}`}
                                  >{seg.text}</p>
                                )}
                            </div>
                        </div>
                    )) : recordingLoading ? (
                        <div className="flex items-center justify-center py-12 text-slate-500">
                            <Loader2 size={20} className="animate-spin mr-2" /> Loading transcript…
                        </div>
                    ) : (
                        <div className="text-center py-12 text-slate-500">No transcript available</div>
                    )}
                </div>
            </div>
        </div>

        {/* Right Section: LLM Sidebar - Chat messages marked selectable */}
        <div className={`transition-all duration-500 ease-[cubic-bezier(0.33,1,0.68,1)] border-l border-white/5 bg-[#0b1120] flex flex-col ${isSidebarOpen ? 'w-100 translate-x-0' : 'w-0 translate-x-10 opacity-0 overflow-hidden'}`}>
             <div className="h-20 border-b border-white/5 flex items-center justify-between px-5 shrink-0 bg-white/2 select-none">
                <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-green-500/10 text-green-400"><Bot size={18} /></div>
                    <div>
                        <div className="text-sm font-semibold text-white">LM Studio</div>
                        <div className="flex items-center gap-1.5">
                            <StatusLight status={llmStatus} className="w-1.5 h-1.5" animate={llmStatus === 'active'} />
                            <span className="text-[10px] text-slate-400 uppercase tracking-wider">{llmStatus === 'active' ? 'Online' : 'Offline'}</span>
                        </div>
                    </div>
                </div>
             </div>
             <div className="flex-1 flex flex-col min-w-100 overflow-hidden">
                <div className="flex-none p-2 border-b border-white/5 bg-white/1 select-none">
                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-3 py-2">Sessions</div>
                    <div className="space-y-1">
                        {chatSessions.map((session) => (
                            <div key={session.id} onContextMenu={(e) => handleContextMenu(e, session.id)} className={`group flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${session.active ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'}`}>
                                <div className={`shrink-0 ${session.type === 'summary' ? 'text-accent-magenta' : 'text-accent-cyan'}`}>{session.type === 'summary' ? <Sparkles size={14} /> : <MessageSquare size={14} />}</div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-xs font-medium truncate">{session.title}</div>
                                    <div className="text-[10px] text-slate-500">{session.timestamp}</div>
                                </div>
                                {session.active && <div className="w-1.5 h-1.5 rounded-full bg-accent-cyan shadow-[0_0_5px_rgba(239,22,238,0.5)]"></div>}
                            </div>
                        ))}
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
                    <div className="text-center text-xs text-slate-600 my-4 select-none">Current Session</div>
                    
                    {/* Welcome message */}
                    <div className="flex gap-3 pr-8">
                        <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center shrink-0 select-none"><Bot size={14} className="text-white" /></div>
                        <div className="bg-white/5 rounded-2xl rounded-tl-none p-3 border border-white/5 selectable-text">
                            <p className="text-sm text-slate-300">Hello! I've loaded the context for <span className="text-accent-cyan font-medium select-none">"{note.title}"</span>. Ask me anything about the speakers or topics discussed.</p>
                        </div>
                    </div>

                    {/* Dynamic chat messages */}
                    {chatMessages.map((msg, idx) => (
                      msg.role === 'user' ? (
                        <div key={idx} className="flex gap-3 pl-8 flex-row-reverse">
                            <div className="w-8 h-8 rounded-full bg-accent-cyan/20 flex items-center justify-center shrink-0 select-none"><User size={14} className="text-accent-cyan" /></div>
                            <div className="bg-accent-cyan/10 rounded-2xl rounded-tr-none p-3 border border-accent-cyan/10 selectable-text">
                                <p className="text-sm text-white">{msg.content}</p>
                            </div>
                        </div>
                      ) : (
                        <div key={idx} className="flex gap-3 pr-8">
                            <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center shrink-0 select-none"><Bot size={14} className="text-white" /></div>
                            <div className="bg-white/5 rounded-2xl rounded-tl-none p-3 border border-white/5 selectable-text">
                                <p className="text-sm text-slate-300 whitespace-pre-wrap">{msg.content || (isChatLoading ? <Loader2 size={14} className="animate-spin" /> : '')}</p>
                            </div>
                        </div>
                      )
                    ))}
                </div>

                {/* Input Area */}
                <div className="p-4 border-t border-white/5 bg-white/2">
                    <div className="relative">
                        <input 
                          type="text" 
                          placeholder="Ask about this note..." 
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); } }}
                          disabled={isChatLoading || !note?.recordingId}
                          className="w-full bg-black/20 border border-white/10 rounded-xl py-3 pl-4 pr-12 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-accent-cyan/50 focus:ring-1 focus:ring-accent-cyan/20 transition-all disabled:opacity-50" 
                        />
                        <button onClick={handleSendMessage} disabled={isChatLoading || !chatInput.trim()} className="absolute right-2 top-2 p-1.5 bg-accent-cyan rounded-lg text-black hover:bg-cyan-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"><Send size={14} /></button>
                    </div>
                    <div className="mt-2 flex justify-between items-center px-1 select-none">
                        <span className="text-[10px] text-slate-500">Model: {llmModel ?? 'unknown'}</span>
                        <span className="text-[10px] text-slate-500">{segments.length} segments context</span>
                    </div>
                </div>
             </div>
        </div>

      </div>

      {/* Context Menu Portal */}
      {contextMenu && (
        <div className="fixed z-10000 w-48 bg-[#0f172a] border border-white/10 rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-100 py-1 select-none" style={{ top: contextMenu.y, left: contextMenu.x }} onClick={(e) => e.stopPropagation()}>
            <button onClick={handleRename} className="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2"><Edit2 size={14} /> Rename</button>
            <button onClick={() => handleExport('txt')} className="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2"><Share size={14} /> Export TXT</button>
            <button onClick={() => handleExport('srt')} className="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2"><Share size={14} /> Export SRT</button>
            <button onClick={() => handleExport('ass')} className="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2"><Share size={14} /> Export ASS</button>
            <div className="h-px bg-white/10 my-1"></div>
            <button onClick={handleDelete} className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300 flex items-center gap-2"><Trash2 size={14} /> Delete</button>
        </div>
      )}
    </div>,
    portalContainer
  );
};
