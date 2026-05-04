/**
 * Auto-action retry hook (Issue #104, Story 6.6 / 6.9).
 *
 * Calls `POST /api/notebook/recordings/{id}/auto-actions/retry` with
 * `{action_type}` body. Returns a mutation handle so the badge can
 * trigger retries on click.
 *
 * Idempotency (Story 6.9): the endpoint returns:
 *   - 202 + status='retry_initiated'      — happy path
 *   - 200 + status='already_complete'     — success → no-op
 *   - 200 + status='already_in_progress'  — concurrent click
 * The dashboard treats all three as "OK, polling will pick up the new state".
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import type { AutoActionType } from '../../components/recording/AutoActionStatusBadge';

export interface AutoActionRetryResponse {
  recording_id: number;
  action_type: string;
  status: 'retry_initiated' | 'already_complete' | 'already_in_progress';
}

export function useAutoActionRetry(recordingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (actionType: AutoActionType): Promise<AutoActionRetryResponse> =>
      apiClient.retryAutoAction(recordingId, actionType),
    onSuccess: () => {
      // Invalidate any query keyed on this recording — the dashboard's
      // existing recording-detail query refetches and the new statuses
      // flow through.
      qc.invalidateQueries({ queryKey: ['notebook-recording', recordingId] });
      qc.invalidateQueries({ queryKey: ['recording', recordingId] });
    },
  });
}
