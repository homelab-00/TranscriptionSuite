import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
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

  const handlePreviousMonth = () => {
    setCurrentMonth(currentMonth.subtract(1, 'month'));
  };

  const handleNextMonth = () => {
    const nextMonth = currentMonth.add(1, 'month');
    // Don't allow navigating to future months
    if (nextMonth.isBefore(dayjs(), 'month') || nextMonth.isSame(dayjs(), 'month')) {
      setCurrentMonth(nextMonth);
    }
  };

  const handleDayClick = (date: Dayjs) => {
    // Navigate to day view
    navigate(`/day/${date.format('YYYY-MM-DD')}`);
  };

  const renderCalendarDays = () => {
    const startOfMonth = currentMonth.startOf('month');
    const endOfMonth = currentMonth.endOf('month');
    const startDay = startOfMonth.day(); // 0 = Sunday
    const daysInMonth = endOfMonth.date();
    const today = dayjs();

    const days = [];

    // Add empty cells for days before the start of the month
    for (let i = 0; i < startDay; i++) {
      days.push(
        <div key={`empty-${i}`} className="p-2" />
      );
    }

    // Add cells for each day of the month
    for (let day = 1; day <= daysInMonth; day++) {
      const date = currentMonth.date(day);
      const dateStr = date.format('YYYY-MM-DD');
      const recordings = recordingsByDate[dateStr] || [];
      const isToday = date.isSame(today, 'day');
      const isFuture = date.isAfter(today, 'day');
      const hasRecordings = recordings.length > 0;
      const recordingCount = recordings.length;

      days.push(
        <div
          key={day}
          onClick={() => !isFuture && handleDayClick(date)}
          className={`
            relative p-3 min-h-[60px] rounded-lg border text-center transition-all duration-200
            ${isFuture
              ? 'opacity-50 cursor-default bg-surface border-gray-800'
              : 'cursor-pointer hover:scale-[1.02] hover:bg-surface-light'
            }
            ${isToday
              ? 'border-2 border-primary bg-surface shadow-lg'
              : hasRecordings
                ? 'bg-surface border-gray-700'
                : 'bg-surface border-gray-800'
            }
          `}
        >
          {/* Red badge in top-right corner */}
          {hasRecordings && (
            <div className="absolute top-1 right-1 min-w-[20px] h-5 px-1 flex items-center justify-center bg-red-500 text-white text-[11px] font-bold rounded-full shadow">
              {recordingCount > 1 ? recordingCount : ''}
            </div>
          )}
          
          <span
            className={`
              text-sm
              ${isToday ? 'font-bold' : 'font-normal'}
              ${hasRecordings ? 'text-primary' : 'text-white'}
            `}
          >
            {day}
          </span>
        </div>
      );
    }

    return days;
  };

  const isNextDisabled = currentMonth.isSame(dayjs(), 'month');

  return (
    <div className="w-full max-w-[650px] mx-auto">
      {/* Month navigation */}
      <div className="flex items-center justify-center mb-6">
        <button
          onClick={handlePreviousMonth}
          className="btn-icon"
        >
          <ChevronLeft size={24} />
        </button>
        <h2 className="mx-6 min-w-[200px] text-center text-2xl font-semibold text-white">
          {currentMonth.format('MMMM YYYY')}
        </h2>
        <button
          onClick={handleNextMonth}
          disabled={isNextDisabled}
          className={`btn-icon ${isNextDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <ChevronRight size={24} />
        </button>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-1 mb-2">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
          <div
            key={day}
            className="text-center text-sm text-gray-500 font-medium py-2"
          >
            {day}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1">
        {renderCalendarDays()}
      </div>
    </div>
  );
}
