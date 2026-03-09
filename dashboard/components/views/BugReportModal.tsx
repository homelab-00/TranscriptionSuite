import React, { useState, useEffect, useRef } from 'react';
import { X, Bug, ExternalLink, CheckCircle } from 'lucide-react';

interface BugReportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const REPO_ISSUES_URL = 'https://github.com/homelab-00/TranscriptionSuite/issues/new';
const LOG_TAIL_LINES = 150;
/** GitHub URL max is ~8192 chars; leave room for the rest of the URL. */
const MAX_BODY_LENGTH = 7000;

export const BugReportModal: React.FC<BugReportModalProps> = ({ isOpen, onClose }) => {
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [description, setDescription] = useState('');
  const [appVersion, setAppVersion] = useState<string>(import.meta.env.VITE_APP_VERSION ?? '0.0.0');
  const [platform, setPlatform] = useState<string>('');
  const [clientLogPath, setClientLogPath] = useState<string>('');
  const [serverLogPath, setServerLogPath] = useState<string>('');
  const [clientLog, setClientLog] = useState<string>('');
  const [serverLog, setServerLog] = useState<string>('');
  const [submitted, setSubmitted] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const openExternal = async (url: string): Promise<void> => {
    try {
      if (window.electronAPI?.app?.openExternal) {
        await window.electronAPI.app.openExternal(url);
        return;
      }
    } catch {
      // Fall through
    }
    if (!window.electronAPI) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;

    if (isOpen) {
      setIsRendered(true);
      setIsVisible(false);
      setSubmitted(false);
      setDescription('');

      const api = window.electronAPI;
      if (api?.app) {
        api.app
          .getVersion()
          .then((v: string) => {
            if (v) setAppVersion(v);
          })
          .catch(() => {});
        setPlatform(api.app.getPlatform?.() ?? '');

        api.app
          .readLogFiles(LOG_TAIL_LINES)
          .then((result) => {
            setClientLog(result.clientLog);
            setServerLog(result.serverLog);
            setClientLogPath(result.clientLogPath);
            setServerLogPath(result.serverLogPath);
          })
          .catch(() => {});
      }

      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 500);
    }

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  // Auto-focus textarea on visible
  useEffect(() => {
    if (isVisible && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isVisible]);

  const handleSubmit = () => {
    const title = encodeURIComponent('Bug Report');
    const sysInfo = `**Version:** ${appVersion}\n**Platform:** ${platform}`;

    // Build body with truncation to stay within URL limits
    let body = `## Description\n\n${description || '_No description provided._'}\n\n## System Info\n\n${sysInfo}`;

    const clientLogSection = clientLog
      ? `\n\n<details><summary>Client Log (last ${LOG_TAIL_LINES} lines)</summary>\n\n\`\`\`\n${clientLog}\n\`\`\`\n\n</details>`
      : '';
    const serverLogSection = serverLog
      ? `\n\n<details><summary>Server Log (last ${LOG_TAIL_LINES} lines)</summary>\n\n\`\`\`\n${serverLog}\n\`\`\`\n\n</details>`
      : '';

    body += clientLogSection + serverLogSection;

    // Truncate if too long for a URL
    if (body.length > MAX_BODY_LENGTH) {
      body = body.slice(0, MAX_BODY_LENGTH) + '\n\n_(truncated — attach full logs manually)_';
    }

    const url = `${REPO_ISSUES_URL}?title=${title}&body=${encodeURIComponent(body)}`;
    void openExternal(url);
    setSubmitted(true);
  };

  if (!isRendered) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity duration-500 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />

      {/* Modal Content */}
      <div
        className={`relative flex w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/20 bg-black/40 bg-linear-to-b from-white/5 to-black/20 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-[100vh] opacity-0'} `}
      >
        <div className="bg-accent-cyan/20 pointer-events-none absolute top-0 left-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="bg-accent-magenta/10 pointer-events-none absolute right-0 bottom-0 h-32 w-32 rounded-full blur-2xl" />
        <div className="pointer-events-none absolute inset-0 bg-black/20" />

        {/* Header */}
        <div className="relative flex items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4">
          <div className="flex items-center gap-3">
            <Bug size={20} className="text-accent-cyan" />
            <h2 className="text-lg font-semibold text-white">Bug Report</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-white/10 bg-black/10 p-2 text-white backdrop-blur-md transition-colors hover:bg-black/40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="relative z-0 flex flex-col gap-4 px-6 py-5">
          {!submitted ? (
            <>
              {/* Description */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">
                  Describe the issue
                </label>
                <textarea
                  ref={textareaRef}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What happened? What did you expect?"
                  rows={4}
                  className="w-full resize-none rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white placeholder-slate-500 backdrop-blur-sm transition-colors focus:border-white/20 focus:outline-none"
                />
              </div>

              {/* System Info Preview */}
              <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
                <p className="mb-1 text-xs font-medium text-slate-400">System Info</p>
                <p className="text-xs text-slate-300">
                  Version: {appVersion} &bull; Platform: {platform || 'unknown'}
                </p>
                <p className="mt-1.5 text-xs text-slate-500">
                  {clientLog ? '✓' : '✗'} Client log &bull; {serverLog ? '✓' : '✗'} Server log
                </p>
              </div>

              {/* Submit */}
              <button
                onClick={handleSubmit}
                className="bg-accent-cyan/20 border-accent-cyan/30 text-accent-cyan hover:bg-accent-cyan/30 flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors"
              >
                <ExternalLink size={16} />
                Open GitHub Issue
              </button>
            </>
          ) : (
            /* Post-submit confirmation */
            <div className="flex flex-col items-center gap-4 py-4">
              <CheckCircle size={40} className="text-accent-cyan" />
              <p className="text-center text-sm text-slate-300">
                Issue page opened in your browser. For complete logs, attach these files to the
                issue:
              </p>
              <div className="w-full space-y-1 rounded-xl border border-white/10 bg-white/5 px-4 py-3">
                {clientLogPath && (
                  <p className="text-xs break-all text-slate-400">{clientLogPath}</p>
                )}
                {serverLogPath && (
                  <p className="text-xs break-all text-slate-400">{serverLogPath}</p>
                )}
              </div>
              <button
                onClick={onClose}
                className="rounded-xl border border-white/10 bg-white/5 px-6 py-2 text-sm text-white transition-colors hover:bg-white/10"
              >
                Close
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
