/**
 * useTraySync push-to-talk action dispatch.
 *
 * Verifies that the ptt-stop-recording tray action (sent by the Wayland
 * portal layer on a held-shortcut release) dispatches to onPttStopRecording
 * and does NOT fall through to onStopRecording, which would also stop Live
 * Mode in SessionView.
 */

import { describe, it, expect, vi, beforeAll } from 'vitest';
import { renderHook, act } from '@testing-library/react';

type ActionListener = (action: string, ...args: unknown[]) => void;

let actionListener: ActionListener | null = null;

function installElectronApiStub() {
  (window as any).electronAPI = {
    tray: {
      setMenuState: vi.fn(),
      setState: vi.fn(),
      setTooltip: vi.fn(),
      onAction: vi.fn((cb: ActionListener) => {
        actionListener = cb;
        return () => {
          actionListener = null;
        };
      }),
    },
  };
}

// isElectron is computed at module load, so the stub must be installed
// BEFORE useTraySync is imported — hence the dynamic import.
let useTraySync: typeof import('../useTraySync').useTraySync;

beforeAll(async () => {
  installElectronApiStub();
  ({ useTraySync } = await import('../useTraySync'));
});

function baseDeps(overrides: Record<string, unknown> = {}) {
  return {
    serverStatus: 'active',
    containerRunning: true,
    containerHealth: 'healthy',
    transcriptionStatus: 'idle',
    liveStatus: 'idle',
    muted: false,
    ...overrides,
  } as any;
}

describe('[P2] useTraySync push-to-talk dispatch', () => {
  it('dispatches ptt-stop-recording to onPttStopRecording only', () => {
    const onPttStopRecording = vi.fn();
    const onStopRecording = vi.fn();

    renderHook(() => useTraySync(baseDeps({ onPttStopRecording, onStopRecording })));

    expect(actionListener).not.toBeNull();
    act(() => {
      actionListener!('ptt-stop-recording');
    });

    expect(onPttStopRecording).toHaveBeenCalledTimes(1);
    expect(onStopRecording).not.toHaveBeenCalled();
  });

  it('keeps dispatching stop-recording to onStopRecording', () => {
    const onPttStopRecording = vi.fn();
    const onStopRecording = vi.fn();

    renderHook(() => useTraySync(baseDeps({ onPttStopRecording, onStopRecording })));

    act(() => {
      actionListener!('stop-recording');
    });

    expect(onStopRecording).toHaveBeenCalledTimes(1);
    expect(onPttStopRecording).not.toHaveBeenCalled();
  });

  it('ignores ptt-stop-recording when no callback is wired', () => {
    const onStopRecording = vi.fn();

    renderHook(() => useTraySync(baseDeps({ onStopRecording })));

    expect(() => {
      act(() => {
        actionListener!('ptt-stop-recording');
      });
    }).not.toThrow();
    expect(onStopRecording).not.toHaveBeenCalled();
  });
});
