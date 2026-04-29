import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { Button } from '../ui/Button';
import { writeToClipboard } from '../../src/hooks/useClipboard';

export interface GpuPreflightCheckProp {
  name: string;
  pass: boolean;
  fixCommand?: string;
  docsUrl?: string;
}

export interface GpuPreflightProp {
  status: 'healthy' | 'warning' | 'unknown';
  checks: GpuPreflightCheckProp[];
}

export interface GpuBackendErrorProp {
  status: 'unrecoverable';
  error: string;
  recovery_hint?: string;
}

export interface GpuHealthCardProps {
  gpuDetected: boolean;
  preflight: GpuPreflightProp | null;
  backendError: GpuBackendErrorProp | null;
  onRunDiagnostic: () => void;
  /** When true, the Run Full Diagnostic button is disabled and shows a "Running…" label. */
  running?: boolean;
}

type CardState = 'green' | 'yellow' | 'red';

function deriveState(
  preflight: GpuPreflightProp | null,
  backendError: GpuBackendErrorProp | null,
): CardState {
  if (backendError && backendError.status === 'unrecoverable') return 'red';
  if (preflight && preflight.status === 'warning') return 'yellow';
  return 'green';
}

const STATE_LABEL: Record<CardState, string> = {
  green: 'GPU healthy — CUDA operational',
  yellow: 'GPU may be misconfigured — server will fall back to CPU',
  red: 'GPU unavailable — fell back to CPU',
};

const STATE_CONTAINER: Record<CardState, string> = {
  green: 'border-green-500/20 bg-green-500/5',
  yellow: 'border-accent-orange/20 bg-accent-orange/5',
  red: 'border-red-500/20 bg-red-500/5',
};

const STATE_BODY_TEXT: Record<CardState, string> = {
  green: 'text-green-400',
  yellow: 'text-accent-orange',
  red: 'text-red-400',
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
    <div className="mt-1 flex items-center gap-2">
      <code className="flex-1 overflow-x-auto rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-100">
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

function StateIcon({ state }: { state: CardState }): React.ReactElement {
  if (state === 'green') return <CheckCircle2 size={18} className="text-green-400" />;
  if (state === 'yellow') return <AlertTriangle size={18} className="text-accent-orange" />;
  return <XCircle size={18} className="text-red-400" />;
}

export function GpuHealthCard({
  gpuDetected,
  preflight,
  backendError,
  onRunDiagnostic,
  running = false,
}: GpuHealthCardProps): React.ReactElement | null {
  if (!gpuDetected) return null;

  const state = deriveState(preflight, backendError);
  const failedChecks = preflight ? preflight.checks.filter((c) => !c.pass) : [];
  const totalChecks = preflight ? preflight.checks.length : 0;
  const passedChecks = totalChecks - failedChecks.length;
  const headerStatus =
    state === 'red'
      ? 'backend error — CPU fallback'
      : totalChecks > 0
        ? `${passedChecks}/${totalChecks} checks passed`
        : 'CUDA operational';

  return (
    <section
      aria-labelledby="gpu-health-title"
      className={`overflow-hidden rounded-xl border transition-all duration-300 ${STATE_CONTAINER[state]}`}
    >
      <div className="flex items-center gap-3 px-5 py-3.5">
        <StateIcon state={state} />
        <h3 id="gpu-health-title" className="m-0 text-sm font-semibold text-white">
          GPU Health (NVIDIA)
        </h3>
        <span className="font-mono text-xs text-slate-500">{headerStatus}</span>
      </div>

      <div className="space-y-2.5 px-5 pb-4">
        <p className="m-0 text-xs text-slate-400">
          This card appears only on systems with an NVIDIA GPU. AMD / Intel / Apple Silicon setups
          do not need it.
        </p>

        <p className={`m-0 text-sm font-semibold ${STATE_BODY_TEXT[state]}`}>
          {STATE_LABEL[state]}
        </p>

        {state === 'red' && backendError?.recovery_hint ? (
          <p className="m-0 rounded bg-red-500/10 p-2 text-sm text-red-200">
            {backendError.recovery_hint}
          </p>
        ) : null}

        {failedChecks.length > 0 ? (
          <div className="pt-1">
            <p className="m-0 mb-1 text-sm font-medium text-white">Failing checks:</p>
            {failedChecks.map((check) => (
              <div key={check.name} className="mb-2.5">
                <div className="text-sm text-slate-300">
                  ✗ {check.name}
                  {check.docsUrl ? (
                    <>
                      {' — '}
                      <a
                        href={check.docsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent-cyan hover:underline"
                      >
                        docs
                      </a>
                    </>
                  ) : null}
                </div>
                {check.fixCommand ? <CopyableCommand cmd={check.fixCommand} /> : null}
              </div>
            ))}
          </div>
        ) : null}

        <div className="pt-1">
          <Button variant="secondary" size="sm" onClick={onRunDiagnostic} disabled={running}>
            {running ? 'Running diagnostic…' : 'Run Full Diagnostic'}
          </Button>
        </div>
      </div>
    </section>
  );
}
