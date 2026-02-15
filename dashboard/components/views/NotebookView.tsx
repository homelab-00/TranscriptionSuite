
import React, { useState, useEffect, useRef, useLayoutEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { NotebookTab } from '../../types';
import { Calendar, Search, Upload, Filter, FileText, Trash2, Download, Clock, MoreHorizontal, Play, ChevronLeft, ChevronRight, Check, Plus, Mic, Minus, CalendarDays, Edit2, Share, Loader2 } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { AudioNoteModal } from './AudioNoteModal';
import { AddNoteModal } from './AddNoteModal';
import { useCalendar } from '../../src/hooks/useCalendar';
import { useSearch } from '../../src/hooks/useSearch';
import { useUpload } from '../../src/hooks/useUpload';
import { apiClient } from '../../src/api/client';
import type { Recording } from '../../src/api/types';

export const NotebookView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NotebookTab>(NotebookTab.CALENDAR);
  
  // Audio Modal State (Existing Note)
  const [selectedNote, setSelectedNote] = useState<any>(null);
  const [isNoteModalOpen, setIsNoteModalOpen] = useState(false);

  // Add Note Modal State (New Note)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [selectedTimeSlot, setSelectedTimeSlot] = useState<number | undefined>(undefined);

  const handleNoteClick = (noteData: any) => {
    setSelectedNote(noteData);
    setIsNoteModalOpen(true);
  };

  const handleAddNote = (time: number) => {
    setSelectedTimeSlot(time);
    setIsAddModalOpen(true);
  };

  const renderContent = () => {
    switch (activeTab) {
      case NotebookTab.CALENDAR:
        return <CalendarTab onNoteClick={handleNoteClick} onAddNote={handleAddNote} />;
      case NotebookTab.SEARCH:
        return <SearchTab onNoteClick={handleNoteClick} />;
      case NotebookTab.IMPORT:
        return <ImportTab />;
    }
  };

  return (
    <div className="flex flex-col h-full space-y-6 max-w-7xl mx-auto w-full p-6">
      <div className="flex items-center justify-between flex-none">
         <h1 className="text-3xl font-bold text-white tracking-tight">Audio Notebook</h1>
         <div className="flex bg-glass-200 backdrop-blur-md p-1 rounded-lg border border-white/5">
            {[
                { id: NotebookTab.CALENDAR, icon: <Calendar size={16} />, label: 'Calendar' },
                { id: NotebookTab.SEARCH, icon: <Search size={16} />, label: 'Search' },
                { id: NotebookTab.IMPORT, icon: <Upload size={16} />, label: 'Import' },
            ].map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                        activeTab === tab.id 
                        ? 'bg-white/10 text-white shadow-sm' 
                        : 'text-slate-400 hover:text-white'
                    }`}
                >
                    {tab.icon}
                    <span>{tab.label}</span>
                </button>
            ))}
         </div>
      </div>
      
      <div className="flex-1 min-h-0 relative animate-in fade-in slide-in-from-bottom-2 duration-300">
        {renderContent()}
      </div>

      {/* View/Edit Audio Note Overlay */}
      <AudioNoteModal 
        isOpen={isNoteModalOpen} 
        onClose={() => setIsNoteModalOpen(false)} 
        note={selectedNote}
      />

      {/* Add New Note Overlay */}
      <AddNoteModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        initialTime={selectedTimeSlot}
      />
    </div>
  );
};

// --- Helper: Context Menu Portal ---
interface MenuTrigger {
    type: 'rect' | 'point';
    rect?: DOMRect;
    x?: number;
    y?: number;
}

interface MenuProps {
    trigger: MenuTrigger;
    onClose: () => void;
    noteId: string;
    onRefresh: () => void;
    onPlay: (id: string) => void;
}

const NoteActionMenu: React.FC<MenuProps> = ({ trigger, onClose, noteId, onRefresh, onPlay }) => {
    const recordingId = parseInt(noteId, 10);

    const handlePlay = () => {
        onPlay(noteId);
        onClose();
    };

    const handleRename = async () => {
        const newTitle = window.prompt('Enter new title:');
        if (!newTitle) return;
        try {
            await apiClient.updateRecordingTitle(recordingId, newTitle);
            onRefresh();
        } catch {
            alert('Failed to rename recording.');
        }
        onClose();
    };

    const handleExport = (format: 'txt' | 'srt' | 'ass') => {
        const url = apiClient.getExportUrl(recordingId, format);
        window.open(url, '_blank');
        onClose();
    };

    const handleDelete = async () => {
        if (!window.confirm('Delete this recording? This cannot be undone.')) return;
        try {
            await apiClient.deleteRecording(recordingId);
            onRefresh();
        } catch {
            alert('Failed to delete recording.');
        }
        onClose();
    };
    const menuRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState<{ top: number, left: number } | null>(null);
    const [animationStyle, setAnimationStyle] = useState<React.CSSProperties>({});

    useLayoutEffect(() => {
        if (!menuRef.current) return;
        const menuRect = menuRef.current.getBoundingClientRect();
        const { innerWidth, innerHeight } = window;
        const PADDING = 10;
        let top = 0;
        let left = 0;
        if (trigger.type === 'rect' && trigger.rect) {
            top = trigger.rect.bottom + 5;
            left = trigger.rect.left;
        } else if (trigger.type === 'point' && trigger.x !== undefined && trigger.y !== undefined) {
            top = trigger.y + 5;
            left = trigger.x + 5;
        }
        if (left + menuRect.width > innerWidth - PADDING) {
            if (trigger.type === 'rect' && trigger.rect) { left = trigger.rect.right - menuRect.width; } 
            else { left = (trigger.x || 0) - menuRect.width - 5; }
        }
        if (top + menuRect.height > innerHeight - PADDING) {
            if (trigger.type === 'rect' && trigger.rect) { top = trigger.rect.top - menuRect.height - 5; } 
            else { top = (trigger.y || 0) - menuRect.height - 5; }
        }
        if (left < PADDING) { left = PADDING; }
        setPosition({ top, left });
        const distFromBottom = innerHeight - top;
        setAnimationStyle({ '--enter-translate-y': `${distFromBottom}px` } as React.CSSProperties);
    }, [trigger]);

    const slideUpKeyframes = `
        @keyframes slideUpFromBottomEdge {
            from { transform: translateY(var(--enter-translate-y, 100vh)); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
    `;

    return createPortal(
        <div className="fixed inset-0 z-[9999]" onClick={(e) => { e.stopPropagation(); onClose(); }} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
            <style>{slideUpKeyframes}</style>
            <div 
                ref={menuRef}
                className="absolute w-44 bg-black/50 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl py-1.5 origin-top-left"
                style={{
                    top: position ? position.top : 0,
                    left: position ? position.left : 0,
                    opacity: position ? 1 : 0,
                    ...animationStyle,
                    animation: position ? 'slideUpFromBottomEdge 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards' : 'none'
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <button onClick={handlePlay} className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2.5 transition-colors group">
                    <Play size={14} className="group-hover:text-accent-cyan" />
                    Play Recording
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button onClick={handleRename} className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2.5 transition-colors">
                    <Edit2 size={14} />
                    Rename
                </button>
                <button onClick={() => handleExport('txt')} className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2.5 transition-colors">
                    <Download size={14} />
                    Export TXT
                </button>
                <button onClick={() => handleExport('srt')} className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2.5 transition-colors">
                    <Download size={14} />
                    Export SRT
                </button>
                <button onClick={() => handleExport('ass')} className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2.5 transition-colors">
                    <Download size={14} />
                    Export ASS
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button onClick={handleDelete} className="w-full text-left px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 hover:text-red-300 flex items-center gap-2.5 transition-colors">
                    <Trash2 size={14} />
                    Delete
                </button>
            </div>
        </div>,
        document.body
    );
};

// --- History / Month Picker ---
interface HistoryPickerProps { isOpen: boolean; onClose: () => void; selectedDate: Date; onSelect: (date: Date) => void; triggerRect: DOMRect | null; }

const HistoryPicker: React.FC<HistoryPickerProps> = ({ isOpen, onClose, selectedDate, onSelect, triggerRect }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [viewYear, setViewYear] = useState(selectedDate.getFullYear());

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;
    if (isOpen) {
      setIsRendered(true);
      setViewYear(selectedDate.getFullYear());
      rafId = requestAnimationFrame(() => { rafId = requestAnimationFrame(() => { setIsVisible(true); }); });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 300);
    }
    return () => { clearTimeout(timer); cancelAnimationFrame(rafId); };
  }, [isOpen, selectedDate]);

  if (!isRendered) return null;
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const handleMonthSelect = (monthIndex: number) => { const newDate = new Date(viewYear, monthIndex, 1); onSelect(newDate); onClose(); };
  const positionStyle: React.CSSProperties = triggerRect ? { position: 'fixed', top: `${triggerRect.top}px`, right: `${window.innerWidth - triggerRect.right}px`, transformOrigin: 'top right' } : {};

  return createPortal(
    <div className="fixed inset-0 z-[9999]">
      <div className="absolute inset-0" onClick={onClose} />
      <div style={positionStyle} className={`w-80 bg-black/10 backdrop-blur-xl border border-white/10 rounded-xl shadow-xl p-6 transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'opacity-100 scale-100 translate-y-0' : 'opacity-0 scale-95 -translate-y-2'}`}>
        <div className="flex items-center justify-between mb-6">
            <button onClick={() => setViewYear(viewYear - 1)} className="p-2 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition-colors"><ChevronLeft size={20} /></button>
            <div className="text-xl font-bold text-white tracking-tight font-mono">{viewYear}</div>
            <button onClick={() => setViewYear(viewYear + 1)} className="p-2 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition-colors"><ChevronRight size={20} /></button>
        </div>
        <div className="grid grid-cols-3 gap-3">
            {months.map((month, index) => {
                const isSelected = selectedDate.getMonth() === index && selectedDate.getFullYear() === viewYear;
                const isCurrentMonth = new Date().getMonth() === index && new Date().getFullYear() === viewYear;
                return (
                    <button key={month} onClick={() => handleMonthSelect(index)} className={`relative h-10 rounded-xl text-sm font-medium transition-all duration-200 flex items-center justify-center ${isSelected ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.4)] font-bold scale-105 z-10' : 'text-slate-300 hover:bg-white/10 hover:text-white hover:scale-105'}`}>
                        {month.slice(0, 3)}
                        {isCurrentMonth && !isSelected && <div className="absolute bottom-1 w-1 h-1 rounded-full bg-accent-cyan"></div>}
                    </button>
                );
            })}
        </div>
        <div className="mt-6 pt-4 border-t border-white/10 flex justify-center">
             <button onClick={() => { const now = new Date(); onSelect(new Date(now.getFullYear(), now.getMonth(), 1)); onClose(); }} className="text-xs font-medium text-accent-cyan hover:text-cyan-300 uppercase tracking-widest transition-colors">Jump to Today</button>
        </div>
      </div>
    </div>,
    document.body
  );
};

// --- Sub-components for Calendar View ---
interface EventData { id: string; title: string; duration?: string; tag?: string; startTime: number; recordingId?: number; }

const TimeSection: React.FC<{ title: string; headerColor: string; headerGradient: string; startHour: number; endHour: number; events: EventData[]; visibleSlots: number; onZoomChange: (slots: number) => void; onNoteClick: (note: EventData) => void; onAddNote: (hour: number) => void; onRefresh: () => void; }> = ({ title, headerColor, headerGradient, startHour, endHour, events, visibleSlots, onZoomChange, onNoteClick, onAddNote, onRefresh }) => {
    const hours = Array.from({ length: endHour - startHour }, (_, i) => startHour + i);
    const [activeMenu, setActiveMenu] = useState<{ id: string, trigger: MenuTrigger } | null>(null);
    const isCompact = visibleSlots >= 4;
    const handleContextMenu = (e: React.MouseEvent, evt: EventData) => { e.preventDefault(); setActiveMenu({ id: evt.id, trigger: { type: 'point', x: e.clientX, y: e.clientY } }); };
    return (
        <div className="flex-1 bg-glass-surface backdrop-blur-xl border border-glass-border rounded-2xl overflow-hidden flex flex-col min-h-0 shadow-xl">
            <div className={`shrink-0 h-14 px-5 border-b border-white/5 backdrop-blur-md z-10 flex justify-between items-center ${headerGradient}`}>
                <h3 className={`font-semibold tracking-tight ${headerColor}`}>{title}</h3>
                <div className="flex items-center gap-1 bg-black/20 rounded-lg p-0.5 border border-white/5">
                    <button onClick={() => onZoomChange(Math.max(2, visibleSlots - 1))} className="p-1 hover:bg-white/10 rounded text-slate-400 hover:text-white transition-colors"><Minus size={14} /></button>
                    <button onClick={() => onZoomChange(Math.min(4, visibleSlots + 1))} className="p-1 hover:bg-white/10 rounded text-slate-400 hover:text-white transition-colors"><Plus size={14} /></button>
                </div>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar relative h-full">
                <div className="h-full">
                    {hours.map((hour) => {
                        const hourEvents = events.filter(e => Math.floor(e.startTime) === hour);
                        return (
                            <div key={hour} className="flex group relative border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors duration-300" style={{ height: `${100 / visibleSlots}%` }}>
                                <div className="w-16 shrink-0 text-right pr-4 pt-6 select-none sticky left-0 z-20">
                                    <span className="text-xs font-medium text-slate-500 font-mono">{hour.toString().padStart(2, '0')}:00</span>
                                </div>
                                <div className="flex-1 relative overflow-x-auto custom-scrollbar flex items-center pr-6 pl-0 gap-3 snap-x snap-mandatory mask-gradient-right h-full">
                                    {hourEvents.map((evt) => {
                                        const minutes = Math.round((evt.startTime % 1) * 60).toString().padStart(2, '0');
                                        const timeStr = `${Math.floor(evt.startTime).toString().padStart(2, '0')}:${minutes}`;
                                        return (
                                            <div key={evt.id} onClick={() => onNoteClick(evt)} onContextMenu={(e) => handleContextMenu(e, evt)} className="snap-start flex-none w-[140px] p-3 rounded-xl bg-glass-200 border border-white/10 hover:bg-glass-300 transition-all duration-300 group/card cursor-pointer relative overflow-hidden shadow-sm hover:shadow-lg hover:border-white/20 hover:-translate-y-1 active:scale-[0.98] h-[85%]">
                                                <div className="absolute left-0 top-0 bottom-0 w-1 bg-accent-cyan opacity-80 group-hover/card:opacity-100 transition-opacity"></div>
                                                <div className="flex flex-col h-full justify-between gap-2">
                                                    <div className="flex justify-between items-start">
                                                        <div className="bg-black/30 px-1.5 py-0.5 rounded text-[9px] font-mono text-slate-400">{timeStr}</div>
                                                        {!isCompact && evt.tag === 'Diarized' && <div className="text-[8px] font-bold uppercase tracking-wider px-1 py-0.5 rounded border bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20">AI</div>}
                                                    </div>
                                                    <div className="min-h-0">
                                                        <h4 className={`text-xs font-medium text-white leading-snug mb-1 ${isCompact ? 'line-clamp-1' : 'line-clamp-2'}`}>{evt.title}</h4>
                                                        {!isCompact && evt.duration && <div className="text-[9px] text-slate-400 flex items-center gap-1"><Clock size={9} />{evt.duration}</div>}
                                                    </div>
                                                    {!isCompact && (
                                                        <div className="flex items-center justify-end opacity-0 group-hover/card:opacity-100 transition-opacity pt-1.5 border-t border-white/5 mt-auto gap-2">
                                                            <button onClick={(e) => { e.stopPropagation(); const rect = e.currentTarget.getBoundingClientRect(); setActiveMenu({ id: evt.id, trigger: { type: 'rect', rect } }); }} className="p-1 hover:bg-white/10 rounded-full text-slate-300 hover:text-white transition-colors"><MoreHorizontal size={12} /></button>
                                                            <button className="p-1 hover:bg-white/10 rounded-full text-slate-300 hover:text-white transition-colors" onClick={(e) => e.stopPropagation()} ><Play size={10} fill="currentColor" /></button>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                    <div className={`snap-start flex items-center ${hourEvents.length === 0 ? 'w-full h-full flex-none justify-start' : 'flex-1 min-w-[50px] h-[85%] justify-center'}`}>
                                        <button onClick={() => onAddNote(hour)} className={`rounded-xl border border-dashed border-white/10 flex flex-col items-center justify-center gap-2 hover:border-accent-cyan/50 hover:bg-accent-cyan/5 transition-all duration-300 group/add ${hourEvents.length === 0 ? 'w-full h-[90%]' : 'w-full h-full opacity-100'}`} >
                                            <div className={`rounded-full bg-white/5 flex items-center justify-center transition-all duration-300 group-hover/add:bg-accent-cyan group-hover/add:text-black group-hover/add:scale-110 shadow-lg ${hourEvents.length === 0 ? 'w-10 h-10' : 'w-7 h-7'}`}><Plus size={hourEvents.length === 0 ? 20 : 14} /></div>
                                            {hourEvents.length === 0 && <span className="text-xs font-medium text-slate-400 group-hover/add:text-white transition-colors">Add Note</span>}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
            {activeMenu && <NoteActionMenu trigger={activeMenu.trigger} onClose={() => setActiveMenu(null)} noteId={activeMenu.id} onRefresh={onRefresh} onPlay={(id) => { const evt = events.find(e => e.id === id); if (evt) onNoteClick(evt); }} />}
        </div>
    );
}

/** Convert seconds to a human-readable duration string */
const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s.toString().padStart(2, '0')}s`;
};

/** Convert a Recording to an EventData for the TimeSection cards */
const recordingToEvent = (rec: Recording): EventData => {
    const d = new Date(rec.recorded_at);
    const startTime = d.getHours() + d.getMinutes() / 60;
    return {
        id: String(rec.id),
        title: rec.title || rec.filename,
        startTime,
        duration: formatDuration(rec.duration_seconds),
        tag: rec.has_diarization ? 'Diarized' : undefined,
        recordingId: rec.id,
    };
};

const CalendarTab: React.FC<{onNoteClick: (note: any) => void, onAddNote: (hour: number) => void }> = ({ onNoteClick, onAddNote }) => {
    const [currentDate, setCurrentDate] = useState(() => new Date()); 
    const [selectedDay, setSelectedDay] = useState<string | null>(null);
    const [isHistoryOpen, setIsHistoryOpen] = useState(false);
    const [triggerRect, setTriggerRect] = useState<DOMRect | null>(null);
    const gridRef = useRef<HTMLDivElement>(null);
    const [slideDirection, setSlideDirection] = useState<'left' | 'right' | null>(null);
    const [animKey, setAnimKey] = useState(0);
    const [visibleSlots, setVisibleSlots] = useState(3); 
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth(); 
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDay = new Date(year, month, 1).getDay();
    const startOffset = (firstDay + 6) % 7; 
    const emptyDays = Array.from({ length: startOffset });
    const monthDays = Array.from({ length: daysInMonth });
    const monthTitle = currentDate.toLocaleString('default', { month: 'long', year: 'numeric' });
    const handlePrevMonth = (e: React.MouseEvent) => { e.stopPropagation(); setSlideDirection('left'); setAnimKey(prev => prev + 1); setCurrentDate(new Date(year, month - 1, 1)); setSelectedDay(null); };
    const handleNextMonth = (e: React.MouseEvent) => { e.stopPropagation(); setSlideDirection('right'); setAnimKey(prev => prev + 1); setCurrentDate(new Date(year, month + 1, 1)); setSelectedDay(null); };
    const calendarHeader = ( <div className="flex items-center gap-3"><span>{monthTitle}</span><div className="flex items-center bg-white/5 rounded-full border border-white/10 p-0.5 ml-1"><button onClick={handlePrevMonth} className="p-1 hover:bg-white/10 rounded-full text-slate-400 hover:text-white transition-colors"><ChevronLeft size={14} /></button><button onClick={handleNextMonth} className="p-1 hover:bg-white/10 rounded-full text-slate-400 hover:text-white transition-colors"><ChevronRight size={14} /></button></div></div> );

    // Live calendar data from API
    const calendar = useCalendar(year, month);

    // Build calendar grid: day-of-month (1-indexed) → array of recording summaries
    const eventsByDay: Record<number, { title: string; id: number }[]> = useMemo(() => {
        const result: Record<number, { title: string; id: number }[]> = {};
        for (const [dateKey, recordings] of Object.entries(calendar.days)) {
            const day = new Date(dateKey).getDate();
            result[day] = recordings.map(r => ({ title: r.title || r.filename, id: r.id }));
        }
        return result;
    }, [calendar.days]);

    // Recordings for the currently selected day, split into morning/afternoon
    const selectedDayRecordings = useMemo<Recording[]>(() => {
        if (!selectedDay || !calendar.days[selectedDay]) return [];
        return calendar.days[selectedDay];
    }, [selectedDay, calendar.days]);

    const morningEvents: EventData[] = useMemo(
        () => selectedDayRecordings.filter(r => new Date(r.recorded_at).getHours() < 12).map(recordingToEvent),
        [selectedDayRecordings],
    );
    const afternoonEvents: EventData[] = useMemo(
        () => selectedDayRecordings.filter(r => new Date(r.recorded_at).getHours() >= 12).map(recordingToEvent),
        [selectedDayRecordings],
    );

    // Auto-select today if it has events and nothing else is selected
    useEffect(() => {
        if (selectedDay) return;
        const todayKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`;
        if (calendar.days[todayKey]?.length) setSelectedDay(todayKey);
    }, [calendar.days, selectedDay, year, month]);

    const handleDayClick = (dayOfMonth: number) => {
        const key = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayOfMonth).padStart(2, '0')}`;
        setSelectedDay(key);
    };

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full min-h-0">
            <style>{`
                @keyframes slideInRight { from { transform: translateX(20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                @keyframes slideInLeft { from { transform: translateX(-20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                .anim-slide-right { animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
                .anim-slide-left { animation: slideInLeft 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
            `}</style>
            <div className="lg:col-span-2 flex flex-col min-h-0">
                <GlassCard className="flex flex-col h-full" title={calendarHeader} action={ <div className="flex gap-2"><Button variant="ghost" size="sm" icon={<Clock size={14}/>} onClick={() => { if (gridRef.current) { setTriggerRect(gridRef.current.getBoundingClientRect()); setIsHistoryOpen(true); } }} className={isHistoryOpen ? 'bg-white/10 text-white' : ''} >Month/Year</Button></div> } >
                    <div ref={gridRef} key={animKey} className={`grid grid-cols-7 grid-rows-[auto_repeat(5,1fr)] gap-px bg-white/5 rounded-2xl overflow-hidden border border-white/10 h-full ${slideDirection === 'right' ? 'anim-slide-right' : ''} ${slideDirection === 'left' ? 'anim-slide-left' : ''}`} >
                        {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((d, i) => ( <div key={i} className="py-1 text-center text-[10px] font-bold text-slate-500 bg-glass-100/50 uppercase tracking-widest border-b border-white/5 flex items-center justify-center">{d.slice(0, 3)}</div> ))}
                        {emptyDays.map((_, i) => ( <div key={`empty-${i}`} className="bg-glass-100/10 border-t border-r border-white/5"></div> ))}
                        {monthDays.map((_, i) => {
                            const dayNum = i + 1;
                            const dayEvents = eventsByDay[dayNum] || [];
                            const hasEvents = dayEvents.length > 0;
                            const count = dayEvents.length;
                            const dayKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`;
                            const isSelected = selectedDay === dayKey;
                            return (
                                <div key={i} className={`bg-glass-100/30 hover:bg-glass-100 transition-colors p-2 relative group cursor-pointer border-t border-r border-white/5 flex flex-col items-start min-h-0 overflow-hidden ${isSelected ? 'ring-1 ring-accent-cyan/50 bg-accent-cyan/5' : ''}`} onClick={() => handleDayClick(dayNum)} >
                                    <div className="flex justify-between items-center w-full mb-1">
                                        <span className={`text-xs w-6 h-6 flex items-center justify-center rounded-full transition-all shrink-0 ${isSelected ? 'bg-accent-cyan text-black font-bold' : hasEvents ? 'bg-[rgb(230,230,230)] text-black font-bold' : 'text-slate-400 group-hover:text-white'}`}>{dayNum}</span>
                                        {hasEvents && <div className="flex items-center justify-center px-2 h-4 min-w-[24px] rounded-full bg-red-500 shadow-[0_0_5px_rgba(239,68,68,0.6)] mr-1"><span className="text-[9px] text-white font-bold leading-none">{count}</span></div>}
                                    </div>
                                    <div className="flex-1 w-full min-h-0 flex flex-col gap-1 overflow-hidden pt-1">
                                        {dayEvents.slice(0, 2).map((evt, idx) => ( <div key={idx} className="px-2 py-0.5 rounded-full bg-accent-cyan text-black text-[10px] font-medium truncate w-full shadow-sm">{evt.title}</div> ))}
                                        {dayEvents.length > 2 && <div className="text-[9px] text-slate-500 pl-2">+{dayEvents.length - 2} more</div>}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </GlassCard>
            </div>
            <div className="flex flex-col space-y-4 h-full min-h-0 overflow-hidden">
                <TimeSection title="Morning" headerColor="text-accent-orange" headerGradient="bg-gradient-to-r from-accent-orange/10 via-red-900/10 to-transparent" startHour={0} endHour={12} events={morningEvents} visibleSlots={visibleSlots} onZoomChange={setVisibleSlots} onNoteClick={onNoteClick} onAddNote={onAddNote} onRefresh={calendar.refresh} />
                <TimeSection title="Afternoon" headerColor="text-indigo-400" headerGradient="bg-gradient-to-r from-indigo-500/10 via-blue-900/10 to-transparent" startHour={12} endHour={24} events={afternoonEvents} visibleSlots={visibleSlots} onZoomChange={setVisibleSlots} onNoteClick={onNoteClick} onAddNote={onAddNote} onRefresh={calendar.refresh} />
            </div>
            <HistoryPicker isOpen={isHistoryOpen} onClose={() => setIsHistoryOpen(false)} selectedDate={currentDate} onSelect={setCurrentDate} triggerRect={triggerRect} />
        </div>
    );
};

const SearchTab: React.FC<{onNoteClick: (note: any) => void}> = ({ onNoteClick }) => {
    const [query, setQuery] = useState('');
    const [fuzzy, setFuzzy] = useState(true);
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const { results, count, loading, error, search } = useSearch();

    // Trigger search whenever inputs change
    useEffect(() => {
        search(query, {
            fuzzy,
            startDate: startDate || undefined,
            endDate: endDate || undefined,
        });
    }, [query, fuzzy, startDate, endDate, search]);

    return (
    <div className="max-w-3xl mx-auto space-y-6">
        <div className="relative">
            <Search className="absolute left-4 top-3.5 text-slate-400" size={20} />
            <input 
                type="text" 
                placeholder="Search transcripts, speakers, or dates..." 
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-glass-100 border border-white/10 rounded-xl py-3 pl-12 pr-4 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent-cyan transition-all"
            />
            {loading && <Loader2 className="absolute right-4 top-3.5 text-accent-cyan animate-spin" size={20} />}
        </div>
        
        <GlassCard>
            <div className="flex items-center gap-6 pb-4 border-b border-white/5">
                <div className="flex items-center gap-2"><Filter size={16} className="text-slate-400" /><span className="text-sm font-medium">Filters:</span></div>
                <AppleSwitch checked={fuzzy} onChange={setFuzzy} label="Fuzzy Search" size="sm" />
                <div className="h-6 w-px bg-white/10"></div>
                <div className="flex gap-2">
                    <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs text-slate-300" />
                    <span className="text-slate-500 text-sm">-</span>
                    <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs text-slate-300" />
                </div>
            </div>
            
            <div className="mt-4 space-y-2 selectable-text">
                {error && <div className="text-xs text-red-400 mb-3">{error}</div>}
                {!query.trim() ? (
                    <div className="text-center text-sm text-slate-500 py-8">Enter a search term to find recordings</div>
                ) : count === 0 && !loading ? (
                    <div className="text-center text-sm text-slate-500 py-8">No results found for &ldquo;{query}&rdquo;</div>
                ) : (
                    <>
                        <div className="text-xs text-slate-500 uppercase tracking-widest mb-3 select-none">{count} Result{count !== 1 ? 's' : ''} found</div>
                        {results.map((r, i) => (
                            <div 
                                key={`${r.recording_id}-${r.id ?? i}`}
                                onClick={() => onNoteClick({ 
                                    title: r.title || r.filename, 
                                    recordingId: r.recording_id,
                                    duration: '',
                                    tag: r.match_type,
                                })}
                                className="p-4 rounded-lg bg-white/5 border border-white/5 hover:bg-white/10 transition-colors cursor-pointer group"
                            >
                                <div className="flex justify-between items-start mb-1 select-none">
                                    <div className="flex items-center gap-2">
                                        <FileText size={16} className="text-accent-cyan" />
                                        <span className="font-medium text-white">{r.title || r.filename}</span>
                                        {r.speaker && <span className="text-xs text-slate-500">({r.speaker})</span>}
                                    </div>
                                    <span className="text-xs text-slate-500">{new Date(r.recorded_at).toLocaleDateString()}</span>
                                </div>
                                <p className="text-sm text-slate-400 pl-6 line-clamp-2">
                                    {r.context ? (
                                        <>...{r.context.split(r.word).map((part, pi, arr) => (
                                            <React.Fragment key={pi}>
                                                {part}
                                                {pi < arr.length - 1 && <span className="text-accent-orange bg-accent-orange/10 rounded px-1">{r.word}</span>}
                                            </React.Fragment>
                                        ))}...</>
                                    ) : r.word}
                                </p>
                            </div>
                        ))}
                    </>
                )}
            </div>
        </GlassCard>
    </div>
    );
};

const ImportTab = () => {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [diarization, setDiarization] = useState(true);
    const [wordTimestamps, setWordTimestamps] = useState(false);
    const [isDragOver, setIsDragOver] = useState(false);
    const { status, result, error, upload, reset } = useUpload();

    const handleFiles = useCallback((files: FileList | null) => {
        if (!files || files.length === 0) return;
        const file = files[0];
        upload(file, {
            enable_diarization: diarization,
            enable_word_timestamps: wordTimestamps,
        });
    }, [diarization, wordTimestamps, upload]);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragOver(false);
        handleFiles(e.dataTransfer.files);
    }, [handleFiles]);

    return (
    <div className="max-w-2xl mx-auto space-y-8 mt-10">
        <input
            ref={fileInputRef}
            type="file"
            accept=".mp3,.wav,.m4a,.flac,.ogg,.webm,.opus"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
        />

        {status === 'success' && result ? (
            <div className="border-2 border-green-500/30 rounded-3xl p-12 flex flex-col items-center justify-center text-center bg-green-500/5">
                <div className="w-16 h-16 bg-green-500/10 rounded-full flex items-center justify-center mb-4">
                    <Check size={32} className="text-green-400" />
                </div>
                <h3 className="text-xl font-semibold text-white mb-2">Upload Complete</h3>
                <p className="text-slate-400 text-sm mb-2">{result.message}</p>
                <p className="text-xs text-slate-500 mb-6">
                    Recording ID: {result.recording_id}
                    {result.diarization.performed && ' • Diarization applied'}
                </p>
                <Button variant="secondary" onClick={reset}>Upload Another</Button>
            </div>
        ) : status === 'error' ? (
            <div className="border-2 border-red-500/30 rounded-3xl p-12 flex flex-col items-center justify-center text-center bg-red-500/5">
                <h3 className="text-xl font-semibold text-white mb-2">Upload Failed</h3>
                <p className="text-red-400 text-sm mb-6">{error}</p>
                <Button variant="secondary" onClick={reset}>Try Again</Button>
            </div>
        ) : (
            <div
                onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
                onClick={() => status !== 'uploading' && fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-3xl p-12 flex flex-col items-center justify-center text-center transition-all cursor-pointer group ${
                    isDragOver ? 'border-accent-cyan bg-accent-cyan/10 scale-[1.02]' :
                    status === 'uploading' ? 'border-accent-cyan/50 bg-accent-cyan/5 pointer-events-none' :
                    'border-white/20 hover:border-accent-cyan/50 hover:bg-accent-cyan/5'
                }`}
            >
                <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
                    {status === 'uploading'
                        ? <Loader2 size={32} className="text-accent-cyan animate-spin" />
                        : <Upload size={32} className="text-slate-300 group-hover:text-accent-cyan" />
                    }
                </div>
                <h3 className="text-xl font-semibold text-white mb-2">
                    {status === 'uploading' ? 'Uploading & Transcribing...' : 'Drag & Drop Audio Files'}
                </h3>
                <p className="text-slate-400 text-sm mb-6">Supports MP3, WAV, M4A, FLAC, OGG, WebM, Opus</p>
                {status !== 'uploading' && <Button variant="primary">Browse Files</Button>}
            </div>
        )}

        <GlassCard title="Import Options">
            <div className="space-y-4">
                 <AppleSwitch checked={diarization} onChange={setDiarization} label="Speaker Diarization" description="Identify distinct speakers in the audio" />
                 <div className="h-px bg-white/5"></div>
                 <AppleSwitch checked={wordTimestamps} onChange={setWordTimestamps} label="Word-level Timestamps" description="Generate precise timestamps for every word" />
            </div>
        </GlassCard>
    </div>
    );
};
