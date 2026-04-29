import React, { useEffect, useRef, useState } from 'react';
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

const STATE_BORDER: Record<CardState, string> = {
  green: 'border-green-600',
  yellow: 'border-amber-600',
  red: 'border-red-700',
};

const STATE_TEXT: Record<CardState, string> = {
  green: 'text-green-600',
  yellow: 'text-amber-600',
  red: 'text-red-700',
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

export function GpuHealthCard({
  gpuDetected,
  preflight,
  backendError,
  onRunDiagnostic,
}: GpuHealthCardProps): React.ReactElement | null {
  if (!gpuDetected) return null;

  const state = deriveState(preflight, backendError);
  const failedChecks = preflight ? preflight.checks.filter((c) => !c.pass) : [];

  return (
    <section
      aria-labelledby="gpu-health-title"
      className={`mt-3 rounded-md border p-3 ${STATE_BORDER[state]}`}
    >
      <h3 id="gpu-health-title" className={`mt-0 ${STATE_TEXT[state]}`}>
        GPU Health (NVIDIA)
      </h3>
      <p className="mt-0 text-xs text-neutral-400">
        This card appears only on systems with an NVIDIA GPU. AMD / Intel / Apple Silicon setups do
        not need it.
      </p>

      <p className="font-semibold">{STATE_LABEL[state]}</p>

      {state === 'red' && backendError?.recovery_hint ? (
        <p className="rounded bg-red-900/50 p-2 text-sm text-red-200">
          {backendError.recovery_hint}
        </p>
      ) : null}

      {failedChecks.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1 font-medium">Failing checks:</p>
          {failedChecks.map((check) => (
            <div key={check.name} className="mb-2.5">
              <div className="text-sm">
                ✗ {check.name}
                {check.docsUrl ? (
                  <>
                    {' — '}
                    <a href={check.docsUrl} target="_blank" rel="noopener noreferrer">
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

      <div className="mt-3">
        <Button variant="secondary" size="sm" onClick={onRunDiagnostic}>
          Run Full Diagnostic
        </Button>
      </div>
    </section>
  );
}
