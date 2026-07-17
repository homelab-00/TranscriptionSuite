import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';

import { loopbackOwner, LOOPBACK_DEVICE_LABEL, LOOPBACK_RELEASE_GRACE_MS } from './loopbackOwner';

// ── Mocks ──────────────────────────────────────────────────────────────

let createMock: Mock;
let removeMock: Mock;

function installElectronAudioMock(): void {
  createMock = vi.fn().mockResolvedValue({ moduleId: 42, volumePct: 100 });
  removeMock = vi.fn().mockResolvedValue(undefined);
  (window as unknown as { electronAPI: unknown }).electronAPI = {
    audio: {
      createMonitorLoopback: createMock,
      removeMonitorLoopback: removeMock,
    },
  };
}

describe('[P1] loopbackOwner', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    installElectronAudioMock();
    // The singleton carries state between tests — drain any pending hold from
    // a previous test by releasing until idle and flushing the grace timer.
    loopbackOwner._resetForTests();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('acquire() creates the module once and returns the device label', async () => {
    const result = await loopbackOwner.acquire('sink-a');
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(createMock).toHaveBeenCalledWith('sink-a');
    expect(result.label).toBe(LOOPBACK_DEVICE_LABEL);
    expect(result.volumePct).toBe(100);
  });

  it('release() does not remove immediately — only after the grace window', async () => {
    await loopbackOwner.acquire('sink-a');
    loopbackOwner.release();
    expect(removeMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS - 1);
    expect(removeMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(removeMock).toHaveBeenCalledTimes(1);
  });

  it('re-acquire within the grace window reuses the module (no remove, no re-create)', async () => {
    await loopbackOwner.acquire('sink-a');
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(1000);
    const result = await loopbackOwner.acquire('sink-a');
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).not.toHaveBeenCalled();
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(result.label).toBe(LOOPBACK_DEVICE_LABEL);
  });

  it('re-acquire after grace expiry re-creates (create twice, remove once, in order)', async () => {
    await loopbackOwner.acquire('sink-a');
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS + 1);
    expect(removeMock).toHaveBeenCalledTimes(1);
    await loopbackOwner.acquire('sink-a');
    expect(createMock).toHaveBeenCalledTimes(2);
    // Strict ordering: create → remove → create
    const order = [
      createMock.mock.invocationCallOrder[0],
      removeMock.mock.invocationCallOrder[0],
      createMock.mock.invocationCallOrder[1],
    ];
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it('re-acquire with a DIFFERENT sink during grace re-creates against the new sink', async () => {
    await loopbackOwner.acquire('sink-a');
    loopbackOwner.release();
    await loopbackOwner.acquire('sink-b');
    expect(createMock).toHaveBeenCalledTimes(2);
    expect(createMock).toHaveBeenLastCalledWith('sink-b');
    // The stale grace timer from sink-a's release must not remove sink-b's module.
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).not.toHaveBeenCalled();
  });

  it('overlapping holds: remove only fires after the LAST hold releases', async () => {
    await loopbackOwner.acquire('sink-a');
    await loopbackOwner.acquire('sink-a');
    expect(createMock).toHaveBeenCalledTimes(1);
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).not.toHaveBeenCalled();
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS);
    expect(removeMock).toHaveBeenCalledTimes(1);
  });

  it('double release is idempotent (never double-removes, never goes negative)', async () => {
    await loopbackOwner.acquire('sink-a');
    loopbackOwner.release();
    loopbackOwner.release();
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).toHaveBeenCalledTimes(1);
    // A later acquire still works from clean state
    await loopbackOwner.acquire('sink-a');
    expect(createMock).toHaveBeenCalledTimes(2);
  });

  it('release with nothing held is a no-op', async () => {
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).not.toHaveBeenCalled();
  });

  it('create IPC rejection → acquire rejects, state stays clean, next acquire retries', async () => {
    createMock.mockRejectedValueOnce(new Error('pactl failed'));
    await expect(loopbackOwner.acquire('sink-a')).rejects.toThrow('pactl failed');
    // State clean: a release after the failed acquire must not schedule a removal
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS * 2);
    expect(removeMock).not.toHaveBeenCalled();
    // Retry works
    const result = await loopbackOwner.acquire('sink-a');
    expect(result.volumePct).toBe(100);
    expect(createMock).toHaveBeenCalledTimes(2);
  });

  it('missing electronAPI → acquire rejects without corrupting state', async () => {
    (window as unknown as { electronAPI: unknown }).electronAPI = undefined;
    await expect(loopbackOwner.acquire('sink-a')).rejects.toThrow();
    installElectronAudioMock();
    const result = await loopbackOwner.acquire('sink-a');
    expect(result.label).toBe(LOOPBACK_DEVICE_LABEL);
  });

  it('IPC calls are serialized — a post-grace re-acquire queues its create behind an in-flight remove', async () => {
    await loopbackOwner.acquire('sink-a');
    // Make the remove hang so it is genuinely in flight when the re-acquire
    // arrives — without the serialization chain the second create would run
    // immediately instead of waiting for the remove to settle.
    let resolveRemove!: () => void;
    removeMock.mockImplementationOnce(
      () =>
        new Promise<void>((res) => {
          resolveRemove = res;
        }),
    );
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS);
    expect(removeMock).toHaveBeenCalledTimes(1); // in flight, hanging

    const acquiring = loopbackOwner.acquire('sink-a');
    await vi.advanceTimersByTimeAsync(0); // flush microtasks
    // Pins the chain: the second create must NOT have started yet.
    expect(createMock).toHaveBeenCalledTimes(1);

    resolveRemove();
    await acquiring;
    expect(createMock).toHaveBeenCalledTimes(2);
    expect(createMock.mock.invocationCallOrder[1]).toBeGreaterThan(
      removeMock.mock.invocationCallOrder[0],
    );
  });

  it('subscribeVolumePct fires with pct on create and null when removal executes', async () => {
    const seen: Array<number | null> = [];
    const unsubscribe = loopbackOwner.subscribeVolumePct((pct) => seen.push(pct));
    await loopbackOwner.acquire('sink-a');
    expect(seen).toEqual([100]);
    loopbackOwner.release();
    await vi.advanceTimersByTimeAsync(LOOPBACK_RELEASE_GRACE_MS);
    expect(seen).toEqual([100, null]);
    unsubscribe();
    await loopbackOwner.acquire('sink-a');
    expect(seen).toEqual([100, null]);
  });
});
