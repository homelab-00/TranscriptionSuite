// @vitest-environment jsdom
/**
 * Renders the modal across the three product-meaningful states:
 *   • completed + stale-CDI WARN  -> shows the regenerate command
 *   • completed + script-missing  -> shows manual command, hides Open Log
 *   • completed clicks Open Log   -> calls electronAPI.app.openPath verbatim
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { GpuDiagnosticModal, type GpuDiagnosticResultProp } from '../GpuDiagnosticModal';

interface ElectronAPIShape {
  app?: { openPath?: (p: string) => Promise<string> };
}

function withElectronApi(api: ElectronAPIShape): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).electronAPI = api;
}

const STALE_CDI_RESULT: GpuDiagnosticResultProp = {
  status: 'completed',
  logPath: '/home/user/.config/transcription-suite/gpu-diagnostics/gpu-diagnostic-x.log',
  scriptPath: '/opt/app/scripts/diagnose-gpu.sh',
  manualCommand: 'bash /opt/app/scripts/diagnose-gpu.sh',
  exitCode: 0,
  summary: {
    passCount: 9,
    warnCount: 1,
    failCount: 0,
    parsed: true,
    issues: [
      {
        status: 'WARN',
        checkNumber: 4,
        title: 'CDI spec vs driver mtime',
        detail:
          'CDI spec is older than driver modules — regenerate with: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
        suggestedCommand: 'sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
      },
    ],
  },
};

const SCRIPT_MISSING_RESULT: GpuDiagnosticResultProp = {
  status: 'script-missing',
  scriptPath: '/opt/app/scripts/diagnose-gpu.sh',
  manualCommand: 'bash /opt/app/scripts/diagnose-gpu.sh',
};

describe('GpuDiagnosticModal', () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = undefined;
  });

  it('renders nothing when not open', () => {
    const { container } = render(
      <GpuDiagnosticModal isOpen={false} result={STALE_CDI_RESULT} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('surfaces the stale-CDI WARN row with the regenerate command (real user repro)', () => {
    render(<GpuDiagnosticModal isOpen={true} result={STALE_CDI_RESULT} onClose={() => {}} />);

    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText(/CDI spec vs driver mtime/)).toBeTruthy();
    expect(
      screen.getByText(/CDI spec is older than driver modules — regenerate with:/),
    ).toBeTruthy();
    expect(
      screen.getByText('sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml'),
    ).toBeTruthy();
    expect(screen.getByText(/9 PASS/)).toBeTruthy();
  });

  it('clicking Open Log calls electronAPI.app.openPath with the log path', () => {
    const openPath = vi.fn().mockResolvedValue('');
    withElectronApi({ app: { openPath } });

    render(<GpuDiagnosticModal isOpen={true} result={STALE_CDI_RESULT} onClose={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: /Open Log/i }));
    expect(openPath).toHaveBeenCalledTimes(1);
    expect(openPath).toHaveBeenCalledWith(STALE_CDI_RESULT.logPath);
  });

  it('script-missing: shows manual command and hides Open Log', () => {
    render(<GpuDiagnosticModal isOpen={true} result={SCRIPT_MISSING_RESULT} onClose={() => {}} />);

    expect(screen.getByText(/Diagnostic script not bundled/)).toBeTruthy();
    expect(screen.getByText(SCRIPT_MISSING_RESULT.manualCommand!)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Open Log/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Copy Path/i })).toBeNull();
  });

  it('Escape key closes the modal', () => {
    const onClose = vi.fn();
    render(<GpuDiagnosticModal isOpen={true} result={STALE_CDI_RESULT} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('all-pass case: shows green banner and "All checks passed" copy with no rows', () => {
    const allPass: GpuDiagnosticResultProp = {
      status: 'completed',
      logPath: '/var/log/x.log',
      summary: { passCount: 11, warnCount: 0, failCount: 0, parsed: true, issues: [] },
      exitCode: 0,
    };
    render(<GpuDiagnosticModal isOpen={true} result={allPass} onClose={() => {}} />);
    expect(screen.getByText(/11 PASS/)).toBeTruthy();
    expect(screen.getByText(/All checks passed/)).toBeTruthy();
  });
});
