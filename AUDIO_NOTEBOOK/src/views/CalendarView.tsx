import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Mic } from 'lucide-react';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../services/api';
import { RecordingsByDate } from '../types';

export default function CalendarView() {
  const navigate = useNavigate();
  const [currentMonth, setCurrentMonth] = useState(dayjs());
  const [recordingsByDate, setRecordingsByDate] = useState<RecordingsByDate>({});

  useEffect(() => {
    loadRecordingsForMonth();
  }, [currentMonth]);

  const loadRecordingsForMonth = async () => {
    try {
      const startDate = currentMonth.startOf('month').format('YYYY-MM-DD');
      const endDate = currentMonth.endOf('month').format('YYYY-MM-DD');
      const data = await api.getRecordingsByDateRange(startDate, endDate);
      setRecordingsByDate(data);
    } catch (error) {
      console.error('Failed to load recordings:', error);
    }
  };

  const handlePreviousMonth = () => setCurrentMonth(currentMonth.subtract(1, 'month'));
  const handleNextMonth = () => {
    const nextMonth = currentMonth.add(1, 'month');
    if (nextMonth.isBefore(dayjs(), 'month') || nextMonth.isSame(dayjs(), 'month')) {
      setCurrentMonth(nextMonth);
    }
  };

  const handleDayClick = (date: Dayjs) => navigate(`/day/${date.format('YYYY-MM-DD')}`);

  const renderCalendarDays = () => {
    const startOfMonth = currentMonth.startOf('month');
    const endOfMonth = currentMonth.endOf('month');
    const startDay = startOfMonth.day(); // 0 = Sunday
    const daysInMonth = endOfMonth.date();
    const today = dayjs();
    const days = [];

    // Empty cells
    for (let i = 0; i < startDay; i++) {
      days.push(<div key={`empty-${i}`} className="min-h-[80px] bg-transparent" />);
    }

    // Days
    for (let day = 1; day <= daysInMonth; day++) {
      const date = currentMonth.date(day);
      const dateStr = date.format('YYYY-MM-DD');
      const recordings = recordingsByDate[dateStr] || [];
      const isToday = date.isSame(today, 'day');
      const isFuture = date.isAfter(today, 'day');
      const hasRecordings = recordings.length > 0;
      
      days.push(
        <div
          key={day}
          onClick={() => !isFuture && handleDayClick(date)}
          className={`
            relative min-h-[80px] border border-gray-800 p-2 transition-all duration-200 overflow-hidden
            ${isToday ? 'bg-primary/10 border-primary' : 'bg-surface hover:bg-gray-800'}
            ${isFuture ? 'opacity-30 cursor-default' : 'cursor-pointer'}
            ${hasRecordings ? 'ring-1 ring-inset ring-gray-700' : ''}
            rounded-lg
          `}
        >
          <div className="flex justify-between items-start">
            <span className={`
              text-sm font-semibold w-7 h-7 flex items-center justify-center rounded-full
              ${isToday ? 'bg-primary text-black' : 'text-gray-400'}
            `}>
              {day}
            </span>
            {hasRecordings && (
               <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white shadow-lg">
                {recordings.length}
               </span>
            )}
          </div>
          
          {hasRecordings && (
            <div className="mt-2 space-y-1">
              {recordings.slice(0, 2).map((rec) => (
                <div key={rec.id} className="flex items-center text-xs text-gray-300 truncate bg-gray-900/50 rounded px-1 py-0.5">
                  <Mic size={10} className="mr-1 text-primary shrink-0" />
                  <span className="truncate">{rec.filename}</span>
                </div>
              ))}
              {recordings.length > 2 && (
                <div className="text-[10px] text-gray-500 pl-1">
                  +{recordings.length - 2} more
                </div>
              )}
            </div>
          )}
        </div>
      );
    }
    return days;
  };

  return (
    <div className="flex flex-col h-full w-full animate-fade-in">
      <div className="flex items-center justify-between mb-4 w-full flex-shrink-0">
        <h1 className="text-3xl font-bold text-white tracking-tight">
          {currentMonth.format('MMMM YYYY')}
        </h1>
        <div className="flex space-x-2">
          <button 
            onClick={handlePreviousMonth}
            className="p-2 rounded-full hover:bg-gray-800 text-gray-400 hover:text-white transition-colors"
          >
            <ChevronLeft size={24} />
          </button>
          <button 
            onClick={handleNextMonth}
            disabled={currentMonth.isSame(dayjs(), 'month')}
            className="p-2 rounded-full hover:bg-gray-800 text-gray-400 hover:text-white transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
          >
            <ChevronRight size={24} />
          </button>
        </div>
      </div>
      
      <div className="grid grid-cols-7 gap-2 mb-2 flex-shrink-0">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
          <div key={d} className="text-center text-sm font-medium text-gray-500 py-2">
            {d}
          </div>
        ))}
      </div>
      
      <div className="grid grid-cols-7 gap-2 flex-1 min-h-0 auto-rows-fr">
        {renderCalendarDays()}
      </div>
    </div>
  );
}
