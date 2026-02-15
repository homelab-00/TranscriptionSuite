/**
 * useCalendar — fetches recordings grouped by day for a given month.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../api/client';
import type { CalendarResponse, Recording } from '../api/types';

export interface CalendarState {
  /** Recordings grouped by day key "YYYY-MM-DD" */
  days: Record<string, Recording[]>;
  totalRecordings: number;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useCalendar(year: number, month: number): CalendarState {
  const [days, setDays] = useState<Record<string, Recording[]>>({});
  const [totalRecordings, setTotalRecordings] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // API month is 1-indexed, JS Date month is 0-indexed
      const data: CalendarResponse = await apiClient.getCalendar(year, month + 1);
      setDays(data.days);
      setTotalRecordings(data.total_recordings);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load calendar');
      setDays({});
      setTotalRecordings(0);
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { days, totalRecordings, loading, error, refresh: fetch };
}
