/**
 * gh-86 #3 — LogsView Metal-mode subscription retry.
 *
 * Verifies the polling retry that hardens against the renderer mounting
 * before `window.electronAPI.mlx` has been bound by the preload script:
 *   - first sync attempt at mount; if successful → no polling at all
 *   - on failure: setInterval(250 ms) up to 10 attempts (~2.5 s budget)
 *   - on first success: subscription attaches, polling stops
 *   - after 10 consecutive failures: console.warn once, polling stops
 */

import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { LogsView } from '../views/LogsView';

vi.mock('../../src/hooks/DockerContext', () => ({
  useDockerContext: () => ({
    container: { exists: false, running: false },
    logLines: [],
    operationError: null,
    startLogStream: vi.fn(),
    stopLogStream: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useClientDebugLogs', () => ({
  useClientDebugLogs: () => ({ logs: [] }),
}));

vi.mock('../../src/hooks/useClipboard', () => ({
  writeToClipboard: vi.fn().mockResolvedValue(undefined),
}));

interface MockMlx {
  getLogs: ReturnType<typeof vi.fn>;
  onLogLine: ReturnType<typeof vi.fn>;
}

function makeMockMlx(): { mlx: MockMlx; unsub: ReturnType<typeof vi.fn> } {
  const unsub = vi.fn();
  const mlx: MockMlx = {
    getLogs: vi.fn().mockResolvedValue([]),
    onLogLine: vi.fn().mockReturnValue(unsub),
  };
  return { mlx, unsub };
}

describe('[P2] LogsView — Metal subscription retry', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    delete (window as { electronAPI?: unknown }).electronAPI;
  });

  afterEach(() => {
    vi.useRealTimers();
    warnSpy.mockRestore();
    delete (window as { electronAPI?: unknown }).electronAPI;
  });

  it('does not throw when window.electronAPI is undefined at mount', () => {
    expect(() => render(<LogsView runtimeProfile="metal" />)).not.toThrow();
  });

  it('attaches subscription synchronously when electronAPI.mlx is already defined at mount', async () => {
    const { mlx } = makeMockMlx();
    (window as unknown as { electronAPI: { mlx: MockMlx } }).electronAPI = { mlx };

    await act(async () => {
      render(<LogsView runtimeProfile="metal" />);
    });

    expect(mlx.getLogs).toHaveBeenCalledWith(500);
    expect(mlx.onLogLine).toHaveBeenCalledTimes(1);
  });

  it('attaches once electronAPI.mlx becomes available within the retry budget', async () => {
    const { mlx } = makeMockMlx();

    await act(async () => {
      render(<LogsView runtimeProfile="metal" />);
    });

    // electronAPI is undefined → first sync attempt fails, polling starts.
    expect(mlx.getLogs).not.toHaveBeenCalled();

    // Advance 3 polls (750 ms) — still no electronAPI.
    await act(async () => {
      vi.advanceTimersByTime(750);
    });
    expect(mlx.getLogs).not.toHaveBeenCalled();

    // Now expose electronAPI and let one more poll fire.
    (window as unknown as { electronAPI: { mlx: MockMlx } }).electronAPI = { mlx };
    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    expect(mlx.getLogs).toHaveBeenCalledWith(500);
    expect(mlx.onLogLine).toHaveBeenCalledTimes(1);
  });

  it('warns exactly once after 10 failed polling attempts and stops polling', () => {
    render(<LogsView runtimeProfile="metal" />);

    // 10 polling attempts at 250 ms each = 2500 ms total.
    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[LogsView] electronAPI.mlx not available after retry — Metal logs unavailable',
    );

    // Advancing further must not warn again — polling has stopped.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('stops polling on unmount before the budget is exhausted', () => {
    const { unmount } = render(<LogsView runtimeProfile="metal" />);

    act(() => {
      vi.advanceTimersByTime(500);
    });

    unmount();

    // After unmount, even waiting beyond MAX_ATTEMPTS must not trigger the warn.
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not start polling when not in Metal mode', () => {
    const { mlx } = makeMockMlx();
    (window as unknown as { electronAPI: { mlx: MockMlx } }).electronAPI = { mlx };

    render(<LogsView runtimeProfile="docker" />);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(mlx.getLogs).not.toHaveBeenCalled();
    expect(mlx.onLogLine).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('treats a malformed preload binding (mlx.onLogLine throws) as terminal — no error spam', async () => {
    // Simulate a preload that exposes `mlx` but with a broken onLogLine method.
    // Without the try/catch in tryAttach, the setInterval callback would
    // re-throw every 250 ms forever (Node does not auto-clear interval
    // callbacks on uncaught exceptions).
    const broken = {
      getLogs: vi.fn().mockResolvedValue([]),
      onLogLine: vi.fn().mockImplementation(() => {
        throw new TypeError('contextBridge stub');
      }),
    };
    (window as unknown as { electronAPI: { mlx: typeof broken } }).electronAPI = { mlx: broken };

    await act(async () => {
      render(<LogsView runtimeProfile="metal" />);
    });

    // Warning fires exactly once on the synchronous attach attempt.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[LogsView] failed to attach mlx subscription:',
      expect.any(TypeError),
    );

    // Polling should NOT continue spamming after the throw.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(broken.onLogLine).toHaveBeenCalledTimes(1);
  });
});
