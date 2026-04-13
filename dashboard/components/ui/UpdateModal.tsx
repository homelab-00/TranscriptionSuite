/**
 * UpdateModal — pre-install decision surface for in-app Dashboard updates.
 *
 * Opens on [Download] click from UpdateBanner. Shows:
 *   • Release notes (markdown, from updateStatus.app.releaseNotes)
 *   • Live server-compat verdict (via updates.checkCompatibility)
 *   • Three footer buttons:
 *       [Install Dashboard]   — always visible; disabled iff incompatible
 *       [Update Server First] — visible only on incompatible + local Docker
 *       [Cancel]              — always visible
 *
 * The modal NEVER calls `updates.download()` itself. Confirmation bubbles
 * through `onConfirmInstall`, which the banner wires to the existing
 * `api.download()` + try/catch pattern.
 *
 * Fail-open per M4 philosophy: `unknown` compat enables [Install Dashboard]
 * with a slate warning badge — do not block the update for transient
 * compat-fetch failures.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  X,
  Download,
  Server as ServerIcon,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';

const EXIT_MS = 500;

export interface UpdateModalProps {
  isOpen: boolean;
  targetVersion: string | null;
  currentVersion: string;
  onClose: () => void;
  onConfirmInstall: () => void;
}

type BadgeTone = 'green' | 'amber' | 'slate' | 'pending';

interface BadgeContent {
  tone: BadgeTone;
  text: string;
  icon: React.ReactNode;
}

/**
 * Pure mapping from CompatResult → verdict badge copy/tone.
 * Exported so the test suite can hit every branch without rendering.
 */
export function deriveBadgeContent(compat: CompatResult | null, pending: boolean): BadgeContent {
  if (pending || compat === null) {
    return {
      tone: 'pending',
      text: 'Checking server compatibility…',
      icon: <Loader2 size={14} className="animate-spin" />,
    };
  }
  if (compat.result === 'compatible') {
    return {
      tone: 'green',
      text: `Compatible with your server (v${compat.serverVersion})`,
      icon: <CheckCircle2 size={14} />,
    };
  }
  if (compat.result === 'incompatible') {
    const tail =
      compat.deployment === 'remote'
        ? '— update your remote server manually.'
        : '— update server first.';
    return {
      tone: 'amber',
      text: `Your server (v${compat.serverVersion}) needs v${compat.compatibleRange} ${tail}`,
      icon: <AlertTriangle size={14} />,
    };
  }
  return {
    tone: 'slate',
    text: `Could not verify server compatibility (${compat.reason}). Install anyway?`,
    icon: <HelpCircle size={14} />,
  };
}

const SAFE_LINK_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

/**
 * Protocol allow-list for release-note anchor clicks. Release bodies are
 * attacker-influenceable (anyone with push to the releases page) — we must
 * not hand `javascript:`, `file:`, or `data:` URLs to the OS shell.
 */
function isSafeExternalUrl(raw: string | undefined): boolean {
  if (!raw) return false;
  try {
    const parsed = new URL(raw);
    return SAFE_LINK_PROTOCOLS.has(parsed.protocol);
  } catch {
    return false;
  }
}

function openExternalLink(url: string | undefined): void {
  if (!isSafeExternalUrl(url)) return;
  const api = window.electronAPI?.app?.openExternal;
  if (typeof api === 'function') {
    void api(url as string).catch(() => {});
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const RELEASE_NOTES_MARKDOWN_COMPONENTS: Record<string, (props: any) => React.ReactNode> = {
  h1: ({ children }) => <h3 className="mt-3 mb-2 text-sm font-semibold text-white">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-3 mb-2 text-sm font-semibold text-white">{children}</h3>,
  h3: ({ children }) => (
    <h4 className="mt-2 mb-1.5 text-xs font-semibold tracking-wide text-slate-200 uppercase">
      {children}
    </h4>
  ),
  p: ({ children }) => (
    <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-300">{children}</p>
  ),
  strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
  em: ({ children }) => <em className="text-slate-200 italic">{children}</em>,
  // react-markdown v9+ removed the `inline` prop. Fenced code blocks are
  // always wrapped in <pre>, so the <pre> override styles block code and
  // this bare <code> override styles inline code only.
  code: ({ children }) => (
    <code className="text-accent-cyan rounded bg-black/30 px-1 py-0.5 font-mono text-xs">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs text-slate-200">
      {children}
    </pre>
  ),
  ul: ({ children }) => <ul className="my-1 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="text-sm leading-relaxed text-slate-300">{children}</li>,
  a: ({ children, href }) => (
    <a
      href={href}
      onClick={(e: React.MouseEvent<HTMLAnchorElement>) => {
        e.preventDefault();
        openExternalLink(href);
      }}
      className="text-accent-cyan hover:underline"
    >
      {children}
    </a>
  ),
};

const BADGE_CLASSES: Record<BadgeTone, string> = {
  green: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200',
  amber: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  slate: 'border-slate-400/30 bg-slate-400/10 text-slate-200',
  pending: 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200',
};

const RELEASE_NOTES_FALLBACK = 'No release notes published for this version.';

export function UpdateModal({
  isOpen,
  targetVersion,
  currentVersion,
  onClose,
  onConfirmInstall,
}: UpdateModalProps) {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [compat, setCompat] = useState<CompatResult | null>(null);
  const [compatPending, setCompatPending] = useState(true);
  const [releaseNotes, setReleaseNotes] = useState<string | null>(null);
  const [serverLatest, setServerLatest] = useState<string | null>(null);
  const [pullInProgress, setPullInProgress] = useState(false);
  // Guard against setState after unmount (modal closed while pullImage is
  // in-flight). Set to false in the cleanup; every async continuation checks
  // before touching state or firing user-visible side effects.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Entry / exit lifecycle — matches BugReportModal double-RAF + 500ms exit.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let rafId = 0;

    if (isOpen) {
      setIsRendered(true);
      setIsVisible(false);
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => setIsVisible(true));
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), EXIT_MS);
    }

    return () => {
      if (timer) clearTimeout(timer);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  // Fetch compat + release notes on every open (no cross-open caching).
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    setCompat(null);
    setCompatPending(true);
    setReleaseNotes(null);
    setServerLatest(null);

    const api = window.electronAPI?.updates;
    if (!api) {
      setCompatPending(false);
      return;
    }

    api
      .checkCompatibility()
      .then((result) => {
        if (!cancelled) {
          setCompat(result);
          setCompatPending(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCompat({
            result: 'unknown',
            reason: 'manifest-fetch-failed',
            detail: err instanceof Error ? err.message : String(err),
          });
          setCompatPending(false);
        }
      });

    api
      .getStatus()
      .then((status) => {
        if (cancelled || !status) return;
        setReleaseNotes(status.app.releaseNotes ?? null);
        setServerLatest(status.server.latest ?? null);
      })
      .catch(() => {
        // Best-effort; fallback copy handles null.
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const refreshCompat = useCallback(async () => {
    const api = window.electronAPI?.updates;
    if (!api) return;
    setCompatPending(true);
    try {
      const result = await api.checkCompatibility();
      setCompat(result);
    } catch (err) {
      setCompat({
        result: 'unknown',
        reason: 'manifest-fetch-failed',
        detail: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setCompatPending(false);
    }
  }, []);

  const handleUpdateServerFirst = useCallback(async () => {
    const dockerApi = window.electronAPI?.docker;
    if (!dockerApi || !serverLatest) {
      toast.error('Server image tag unavailable — try again after the next update check.');
      return;
    }
    setPullInProgress(true);
    try {
      await dockerApi.pullImage(serverLatest);
      // Modal may have closed during the pull. Skip user-visible side
      // effects on unmounted component — prevents setState-on-unmounted
      // warnings and orphan toasts that confuse the user.
      if (!mountedRef.current) return;
      toast.success(
        'Server image updated. Restart the server from the Server tab to apply, then re-run the update.',
      );
      await refreshCompat();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`Server image pull failed: ${message}`);
    } finally {
      if (mountedRef.current) setPullInProgress(false);
    }
  }, [serverLatest, refreshCompat]);

  // Latch for double-click / Enter-key protection during the 500ms exit
  // animation: once the user has confirmed install, suppress subsequent
  // invocations so `api.download()` fires at most once per open.
  const confirmedRef = useRef(false);
  useEffect(() => {
    if (isOpen) confirmedRef.current = false;
  }, [isOpen]);

  const handleInstall = useCallback(() => {
    if (confirmedRef.current) return;
    confirmedRef.current = true;
    onConfirmInstall();
    onClose();
  }, [onConfirmInstall, onClose]);

  if (!isRendered) return null;

  const badge = deriveBadgeContent(compat, compatPending);
  const isIncompatible = compat?.result === 'incompatible';
  const showServerFirst = isIncompatible && compat.deployment === 'local';
  // Guard Install against: pending verdict, unresolved verdict (non-Electron
  // context where compat was never fetched), incompatible servers, and
  // in-flight pulls. Double-click during the 500ms exit animation is
  // defended separately via confirmedRef in handleInstall — which is
  // timing-independent, unlike an `!isVisible` check that breaks in jsdom
  // (no real requestAnimationFrame).
  const installDisabled = compatPending || compat === null || isIncompatible || pullInProgress;
  const notesToRender = releaseNotes && releaseNotes.length > 0 ? releaseNotes : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Dashboard update — release notes and install confirmation"
    >
      {/* Backdrop — click-to-close is suppressed during an in-flight pull so
          the user cannot orphan a Docker operation by fat-fingering outside
          the card. */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={pullInProgress ? undefined : onClose}
      />

      {/* Modal card */}
      <div
        className={`relative flex w-full max-w-xl flex-col overflow-hidden rounded-3xl border border-white/20 bg-black/40 bg-linear-to-b from-white/5 to-black/20 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'}`}
      >
        <div className="bg-accent-cyan/20 pointer-events-none absolute top-0 left-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="bg-accent-magenta/10 pointer-events-none absolute right-0 bottom-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="pointer-events-none absolute inset-0 bg-black/20" />

        {/* Header */}
        <div className="relative flex items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4">
          <div className="flex items-center gap-3">
            <Download size={20} className="text-accent-cyan" />
            <div className="flex flex-col">
              <h2 className="text-lg font-semibold text-white">Dashboard update</h2>
              <p className="text-xs text-slate-400">
                {currentVersion ? `v${currentVersion} → ` : ''}
                {targetVersion ? `v${targetVersion}` : 'latest'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-full border border-white/10 bg-black/10 p-2 text-white backdrop-blur-md transition-colors hover:bg-black/40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="relative z-0 flex flex-col gap-4 px-6 py-5">
          {/* Verdict badge */}
          <div
            role="status"
            aria-label="Server compatibility"
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${BADGE_CLASSES[badge.tone]}`}
          >
            <span className="flex-shrink-0">{badge.icon}</span>
            <span className="leading-snug">{badge.text}</span>
          </div>

          {/* Release notes */}
          <div
            className="max-h-80 overflow-y-auto rounded-lg border border-white/10 bg-black/20 px-4 py-3"
            data-testid="release-notes"
          >
            {notesToRender ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={RELEASE_NOTES_MARKDOWN_COMPONENTS}
              >
                {notesToRender}
              </ReactMarkdown>
            ) : (
              <p className="text-sm text-slate-400 italic">{RELEASE_NOTES_FALLBACK}</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="relative flex items-center justify-end gap-2 border-t border-white/10 bg-white/5 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={pullInProgress}
            title={pullInProgress ? 'Server pull in progress — wait for it to finish' : undefined}
            className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Cancel
          </button>
          {showServerFirst && (
            <button
              type="button"
              onClick={handleUpdateServerFirst}
              disabled={pullInProgress}
              className="inline-flex items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-2 text-sm font-medium text-amber-100 transition-colors hover:bg-amber-400/20 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {pullInProgress ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ServerIcon size={14} />
              )}
              Update Server First
            </button>
          )}
          <button
            type="button"
            onClick={handleInstall}
            disabled={installDisabled}
            className="from-accent-cyan shadow-accent-cyan/20 hover:shadow-accent-cyan/40 inline-flex items-center gap-2 rounded-lg bg-linear-to-r to-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-lg transition-shadow disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download size={14} />
            Install Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
