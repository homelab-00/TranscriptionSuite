/**
 * Auto-action status badge (Issue #104, Story 6.6 — UX-DR1, FR35).
 *
 * Wraps the existing `StatusLight` colored-dot primitive with a label,
 * an inline ⟳ retry button, and ARIA live-region announcements. Story
 * 6.6 calls this surface "status badge with single-click retry"; the
 * implementation reuses StatusLight (UX-DR1) instead of inventing a
 * new visual primitive.
 *
 * Severity → StatusLight status mapping:
 *   ok                          → 'active'  (green, pulses)
 *   warn                        → 'warning' (amber)
 *   error                       → 'error'   (red)
 *   processing                  → 'loading' (blue, pulses)
 *   manual_intervention_required → 'error'  (red — distinct from 'error'
 *                                           via the message text)
 *
 * Cardinality (Story 6.6 AC3): one badge per auto-action per recording.
 * Auto-summary and auto-export render TWO independent badges; each has
 * its own retry button.
 *
 * Persistence (Story 6.6 AC4): the severity is read from the row's
 * status column, not from local state. Auto-dismiss for severity='ok'
 * is local-only — the DB row stays at 'success'.
 *
 * UI-contract (UX-DR5): the new CSS classes added by this component
 * must be ratified via `npm run ui:contract:check`.
 */

import { useEffect, useState } from 'react';

import { StatusLight } from '../ui/StatusLight';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';

export type AutoActionSeverity =
  | 'ok'
  | 'warn'
  | 'error'
  | 'processing'
  | 'manual_intervention_required';
export type AutoActionType = 'auto_summary' | 'auto_export';

interface AutoActionStatusBadgeProps {
  recordingId: number;
  recordingName: string;
  actionType: AutoActionType;
  severity: AutoActionSeverity;
  message: string;
  retryable: boolean;
  onRetry?: (actionType: AutoActionType) => void;
  /**
   * If true, the badge unmounts itself after 3s when severity='ok' —
   * matches Story 6.6 AC1 ("auto-dismisses 3s after success"). Disabled
   * by default so tests can assert the immediate render.
   */
  autoDismissOk?: boolean;
}

const SEVERITY_TO_STATUSLIGHT: Record<
  AutoActionSeverity,
  'active' | 'warning' | 'error' | 'loading'
> = {
  ok: 'active',
  warn: 'warning',
  error: 'error',
  processing: 'loading',
  manual_intervention_required: 'error',
};

const ACTION_LABEL: Record<AutoActionType, string> = {
  auto_summary: 'auto-summary',
  auto_export: 'auto-export',
};

export function AutoActionStatusBadge({
  recordingId,
  recordingName,
  actionType,
  severity,
  message,
  retryable,
  onRetry,
  autoDismissOk = false,
}: AutoActionStatusBadgeProps) {
  const announce = useAriaAnnouncer();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    announce(`${ACTION_LABEL[actionType]}: ${message}`);
  }, [actionType, message, announce]);

  useEffect(() => {
    if (!autoDismissOk || severity !== 'ok') return undefined;
    const handle = setTimeout(() => setDismissed(true), 3000);
    return () => clearTimeout(handle);
  }, [autoDismissOk, severity]);

  if (dismissed) return null;

  return (
    <div
      role="status"
      data-recording-id={recordingId}
      data-action-type={actionType}
      data-severity={severity}
      className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-2 py-1 text-xs"
    >
      <StatusLight status={SEVERITY_TO_STATUSLIGHT[severity]} animate={severity !== 'ok'} />
      <span className="text-slate-200">{message}</span>
      {retryable && onRetry !== undefined && (
        <button
          type="button"
          onClick={() => onRetry(actionType)}
          aria-label={`Retry ${ACTION_LABEL[actionType]} for ${recordingName}`}
          className="ml-1 rounded px-1 text-cyan-300 hover:bg-white/10 hover:text-cyan-200"
        >
          ⟳ Retry
        </button>
      )}
    </div>
  );
}

/**
 * Map a backend status value to a UI severity + retryable flag.
 *
 * The backend persists the per-action enum from
 * `server/backend/database/auto_action_repository.py`; the dashboard
 * keeps this mapping in TypeScript so all consumers (badge, hook,
 * future analytics surfaces) agree.
 */
export interface AutoActionStatusMap {
  severity: AutoActionSeverity;
  message: string;
  retryable: boolean;
}

const RETRYABLE_STATUSES = new Set<string>([
  'failed',
  'deferred',
  'summary_empty',
  'summary_truncated',
  'manual_intervention_required',
  'retry_pending',
]);

export function statusToBadgeProps(
  status: string | null,
  actionType: AutoActionType,
  options: { error?: string | null; path?: string | null } = {},
): AutoActionStatusMap | null {
  if (status === null || status === undefined) return null;

  const action = actionType === 'auto_summary' ? 'Summary' : 'Export';
  const retryable = RETRYABLE_STATUSES.has(status);

  switch (status) {
    case 'success':
      return { severity: 'ok', message: `${action} ready`, retryable: false };
    case 'in_progress':
    case 'pending':
      return { severity: 'processing', message: `${action} in progress…`, retryable: false };
    case 'held':
      return {
        severity: 'warn',
        message: 'Auto-summary held — review uncertain turns first',
        retryable: false,
      };
    case 'summary_empty':
      return { severity: 'warn', message: 'Summary empty', retryable: true };
    case 'summary_truncated':
      return { severity: 'warn', message: 'Summary truncated', retryable: true };
    case 'deferred':
      return {
        severity: 'warn',
        message: options.path
          ? `Export deferred — destination "${options.path}" not mounted (will retry)`
          : 'Export deferred — destination not available',
        retryable: true,
      };
    case 'retry_pending':
      return {
        severity: 'processing',
        message: `${action} — auto-retry pending…`,
        retryable: true,
      };
    case 'failed':
      return {
        severity: 'error',
        message: options.error ? `${action} failed: ${options.error}` : `${action} failed`,
        retryable: true,
      };
    case 'manual_intervention_required':
      return {
        severity: 'manual_intervention_required',
        message: 'Manual intervention required — automatic retry exhausted',
        retryable: true,
      };
    default:
      return { severity: 'warn', message: `${action}: ${status}`, retryable };
  }
}
