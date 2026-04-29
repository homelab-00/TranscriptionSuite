// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { GpuHealthCard } from '../GpuHealthCard';

const healthyPreflight = {
  status: 'healthy' as const,
  checks: [
    { name: 'CDI spec exists', pass: true },
    { name: 'CDI spec newer than driver', pass: true },
    { name: '/dev/char NVIDIA symlinks', pass: true },
    { name: 'nvidia_uvm module loaded', pass: true },
  ],
};

const warningPreflight = {
  status: 'warning' as const,
  checks: [
    { name: 'CDI spec exists', pass: true },
    { name: 'CDI spec newer than driver', pass: true },
    {
      name: '/dev/char NVIDIA symlinks',
      pass: false,
      fixCommand: 'sudo nvidia-ctk system create-dev-char-symlinks --create-all',
      docsUrl: 'https://github.com/NVIDIA/nvidia-container-toolkit/issues/48',
    },
    { name: 'nvidia_uvm module loaded', pass: true },
  ],
};

describe('GpuHealthCard', () => {
  it('renders nothing when no NVIDIA GPU is detected', () => {
    const { container } = render(
      <GpuHealthCard
        gpuDetected={false}
        preflight={null}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the NVIDIA-only label so non-NVIDIA users are not confused', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/GPU Health \(NVIDIA\)/i)).toBeInTheDocument();
  });

  it('green state: healthy preflight + no backend error', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/CUDA operational/i)).toBeInTheDocument();
  });

  it('yellow state: preflight has a failed check, no backend error', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={warningPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/may be misconfigured/i)).toBeInTheDocument();
    expect(
      screen.getByText('sudo nvidia-ctk system create-dev-char-symlinks --create-all'),
    ).toBeInTheDocument();
  });

  it('red state: backend reported unrecoverable; recovery_hint shown verbatim', () => {
    const backendError = {
      status: 'unrecoverable' as const,
      error: 'CUDA unknown error',
      recovery_hint: 'GPU init failed with error 999 (CUDA unknown). Run scripts/diagnose-gpu.sh.',
    };
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={warningPreflight}
        backendError={backendError}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/GPU unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/Run scripts\/diagnose-gpu\.sh/)).toBeInTheDocument();
  });

  it('clicking Run Full Diagnostic invokes the prop', async () => {
    const onRun = vi.fn();
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={onRun}
      />,
    );
    const button = screen.getByRole('button', { name: /Run Full Diagnostic/i });
    button.click();
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});
