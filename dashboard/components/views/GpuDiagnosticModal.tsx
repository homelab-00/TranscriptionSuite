/**
 * GpuDiagnosticModal — actionable surface for the output of
 * `scripts/diagnose-gpu.sh`. Replaces the old `window.alert` flow.
 *
 * Renders three things, in order:
 *   1. Summary banner: PASS / WARN / FAIL counts, tone derived from worst.
 *   2. Per-issue rows for each WARN and FAIL — title + detail + (optional)
 *      copyable suggested command extracted by parseDiagnosticLog().
 *   3. Footer: Open Log (electronAPI.app.openPath → OS default text editor),
 *      Copy Path, Close.
 *
 * Stays NVIDIA-only by virtue of being mounted only when GpuHealthCard
 * passes `running` through. The dashboard never invokes sudo on the user's
 * behalf — fix commands are copy-paste only (advisor-not-agent stance).
 */
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertTriangle, AlertOctagon, FileText, Clipboard } from 'lucide-react';
import { writeToClipboard } from '../../src/hooks/useClipboard';
import { Button } from '../ui/Button';

export interface DiagnosticIssueProp {
  status: 'PASS' | 'WARN' | 'FAIL' | 'INFO';
  checkNumber: number;
  title: string;
  detail: string;
  suggestedCommand?: string;
}

export interface DiagnosticSummaryProp {
  passCount: number;
  warnCount: number;
  failCount: number;
  parsed: boolean;
  issues: DiagnosticIssueProp[];
}

export interface GpuDiagnosticResultProp {
  status: 'completed' | 'unsupported' | 'script-missing';
  logPath?: string;
  scriptPath?: string;
  manualCommand?: string;
  summary?: DiagnosticSummaryProp;
  exitCode?: number;
}

export interface GpuDiagnosticModalProps {
  isOpen: boolean;
  result: GpuDiagnosticResultProp | null;
  onClose: () => void;
}

type BannerTone = 'green' | 'amber' | 'red' | 'slate';

function deriveBannerTone(summary: DiagnosticSummaryProp | undefined): BannerTone {
  if (!summary) return 'slate';
  if (summary.failCount > 0) return 'red';
  if (summary.warnCount > 0) return 'amber';
  return 'green';
}

const BANNER_CLASSES: Record<BannerTone, string> = {
  green: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  amber: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  red: 'border-red-600/40 bg-red-600/10 text-red-200',
  slate: 'border-slate-400/30 bg-slate-400/10 text-slate-200',
};

function CopyableCommand({ cmd }: { cmd: string }): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  const handleCopy = (): void => {
    writeToClipboard(cmd)
      .then(() => {
        setCopied(true);
        if (timerRef.current) window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        /* silent — matches LogsView pattern */
      });
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <code className="flex-1 overflow-x-auto rounded bg-black/40 px-2 py-1 font-mono text-xs text-neutral-100">
        {cmd}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-100 hover:bg-neutral-600"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

function IssueRow({ issue }: { issue: DiagnosticIssueProp }): React.ReactElement {
  const isFail = issue.status === 'FAIL';
  const Icon = isFail ? AlertOctagon : AlertTriangle;
  const iconClass = isFail ? 'text-red-400' : 'text-amber-400';
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex items-start gap-2">
        <Icon size={16} className={`mt-0.5 flex-shrink-0 ${iconClass}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-white">
            #{issue.checkNumber} {issue.title}
          </p>
          <p className="mt-0.5 text-xs text-slate-300">{issue.detail}</p>
          {issue.suggestedCommand ? <CopyableCommand cmd={issue.suggestedCommand} /> : null}
        </div>
      </div>
    </div>
  );
}

export function GpuDiagnosticModal({
  isOpen,
  result,
  onClose,
}: GpuDiagnosticModalProps): React.ReactElement | null {
  const [pathCopied, setPathCopied] = useState(false);
  const pathTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  useEffect(() => {
    return () => {
      if (pathTimerRef.current) window.clearTimeout(pathTimerRef.current);
    };
  }, []);

  if (!isOpen || !result) return null;

  const summary = result.summary;
  const tone = deriveBannerTone(summary);
  const issues = summary?.issues ?? [];

  const handleOpenLog = (): void => {
    if (!result.logPath) return;
    const api = window.electronAPI?.app?.openPath;
    if (typeof api !== 'function') return;
    void api(result.logPath).catch(() => {
      /* surface via console only — modal stays useful */
      // eslint-disable-next-line no-console
      console.warn('Failed to open diagnostic log via shell');
    });
  };

  const handleCopyPath = (): void => {
    if (!result.logPath) return;
    writeToClipboard(result.logPath)
      .then(() => {
        setPathCopied(true);
        if (pathTimerRef.current) window.clearTimeout(pathTimerRef.current);
        pathTimerRef.current = window.setTimeout(() => setPathCopied(false), 1500);
      })
      .catch(() => {
        /* silent */
      });
  };

  const bannerText: string = (() => {
    if (result.status === 'script-missing') {
      return 'Diagnostic script not bundled — run it manually.';
    }
    if (!summary) {
      return 'Diagnostic ran but no summary could be parsed.';
    }
    if (!summary.parsed) {
      return `Could not parse the Summary block — counted ${summary.passCount} PASS / ${summary.warnCount} WARN / ${summary.failCount} FAIL from rows.`;
    }
    return `${summary.passCount} PASS · ${summary.warnCount} WARN · ${summary.failCount} FAIL`;
  })();

  const modalContent = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="GPU diagnostic results"
    >
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      <div className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-white/20 bg-black/40 bg-linear-to-b from-white/5 to-black/20 shadow-2xl backdrop-blur-xl">
        <div className="bg-accent-cyan/20 pointer-events-none absolute top-0 left-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="bg-accent-magenta/10 pointer-events-none absolute right-0 bottom-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="pointer-events-none absolute inset-0 bg-black/20" />

        <div className="relative flex items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4">
          <div className="flex items-center gap-3">
            <FileText size={20} className="text-accent-cyan" />
            <div className="flex flex-col">
              <h2 className="text-lg font-semibold text-white">GPU Diagnostic</h2>
              <p className="text-xs text-slate-400">
                Output of <code className="font-mono">scripts/diagnose-gpu.sh</code>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full border border-white/10 bg-black/10 p-2 text-white backdrop-blur-md transition-colors hover:bg-black/40"
          >
            <X size={16} />
          </button>
        </div>

        <div className="relative z-0 flex flex-col gap-3 overflow-y-auto px-6 py-5">
          <div
            role="status"
            className={`rounded-lg border px-3 py-2 text-sm font-medium ${BANNER_CLASSES[tone]}`}
          >
            {bannerText}
          </div>

          {result.status === 'script-missing' && result.manualCommand ? (
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-xs text-slate-300">
                Run this in a terminal to capture the diagnostic yourself:
              </p>
              <CopyableCommand cmd={result.manualCommand} />
            </div>
          ) : null}

          {issues.length > 0 ? (
            <div className="flex flex-col gap-2">
              {issues.map((issue) => (
                <IssueRow key={`${issue.status}-${issue.checkNumber}`} issue={issue} />
              ))}
            </div>
          ) : result.status === 'completed' && summary && summary.parsed ? (
            <p className="text-sm text-slate-300">All checks passed — GPU is healthy.</p>
          ) : null}

          {result.logPath ? (
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-xs font-medium text-slate-300">Log file</p>
              <code className="mt-1 block overflow-x-auto font-mono text-xs text-slate-200">
                {result.logPath}
              </code>
            </div>
          ) : null}
        </div>

        <div className="relative flex items-center justify-end gap-2 border-t border-white/10 bg-white/5 px-6 py-4">
          {result.logPath ? (
            <>
              <button
                type="button"
                onClick={handleCopyPath}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-white/10"
              >
                <Clipboard size={14} />
                {pathCopied ? 'Copied' : 'Copy Path'}
              </button>
              <Button variant="primary" size="sm" onClick={handleOpenLog}>
                Open Log
              </Button>
            </>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-white/10"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
