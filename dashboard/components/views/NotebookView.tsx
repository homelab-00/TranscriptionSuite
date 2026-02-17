import React, { useState, useEffect, useRef, useLayoutEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { NotebookTab } from '../../types';
import {
  Calendar,
  Search,
  Upload,
  Filter,
  FileText,
  Trash2,
  Download,
  Clock,
  MoreHorizontal,
  Play,
  ChevronLeft,
  ChevronRight,
  Check,
  Plus,
  Minus,
  Edit2,
  Loader2,
  RotateCcw,
  XCircle,
  AlertCircle,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { AudioNoteModal } from './AudioNoteModal';
import { AddNoteModal } from './AddNoteModal';
import { useCalendar } from '../../src/hooks/useCalendar';
import { useSearch } from '../../src/hooks/useSearch';
import { useUpload } from '../../src/hooks/useUpload';
import { useImportQueue } from '../../src/hooks/useImportQueue';
import type { ImportJob } from '../../src/hooks/useImportQueue';
import { apiClient } from '../../src/api/client';
import type { Recording } from '../../src/api/types';

export const NotebookView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NotebookTab>(NotebookTab.CALENDAR);
  const [calendarRefreshNonce, setCalendarRefreshNonce] = useState(0);

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

  const bumpCalendarRefresh = useCallback(() => {
    setCalendarRefreshNonce((prev) => prev + 1);
  }, []);

  const renderContent = () => {
    switch (activeTab) {
      case NotebookTab.CALENDAR:
        return (
          <CalendarTab
            onNoteClick={handleNoteClick}
            onAddNote={handleAddNote}
            refreshNonce={calendarRefreshNonce}
          />
        );
      case NotebookTab.SEARCH:
        return <SearchTab onNoteClick={handleNoteClick} />;
      case NotebookTab.IMPORT:
        return <ImportTab />;
    }
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col space-y-6 p-6">
      <div className="flex flex-none items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-white">Audio Notebook</h1>
        <div className="bg-glass-200 flex rounded-lg border border-white/5 p-1 backdrop-blur-md">
          {[
            { id: NotebookTab.CALENDAR, icon: <Calendar size={16} />, label: 'Calendar' },
            { id: NotebookTab.SEARCH, icon: <Search size={16} />, label: 'Search' },
            { id: NotebookTab.IMPORT, icon: <Upload size={16} />, label: 'Import' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center space-x-2 rounded-md px-4 py-2 text-sm font-medium transition-all duration-200 ${
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

      <div className="animate-in fade-in slide-in-from-bottom-2 relative min-h-0 flex-1 duration-300">
        {renderContent()}
      </div>

      {/* View/Edit Audio Note Overlay */}
      <AudioNoteModal
        isOpen={isNoteModalOpen}
        onClose={() => setIsNoteModalOpen(false)}
        note={selectedNote}
        onRecordingMutated={bumpCalendarRefresh}
      />

      {/* Add New Note Overlay */}
      <AddNoteModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        initialTime={selectedTimeSlot}
        onCreated={bumpCalendarRefresh}
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
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
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
      if (trigger.type === 'rect' && trigger.rect) {
        left = trigger.rect.right - menuRect.width;
      } else {
        left = (trigger.x || 0) - menuRect.width - 5;
      }
    }
    if (top + menuRect.height > innerHeight - PADDING) {
      if (trigger.type === 'rect' && trigger.rect) {
        top = trigger.rect.top - menuRect.height - 5;
      } else {
        top = (trigger.y || 0) - menuRect.height - 5;
      }
    }
    if (left < PADDING) {
      left = PADDING;
    }
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
    <div
      className="fixed inset-0 z-9999"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <style>{slideUpKeyframes}</style>
      <div
        ref={menuRef}
        className="absolute w-44 origin-top-left rounded-xl border border-white/10 bg-black/50 py-1.5 shadow-2xl backdrop-blur-xl"
        style={{
          top: position ? position.top : 0,
          left: position ? position.left : 0,
          opacity: position ? 1 : 0,
          ...animationStyle,
          animation: position
            ? 'slideUpFromBottomEdge 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards'
            : 'none',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={handlePlay}
          className="group flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Play size={14} className="group-hover:text-accent-cyan" />
          Play Recording
        </button>
        <div className="mx-2 my-1 h-px bg-white/5"></div>
        <button
          onClick={handleRename}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Edit2 size={14} />
          Rename
        </button>
        <button
          onClick={() => handleExport('txt')}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Download size={14} />
          Export TXT
        </button>
        <button
          onClick={() => handleExport('srt')}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Download size={14} />
          Export SRT
        </button>
        <button
          onClick={() => handleExport('ass')}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Download size={14} />
          Export ASS
        </button>
        <div className="mx-2 my-1 h-px bg-white/5"></div>
        <button
          onClick={handleDelete}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-red-400 transition-colors hover:bg-red-500/10 hover:text-red-300"
        >
          <Trash2 size={14} />
          Delete
        </button>
      </div>
    </div>,
    document.body,
  );
};

// --- History / Month Picker ---
interface HistoryPickerProps {
  isOpen: boolean;
  onClose: () => void;
  selectedDate: Date;
  onSelect: (date: Date) => void;
  triggerRect: DOMRect | null;
}

const HistoryPicker: React.FC<HistoryPickerProps> = ({
  isOpen,
  onClose,
  selectedDate,
  onSelect,
  triggerRect,
}) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [viewYear, setViewYear] = useState(selectedDate.getFullYear());

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;
    if (isOpen) {
      setIsRendered(true);
      setViewYear(selectedDate.getFullYear());
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 300);
    }
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen, selectedDate]);

  if (!isRendered) return null;
  const months = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];
  const handleMonthSelect = (monthIndex: number) => {
    const newDate = new Date(viewYear, monthIndex, 1);
    onSelect(newDate);
    onClose();
  };
  const positionStyle: React.CSSProperties = triggerRect
    ? {
        position: 'fixed',
        top: `${triggerRect.top}px`,
        right: `${window.innerWidth - triggerRect.right}px`,
        transformOrigin: 'top right',
      }
    : {};

  return createPortal(
    <div className="fixed inset-0 z-9999">
      <div className="absolute inset-0" onClick={onClose} />
      <div
        style={positionStyle}
        className={`w-80 rounded-xl border border-white/10 bg-black/10 p-6 shadow-xl backdrop-blur-xl transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 scale-100 opacity-100' : '-translate-y-2 scale-95 opacity-0'}`}
      >
        <div className="mb-6 flex items-center justify-between">
          <button
            onClick={() => setViewYear(viewYear - 1)}
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <ChevronLeft size={20} />
          </button>
          <div className="font-mono text-xl font-bold tracking-tight text-white">{viewYear}</div>
          <button
            onClick={() => setViewYear(viewYear + 1)}
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <ChevronRight size={20} />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {months.map((month, index) => {
            const isSelected =
              selectedDate.getMonth() === index && selectedDate.getFullYear() === viewYear;
            const isCurrentMonth =
              new Date().getMonth() === index && new Date().getFullYear() === viewYear;
            return (
              <button
                key={month}
                onClick={() => handleMonthSelect(index)}
                className={`relative flex h-10 items-center justify-center rounded-xl text-sm font-medium transition-all duration-200 ${isSelected ? 'bg-accent-cyan z-10 scale-105 font-bold text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.4)]' : 'text-slate-300 hover:scale-105 hover:bg-white/10 hover:text-white'}`}
              >
                {month.slice(0, 3)}
                {isCurrentMonth && !isSelected && (
                  <div className="bg-accent-cyan absolute bottom-1 h-1 w-1 rounded-full"></div>
                )}
              </button>
            );
          })}
        </div>
        <div className="mt-6 flex justify-center border-t border-white/10 pt-4">
          <button
            onClick={() => {
              const now = new Date();
              onSelect(new Date(now.getFullYear(), now.getMonth(), 1));
              onClose();
            }}
            className="text-accent-cyan text-xs font-medium tracking-widest uppercase transition-colors hover:text-cyan-300"
          >
            Jump to Today
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
};

// --- Sub-components for Calendar View ---
interface EventData {
  id: string;
  title: string;
  duration?: string;
  tag?: string;
  startTime: number;
  recordingId?: number;
}

const TimeSection: React.FC<{
  title: string;
  headerColor: string;
  headerGradient: string;
  startHour: number;
  endHour: number;
  events: EventData[];
  visibleSlots: number;
  onZoomChange: (slots: number) => void;
  onNoteClick: (note: EventData) => void;
  onAddNote: (hour: number) => void;
  onRefresh: () => void;
}> = ({
  title,
  headerColor,
  headerGradient,
  startHour,
  endHour,
  events,
  visibleSlots,
  onZoomChange,
  onNoteClick,
  onAddNote,
  onRefresh,
}) => {
  const hours = Array.from({ length: endHour - startHour }, (_, i) => startHour + i);
  const [activeMenu, setActiveMenu] = useState<{ id: string; trigger: MenuTrigger } | null>(null);
  const isCompact = visibleSlots >= 4;
  const handleContextMenu = (e: React.MouseEvent, evt: EventData) => {
    e.preventDefault();
    setActiveMenu({ id: evt.id, trigger: { type: 'point', x: e.clientX, y: e.clientY } });
  };
  return (
    <div className="bg-glass-surface border-glass-border flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl">
      <div
        className={`z-10 flex h-14 shrink-0 items-center justify-between border-b border-white/5 px-5 backdrop-blur-md ${headerGradient}`}
      >
        <h3 className={`font-semibold tracking-tight ${headerColor}`}>{title}</h3>
        <div className="flex items-center gap-1 rounded-lg border border-white/5 bg-black/20 p-0.5">
          <button
            onClick={() => onZoomChange(Math.max(2, visibleSlots - 1))}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <Minus size={14} />
          </button>
          <button
            onClick={() => onZoomChange(Math.min(4, visibleSlots + 1))}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>
      <div className="custom-scrollbar relative h-full flex-1 overflow-y-auto">
        <div className="h-full">
          {hours.map((hour) => {
            const hourEvents = events.filter((e) => Math.floor(e.startTime) === hour);
            return (
              <div
                key={hour}
                className="group relative flex border-b border-white/5 transition-colors duration-300 last:border-0 hover:bg-white/2"
                style={{ height: `${100 / visibleSlots}%` }}
              >
                <div className="sticky left-0 z-20 w-16 shrink-0 pt-6 pr-4 text-right select-none">
                  <span className="font-mono text-xs font-medium text-slate-500">
                    {hour.toString().padStart(2, '0')}:00
                  </span>
                </div>
                <div className="custom-scrollbar mask-gradient-right relative flex h-full flex-1 snap-x snap-mandatory items-center gap-3 overflow-x-auto pr-6 pl-0">
                  {hourEvents.map((evt) => {
                    const minutes = Math.round((evt.startTime % 1) * 60)
                      .toString()
                      .padStart(2, '0');
                    const timeStr = `${Math.floor(evt.startTime).toString().padStart(2, '0')}:${minutes}`;
                    return (
                      <div
                        key={evt.id}
                        onClick={() => onNoteClick(evt)}
                        onContextMenu={(e) => handleContextMenu(e, evt)}
                        className="bg-glass-200 hover:bg-glass-300 group/card relative h-[85%] w-35 flex-none cursor-pointer snap-start overflow-hidden rounded-xl border border-white/10 p-3 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-white/20 hover:shadow-lg active:scale-[0.98]"
                      >
                        <div className="bg-accent-cyan absolute top-0 bottom-0 left-0 w-1 opacity-80 transition-opacity group-hover/card:opacity-100"></div>
                        <div className="flex h-full flex-col justify-between gap-2">
                          <div className="flex items-start justify-between">
                            <div className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
                              {timeStr}
                            </div>
                            {!isCompact && evt.tag === 'Diarized' && (
                              <div className="bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20 rounded border px-1 py-0.5 text-[8px] font-bold tracking-wider uppercase">
                                AI
                              </div>
                            )}
                          </div>
                          <div className="min-h-0">
                            <h4
                              className={`mb-1 text-xs leading-snug font-medium text-white ${isCompact ? 'line-clamp-1' : 'line-clamp-2'}`}
                            >
                              {evt.title}
                            </h4>
                            {!isCompact && evt.duration && (
                              <div className="flex items-center gap-1 text-[9px] text-slate-400">
                                <Clock size={9} />
                                {evt.duration}
                              </div>
                            )}
                          </div>
                          {!isCompact && (
                            <div className="mt-auto flex items-center justify-end gap-2 border-t border-white/5 pt-1.5 opacity-0 transition-opacity group-hover/card:opacity-100">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const rect = e.currentTarget.getBoundingClientRect();
                                  setActiveMenu({ id: evt.id, trigger: { type: 'rect', rect } });
                                }}
                                className="rounded-full p-1 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                              >
                                <MoreHorizontal size={12} />
                              </button>
                              <button
                                className="rounded-full p-1 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Play size={10} fill="currentColor" />
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  <div
                    className={`flex snap-start items-center ${hourEvents.length === 0 ? 'h-full w-full flex-none justify-start' : 'h-[85%] min-w-12.5 flex-1 justify-center'}`}
                  >
                    <button
                      onClick={() => onAddNote(hour)}
                      className={`hover:border-accent-cyan/50 hover:bg-accent-cyan/5 group/add flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 transition-all duration-300 ${hourEvents.length === 0 ? 'h-[90%] w-full' : 'h-full w-full opacity-100'}`}
                    >
                      <div
                        className={`group-hover/add:bg-accent-cyan flex items-center justify-center rounded-full bg-white/5 shadow-lg transition-all duration-300 group-hover/add:scale-110 group-hover/add:text-black ${hourEvents.length === 0 ? 'h-10 w-10' : 'h-7 w-7'}`}
                      >
                        <Plus size={hourEvents.length === 0 ? 20 : 14} />
                      </div>
                      {hourEvents.length === 0 && (
                        <span className="text-xs font-medium text-slate-400 transition-colors group-hover/add:text-white">
                          Add Note
                        </span>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {activeMenu && (
        <NoteActionMenu
          trigger={activeMenu.trigger}
          onClose={() => setActiveMenu(null)}
          noteId={activeMenu.id}
          onRefresh={onRefresh}
          onPlay={(id) => {
            const evt = events.find((e) => e.id === id);
            if (evt) onNoteClick(evt);
          }}
        />
      )}
    </div>
  );
};

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

const CalendarTab: React.FC<{
  onNoteClick: (note: any) => void;
  onAddNote: (hour: number) => void;
  refreshNonce: number;
}> = ({ onNoteClick, onAddNote, refreshNonce }) => {
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
  const totalCells = startOffset + daysInMonth;
  const gridRows = Math.ceil(totalCells / 7);
  const trailingCount = gridRows * 7 - totalCells;
  const trailingDays = Array.from({ length: trailingCount });
  // Day numbers for leading/trailing cells
  const prevMonthDays = new Date(year, month, 0).getDate(); // last day of prev month
  const monthTitle = currentDate.toLocaleString('default', { month: 'long', year: 'numeric' });
  const handlePrevMonth = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSlideDirection('left');
    setAnimKey((prev) => prev + 1);
    setCurrentDate(new Date(year, month - 1, 1));
    setSelectedDay(null);
  };
  const handleNextMonth = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSlideDirection('right');
    setAnimKey((prev) => prev + 1);
    setCurrentDate(new Date(year, month + 1, 1));
    setSelectedDay(null);
  };
  const calendarHeader = (
    <div className="flex items-center gap-3">
      <span>{monthTitle}</span>
      <div className="ml-1 flex items-center rounded-full border border-white/10 bg-white/5 p-0.5">
        <button
          onClick={handlePrevMonth}
          className="rounded-full p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ChevronLeft size={14} />
        </button>
        <button
          onClick={handleNextMonth}
          className="rounded-full p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );

  // Live calendar data from API
  const calendar = useCalendar(year, month);

  // Build calendar grid: day-of-month (1-indexed) → array of recording summaries
  const eventsByDay: Record<number, { title: string; id: number }[]> = useMemo(() => {
    const result: Record<number, { title: string; id: number }[]> = {};
    for (const [dateKey, recordings] of Object.entries(calendar.days)) {
      const day = new Date(dateKey).getDate();
      result[day] = recordings.map((r) => ({ title: r.title || r.filename, id: r.id }));
    }
    return result;
  }, [calendar.days]);

  // Recordings for the currently selected day, split into morning/afternoon
  const selectedDayRecordings = useMemo<Recording[]>(() => {
    if (!selectedDay || !calendar.days[selectedDay]) return [];
    return calendar.days[selectedDay];
  }, [selectedDay, calendar.days]);

  const morningEvents: EventData[] = useMemo(
    () =>
      selectedDayRecordings
        .filter((r) => new Date(r.recorded_at).getHours() < 12)
        .map(recordingToEvent),
    [selectedDayRecordings],
  );
  const afternoonEvents: EventData[] = useMemo(
    () =>
      selectedDayRecordings
        .filter((r) => new Date(r.recorded_at).getHours() >= 12)
        .map(recordingToEvent),
    [selectedDayRecordings],
  );

  useEffect(() => {
    if (refreshNonce === 0) return;
    calendar.refresh();
  }, [refreshNonce, calendar.refresh]);

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
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-6 lg:grid-cols-3">
      <style>{`
                @keyframes slideInRight { from { transform: translateX(20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                @keyframes slideInLeft { from { transform: translateX(-20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                .anim-slide-right { animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
                .anim-slide-left { animation: slideInLeft 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
            `}</style>
      <div className="flex min-h-0 flex-col lg:col-span-2">
        <GlassCard
          className="flex h-full flex-col"
          title={calendarHeader}
          action={
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={<Clock size={14} />}
                onClick={() => {
                  if (gridRef.current) {
                    setTriggerRect(gridRef.current.getBoundingClientRect());
                    setIsHistoryOpen(true);
                  }
                }}
                className={isHistoryOpen ? 'bg-white/10 text-white' : ''}
              >
                Month/Year
              </Button>
            </div>
          }
        >
          <div
            ref={gridRef}
            key={animKey}
            className={`grid h-full grid-cols-7 gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/5 ${slideDirection === 'right' ? 'anim-slide-right' : ''} ${slideDirection === 'left' ? 'anim-slide-left' : ''}`}
            style={{ gridTemplateRows: `auto repeat(${gridRows}, 1fr)` }}
          >
            {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(
              (d, i) => (
                <div
                  key={i}
                  className="bg-glass-100/50 flex items-center justify-center border-b border-white/5 py-1 text-center text-[10px] font-bold tracking-widest text-slate-500 uppercase"
                >
                  {d.slice(0, 3)}
                </div>
              ),
            )}
            {emptyDays.map((_, i) => (
              <div key={`empty-${i}`} className="border-t border-r border-white/5 bg-black/20 p-2">
                <span className="text-xs text-slate-600">
                  {prevMonthDays - startOffset + 1 + i}
                </span>
              </div>
            ))}
            {monthDays.map((_, i) => {
              const dayNum = i + 1;
              const dayEvents = eventsByDay[dayNum] || [];
              const hasEvents = dayEvents.length > 0;
              const count = dayEvents.length;
              const dayKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`;
              const isSelected = selectedDay === dayKey;
              const isToday = dayKey === todayKey;
              return (
                <div
                  key={i}
                  className={`bg-glass-100/30 hover:bg-glass-100 group relative flex min-h-0 cursor-pointer flex-col items-start overflow-hidden border-t border-r border-white/5 p-2 transition-colors ${isSelected ? 'ring-accent-cyan/50 bg-accent-cyan/5 ring-1' : ''}`}
                  onClick={() => handleDayClick(dayNum)}
                >
                  <div className="mb-1 flex w-full items-center justify-between">
                    <span
                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs transition-all ${isSelected ? 'bg-accent-cyan font-bold text-black' : isToday ? 'bg-[rgb(230,230,230)] font-bold text-black' : 'text-slate-400 group-hover:text-white'}`}
                    >
                      {dayNum}
                    </span>
                    {hasEvents && (
                      <div className="mr-1 flex h-4 min-w-6 items-center justify-center rounded-full bg-red-500 px-2 shadow-[0_0_5px_rgba(239,68,68,0.6)]">
                        <span className="text-[9px] leading-none font-bold text-white">
                          {count}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="flex min-h-0 w-full flex-1 flex-col gap-1 overflow-hidden pt-1">
                    {dayEvents.slice(0, 2).map((evt, idx) => (
                      <div
                        key={idx}
                        className="bg-accent-cyan w-full truncate rounded-full px-2 py-0.5 text-[10px] font-medium text-black shadow-sm"
                      >
                        {evt.title}
                      </div>
                    ))}
                    {dayEvents.length > 2 && (
                      <div className="pl-2 text-[9px] text-slate-500">
                        +{dayEvents.length - 2} more
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {trailingDays.map((_, i) => (
              <div key={`trail-${i}`} className="border-t border-r border-white/5 bg-black/20 p-2">
                <span className="text-xs text-slate-600">{i + 1}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
      <div className="flex h-full min-h-0 flex-col space-y-4 overflow-hidden">
        <TimeSection
          title="Morning"
          headerColor="text-accent-orange"
          headerGradient="bg-linear-to-r from-accent-orange/10 via-red-900/10 to-transparent"
          startHour={0}
          endHour={12}
          events={morningEvents}
          visibleSlots={visibleSlots}
          onZoomChange={setVisibleSlots}
          onNoteClick={onNoteClick}
          onAddNote={onAddNote}
          onRefresh={calendar.refresh}
        />
        <TimeSection
          title="Afternoon"
          headerColor="text-indigo-400"
          headerGradient="bg-linear-to-r from-indigo-500/10 via-blue-900/10 to-transparent"
          startHour={12}
          endHour={24}
          events={afternoonEvents}
          visibleSlots={visibleSlots}
          onZoomChange={setVisibleSlots}
          onNoteClick={onNoteClick}
          onAddNote={onAddNote}
          onRefresh={calendar.refresh}
        />
      </div>
      <HistoryPicker
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        selectedDate={currentDate}
        onSelect={setCurrentDate}
        triggerRect={triggerRect}
      />
    </div>
  );
};

const SearchTab: React.FC<{ onNoteClick: (note: any) => void }> = ({ onNoteClick }) => {
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
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="relative">
        <Search className="absolute top-3.5 left-4 text-slate-400" size={20} />
        <input
          type="text"
          placeholder="Search transcripts, speakers, or dates..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="bg-glass-100 focus:ring-accent-cyan w-full rounded-xl border border-white/10 py-3 pr-4 pl-12 text-white placeholder-slate-500 transition-all focus:ring-2 focus:outline-none"
        />
        {loading && (
          <Loader2 className="text-accent-cyan absolute top-3.5 right-4 animate-spin" size={20} />
        )}
      </div>

      <GlassCard>
        <div className="flex items-center gap-6 border-b border-white/5 pb-4">
          <div className="flex items-center gap-2">
            <Filter size={16} className="text-slate-400" />
            <span className="text-sm font-medium">Filters:</span>
          </div>
          <AppleSwitch checked={fuzzy} onChange={setFuzzy} label="Fuzzy Search" size="sm" />
          <div className="h-6 w-px bg-white/10"></div>
          <div className="flex gap-2">
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded border border-white/10 bg-black/20 px-2 py-1 text-xs text-slate-300"
            />
            <span className="text-sm text-slate-500">-</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded border border-white/10 bg-black/20 px-2 py-1 text-xs text-slate-300"
            />
          </div>
        </div>

        <div className="selectable-text mt-4 space-y-2">
          {error && <div className="mb-3 text-xs text-red-400">{error}</div>}
          {!query.trim() ? (
            <div className="py-8 text-center text-sm text-slate-500">
              Enter a search term to find recordings
            </div>
          ) : count === 0 && !loading ? (
            <div className="py-8 text-center text-sm text-slate-500">
              No results found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            <>
              <div className="mb-3 text-xs tracking-widest text-slate-500 uppercase select-none">
                {count} Result{count !== 1 ? 's' : ''} found
              </div>
              {results.map((r, i) => (
                <div
                  key={`${r.recording_id}-${r.id ?? i}`}
                  onClick={() =>
                    onNoteClick({
                      title: r.title || r.filename,
                      recordingId: r.recording_id,
                      duration: '',
                      tag: r.match_type,
                    })
                  }
                  className="group cursor-pointer rounded-lg border border-white/5 bg-white/5 p-4 transition-colors hover:bg-white/10"
                >
                  <div className="mb-1 flex items-start justify-between select-none">
                    <div className="flex items-center gap-2">
                      <FileText size={16} className="text-accent-cyan" />
                      <span className="font-medium text-white">{r.title || r.filename}</span>
                      {r.speaker && <span className="text-xs text-slate-500">({r.speaker})</span>}
                    </div>
                    <span className="text-xs text-slate-500">
                      {new Date(r.recorded_at).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="line-clamp-2 pl-6 text-sm text-slate-400">
                    {r.context ? (
                      <>
                        ...
                        {r.context.split(r.word).map((part, pi, arr) => (
                          <React.Fragment key={pi}>
                            {part}
                            {pi < arr.length - 1 && (
                              <span className="text-accent-orange bg-accent-orange/10 rounded px-1">
                                {r.word}
                              </span>
                            )}
                          </React.Fragment>
                        ))}
                        ...
                      </>
                    ) : (
                      r.word
                    )}
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
  const queue = useImportQueue();

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      queue.addFiles(Array.from(files), {
        enable_diarization: diarization,
        enable_word_timestamps: wordTimestamps,
      });
    },
    [diarization, wordTimestamps, queue],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const statusIcon = (job: ImportJob) => {
    switch (job.status) {
      case 'pending':
        return <Clock size={14} className="text-slate-400" />;
      case 'processing':
        return <Loader2 size={14} className="text-accent-cyan animate-spin" />;
      case 'success':
        return <Check size={14} className="text-green-400" />;
      case 'error':
        return <AlertCircle size={14} className="text-red-400" />;
    }
  };

  const statusLabel = (job: ImportJob) => {
    switch (job.status) {
      case 'pending':
        return 'Queued';
      case 'processing':
        return 'Processing...';
      case 'success':
        return `Done — ID ${job.result?.recording_id}`;
      case 'error':
        return job.error ?? 'Failed';
    }
  };

  return (
    <div className="mx-auto mt-10 max-w-2xl space-y-8">
      <input
        ref={fileInputRef}
        type="file"
        accept=".mp3,.wav,.m4a,.flac,.ogg,.webm,.opus"
        multiple
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = '';
        }}
      />

      {/* Drop Zone — always visible */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`group flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-12 text-center transition-all ${
          isDragOver
            ? 'border-accent-cyan bg-accent-cyan/10 scale-[1.02]'
            : 'hover:border-accent-cyan/50 hover:bg-accent-cyan/5 border-white/20'
        }`}
      >
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-white/5 transition-transform group-hover:scale-110">
          <Upload size={32} className="group-hover:text-accent-cyan text-slate-300" />
        </div>
        <h3 className="mb-2 text-xl font-semibold text-white">Drag & Drop Audio Files</h3>
        <p className="mb-6 text-sm text-slate-400">
          Supports MP3, WAV, M4A, FLAC, OGG, WebM, Opus — multiple files OK
        </p>
        <Button variant="primary">Browse Files</Button>
      </div>

      {/* Queue List */}
      {queue.jobs.length > 0 && (
        <GlassCard
          title={`Import Queue${queue.isProcessing ? ' — Processing' : ''}`}
          action={
            <div className="flex items-center gap-3 text-xs text-slate-400">
              {queue.completedCount > 0 && (
                <span className="text-green-400">{queue.completedCount} done</span>
              )}
              {queue.pendingCount > 0 && <span>{queue.pendingCount} pending</span>}
              {queue.errorCount > 0 && (
                <span className="text-red-400">{queue.errorCount} failed</span>
              )}
              {(queue.completedCount > 0 || queue.errorCount > 0) && (
                <button
                  onClick={queue.clearFinished}
                  className="ml-1 text-slate-500 transition-colors hover:text-white"
                  title="Clear finished"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          }
        >
          <div className="max-h-60 space-y-2 overflow-y-auto">
            {queue.jobs.map((job) => (
              <div
                key={job.id}
                className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2 transition-colors hover:bg-white/8"
              >
                {statusIcon(job)}
                <span className="flex-1 truncate text-sm text-white">{job.file.name}</span>
                <span className="text-xs whitespace-nowrap text-slate-400">{statusLabel(job)}</span>
                {job.status === 'error' && (
                  <button
                    onClick={() => queue.retryJob(job.id)}
                    className="hover:text-accent-cyan p-1 text-slate-400 transition-colors"
                    title="Retry"
                  >
                    <RotateCcw size={12} />
                  </button>
                )}
                {job.status !== 'processing' && (
                  <button
                    onClick={() => queue.removeJob(job.id)}
                    className="p-1 text-slate-500 transition-colors hover:text-red-400"
                    title="Remove"
                  >
                    <XCircle size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      <GlassCard title="Import Options">
        <div className="space-y-4">
          <AppleSwitch
            checked={diarization}
            onChange={setDiarization}
            label="Speaker Diarization"
            description="Identify distinct speakers in the audio"
          />
          <div className="h-px bg-white/5"></div>
          <AppleSwitch
            checked={wordTimestamps}
            onChange={setWordTimestamps}
            label="Word-level Timestamps"
            description="Generate precise timestamps for every word"
          />
        </div>
      </GlassCard>
    </div>
  );
};
