import React, { useState } from 'react';

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

const STATE_COLOR: Record<CardState, string> = {
  green: '#1f8a3a',
  yellow: '#b88a00',
  red: '#b53030',
};

function CopyableCommand({ cmd }: { cmd: string }): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const handleCopy = (): void => {
    void navigator.clipboard.writeText(cmd).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
      <code
        style={{
          padding: '4px 8px',
          background: '#222',
          color: '#eee',
          borderRadius: 4,
          fontSize: 12,
          flex: 1,
          overflowX: 'auto',
        }}
      >
        {cmd}
      </code>
      <button type="button" onClick={handleCopy} style={{ fontSize: 12 }}>
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
      style={{
        border: `1px solid ${STATE_COLOR[state]}`,
        borderRadius: 6,
        padding: 12,
        marginTop: 12,
      }}
    >
      <h3 id="gpu-health-title" style={{ marginTop: 0, color: STATE_COLOR[state] }}>
        GPU Health (NVIDIA)
      </h3>
      <p style={{ fontSize: 12, marginTop: 0, color: '#888' }}>
        This card appears only on systems with an NVIDIA GPU. AMD / Intel / Apple Silicon setups do
        not need it.
      </p>

      <p style={{ fontWeight: 600 }}>{STATE_LABEL[state]}</p>

      {state === 'red' && backendError?.recovery_hint ? (
        <p
          style={{
            background: '#3a1313',
            padding: 8,
            borderRadius: 4,
            color: '#fbb',
            fontSize: 13,
          }}
        >
          {backendError.recovery_hint}
        </p>
      ) : null}

      {failedChecks.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <p style={{ marginBottom: 4, fontWeight: 500 }}>Failing checks:</p>
          {failedChecks.map((check) => (
            <div key={check.name} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 13 }}>
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

      <div style={{ marginTop: 12 }}>
        <button type="button" onClick={onRunDiagnostic}>
          Run Full Diagnostic
        </button>
      </div>
    </section>
  );
}
