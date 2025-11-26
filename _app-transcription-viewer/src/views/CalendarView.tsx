import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  IconButton,
  Badge,
  Grid,
} from '@mui/material';
import {
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material';
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
    const dateStr = date.format('YYYY-MM-DD');
    if (recordingsByDate[dateStr] && recordingsByDate[dateStr].length > 0) {
      // Navigate to first recording of that day
      navigate(`/recording/${recordingsByDate[dateStr][0].id}`);
    }
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
        <Grid item xs={12 / 7} key={`empty-${i}`}>
          <Box sx={{ p: 2 }} />
        </Grid>
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

      days.push(
        <Grid item xs={12 / 7} key={day}>
          <Paper
            elevation={isToday ? 3 : 1}
            onClick={() => !isFuture && handleDayClick(date)}
            sx={{
              p: 2,
              textAlign: 'center',
              cursor: isFuture ? 'default' : 'pointer',
              opacity: isFuture ? 0.5 : 1,
              border: isToday ? '2px solid' : 'none',
              borderColor: 'primary.main',
              '&:hover': isFuture ? {} : {
                bgcolor: 'action.hover',
              },
            }}
          >
            <Badge
              badgeContent={hasRecordings ? recordings.length : 0}
              color="primary"
              invisible={!hasRecordings}
            >
              <Typography
                variant="body1"
                sx={{
                  fontWeight: isToday ? 'bold' : 'normal',
                  color: hasRecordings ? 'primary.main' : 'text.primary',
                }}
              >
                {day}
              </Typography>
            </Badge>
          </Paper>
        </Grid>
      );
    }

    return days;
  };

  return (
    <Box>
      {/* Month navigation */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          mb: 3,
        }}
      >
        <IconButton onClick={handlePreviousMonth}>
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="h4" sx={{ mx: 3, minWidth: 200, textAlign: 'center' }}>
          {currentMonth.format('MMMM YYYY')}
        </Typography>
        <IconButton
          onClick={handleNextMonth}
          disabled={currentMonth.isSame(dayjs(), 'month')}
        >
          <ChevronRightIcon />
        </IconButton>
      </Box>

      {/* Day headers */}
      <Grid container spacing={1} sx={{ mb: 1 }}>
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
          <Grid item xs={12 / 7} key={day}>
            <Typography
              variant="subtitle2"
              sx={{ textAlign: 'center', color: 'text.secondary' }}
            >
              {day}
            </Typography>
          </Grid>
        ))}
      </Grid>

      {/* Calendar grid */}
      <Grid container spacing={1}>
        {renderCalendarDays()}
      </Grid>
    </Box>
  );
}
