/**
 * Shared icon/color mapping for notification categories, used by both
 * NotificationsView (the session log) and NotificationToasts (the floating
 * stack). Cyan = active/primary per the design language; category accents
 * reuse the established accent tokens.
 */

import React from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Mic,
  RefreshCw,
  Server,
  StickyNote,
  Upload,
} from 'lucide-react';
import type { AppNotification, NotificationCategory } from '../../src/stores/notificationsStore';

export const CATEGORY_ICON: Record<NotificationCategory, React.ReactNode> = {
  download: <Download size={16} />,
  server: <Server size={16} />,
  update: <RefreshCw size={16} />,
  recording: <Mic size={16} />,
  import: <Upload size={16} />,
  note: <StickyNote size={16} />,
  transcription: <FileText size={16} />,
};

export const CATEGORY_COLOR: Record<NotificationCategory, string> = {
  download: 'text-accent-cyan',
  server: 'text-accent-magenta',
  update: 'text-accent-orange',
  recording: 'text-accent-rose',
  import: 'text-accent-cyan',
  note: 'text-accent-orange',
  transcription: 'text-emerald-400',
};

export function NotificationStatusIcon({ status }: { status: AppNotification['status'] }) {
  switch (status) {
    case 'active':
      return <Loader2 size={14} className="text-accent-cyan shrink-0 animate-spin" />;
    case 'complete':
      return <CheckCircle2 size={14} className="shrink-0 text-emerald-400" />;
    case 'error':
      return <AlertCircle size={14} className="shrink-0 text-red-400" />;
    default:
      return null;
  }
}

/** Left-border accent for error/warning entries. */
export function severityBorderClass(item: AppNotification): string {
  if (item.status === 'error') return 'border-l-2 border-l-red-500';
  if (item.severity === 'warning') return 'border-l-2 border-l-amber-400';
  return '';
}
