import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';

import { AudioCapture } from './audioCapture';
import { loopbackOwner } from './loopbackOwner';

// ── Mocks ──────────────────────────────────────────────────────────────

vi.mock('./loopbackOwner', () => ({
  LOOPBACK_DEVICE_LABEL: 'TranscriptionSuite_Loopback',
  loopbackOwner: {
    acquire: vi.fn().mockResolvedValue({ label: 'TranscriptionSuite_Loopback', volumePct: 100 }),
    release: vi.fn(),
  },
}));

const acquireMock = loopbackOwner.acquire as unknown as Mock;
const releaseMock = loopbackOwner.release as unknown as Mock;

function makeTrack(): { stop: Mock; getSettings: Mock } {
  return { stop: vi.fn(), getSettings: vi.fn().mockReturnValue({ sampleRate: 48000 }) };
}

function makeStream(): {
  stream: MediaStream;
  audioTrack: ReturnType<typeof makeTrack>;
} {
  const audioTrack = makeTrack();
  const stream = {
    getTracks: () => [audioTrack],
    getAudioTracks: () => [audioTrack],
    getVideoTracks: () => [],
  } as unknown as MediaStream;
  return { stream, audioTrack };
}

let getUserMediaMock: Mock;
let enumerateDevicesMock: Mock;
let addModuleMock: Mock;

// Captures the most recently constructed FakeAudioContext so tests can
// inspect per-instance node mocks (e.g. distinguishing gainNode from
// micGainNode) without threading a reference through AudioCapture's private
// fields.
let lastCtx: FakeAudioContext | undefined;

class FakeAudioContext {
  sampleRate = 48000;
  state = 'running';
  audioWorklet = { addModule: (...args: unknown[]) => addModuleMock(...args) };
  // mockImplementation (not mockReturnValue) so each call gets its own node —
  // mixMicWithSystem calls both createMediaStreamSource and createGain twice
  // (primary + secondary), and a single cached return value would make the
  // mic and system-audio nodes indistinguishable.
  createMediaStreamSource = vi
    .fn()
    .mockImplementation(() => ({ connect: vi.fn(), disconnect: vi.fn() }));
  createGain = vi
    .fn()
    .mockImplementation(() => ({ connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } }));
  createAnalyser = vi.fn().mockReturnValue({
    connect: vi.fn(),
    disconnect: vi.fn(),
    fftSize: 0,
    smoothingTimeConstant: 0,
  });
  close = vi.fn().mockResolvedValue(undefined);

  constructor() {
    lastCtx = this;
  }
}

class FakeAudioWorkletNode {
  port = { onmessage: null as unknown };
  connect = vi.fn();
  disconnect = vi.fn();
}

describe('[P1] AudioCapture loopback ownership (GH-230)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    acquireMock.mockResolvedValue({ label: 'TranscriptionSuite_Loopback', volumePct: 100 });

    const { stream } = makeStream();
    getUserMediaMock = vi.fn().mockResolvedValue(stream);
    enumerateDevicesMock = vi.fn().mockResolvedValue([
      {
        kind: 'audioinput',
        label: 'Remapped TranscriptionSuite_Loopback source',
        deviceId: 'loopback-dev-1',
      },
    ]);
    addModuleMock = vi.fn().mockResolvedValue(undefined);

    Object.defineProperty(globalThis.navigator, 'mediaDevices', {
      value: {
        getUserMedia: getUserMediaMock,
        enumerateDevices: enumerateDevicesMock,
        getDisplayMedia: vi.fn().mockResolvedValue(makeStream().stream),
      },
      configurable: true,
    });
    vi.stubGlobal('AudioContext', FakeAudioContext);
    vi.stubGlobal('AudioWorkletNode', FakeAudioWorkletNode);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('system-audio start acquires the module BEFORE device enumeration; stop releases once', async () => {
    const capture = new AudioCapture(() => {});
    await capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });

    expect(acquireMock).toHaveBeenCalledTimes(1);
    expect(acquireMock).toHaveBeenCalledWith('sink-a');
    expect(acquireMock.mock.invocationCallOrder[0]).toBeLessThan(
      enumerateDevicesMock.mock.invocationCallOrder[0],
    );
    expect(getUserMediaMock).toHaveBeenCalledWith(
      expect.objectContaining({
        audio: expect.objectContaining({ deviceId: { exact: 'loopback-dev-1' } }),
      }),
    );
    expect(releaseMock).not.toHaveBeenCalled();

    capture.stop();
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('double stop() releases only once', async () => {
    const capture = new AudioCapture(() => {});
    await capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    capture.stop();
    capture.stop();
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('getUserMedia rejection after acquire → release called, start() rejects', async () => {
    getUserMediaMock.mockRejectedValueOnce(new Error('NotAllowedError'));
    const capture = new AudioCapture(() => {});
    await expect(capture.start({ systemAudio: true, monitorSinkName: 'sink-a' })).rejects.toThrow(
      'NotAllowedError',
    );
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('waitForDevice timeout → release called, start() rejects', async () => {
    vi.useFakeTimers();
    enumerateDevicesMock.mockResolvedValue([]); // device never appears
    const capture = new AudioCapture(() => {});
    const starting = capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    const assertion = expect(starting).rejects.toThrow(/did not appear in time/);
    await vi.advanceTimersByTimeAsync(8000);
    await assertion;
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('addModule rejection → release called AND stream tracks stopped', async () => {
    const { stream, audioTrack } = makeStream();
    getUserMediaMock.mockResolvedValueOnce(stream);
    addModuleMock.mockRejectedValueOnce(new Error('worklet load failed'));
    const capture = new AudioCapture(() => {});
    await expect(capture.start({ systemAudio: true, monitorSinkName: 'sink-a' })).rejects.toThrow(
      'worklet load failed',
    );
    expect(releaseMock).toHaveBeenCalledTimes(1);
    expect(audioTrack.stop).toHaveBeenCalled();
  });

  it('microphone capture never touches loopbackOwner', async () => {
    const capture = new AudioCapture(() => {});
    await capture.start({ deviceId: 'mic-1' });
    capture.stop();
    expect(acquireMock).not.toHaveBeenCalled();
    expect(releaseMock).not.toHaveBeenCalled();
  });

  it('getDisplayMedia system audio (win/mac path) never touches loopbackOwner', async () => {
    const capture = new AudioCapture(() => {});
    await capture.start({ systemAudio: true });
    capture.stop();
    expect(acquireMock).not.toHaveBeenCalled();
    expect(releaseMock).not.toHaveBeenCalled();
  });

  it('the defensive internal stop() at start() never releases a hold it does not have', async () => {
    const capture = new AudioCapture(() => {});
    // Fresh instance: the stop() inside start() must not call release.
    await capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    expect(releaseMock).not.toHaveBeenCalled();
    // Restart on the same instance: the internal stop() releases the previous
    // hold exactly once, then re-acquires.
    await capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    expect(releaseMock).toHaveBeenCalledTimes(1);
    expect(acquireMock).toHaveBeenCalledTimes(2);
  });

  // ── stop()-during-start() abort races (GH-230 review finding) ─────────
  //
  // An external stop() landing while start() is awaiting used to be a silent
  // no-op: the orphaned start() ran to completion, held the loopback module
  // forever (mic indicator lit), and pumped audio into a dead session.

  it('external stop() during the acquire await → hold released exactly once, start rejects with AbortError', async () => {
    let resolveAcquire!: (v: { label: string; volumePct: number | null }) => void;
    acquireMock.mockImplementationOnce(
      () =>
        new Promise<{ label: string; volumePct: number | null }>((res) => {
          resolveAcquire = res;
        }),
    );
    const capture = new AudioCapture(() => {});
    const starting = capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    const assertion = expect(starting).rejects.toMatchObject({ name: 'AbortError' });

    capture.stop(); // lands mid-acquire: nothing to release yet
    expect(releaseMock).not.toHaveBeenCalled();

    resolveAcquire({ label: 'TranscriptionSuite_Loopback', volumePct: 100 });
    await assertion;
    // The just-granted hold was released by the abort path — exactly once.
    expect(releaseMock).toHaveBeenCalledTimes(1);
    // The orphaned start never opened the device.
    expect(getUserMediaMock).not.toHaveBeenCalled();
  });

  it('external stop() during getUserMedia → stream tracks stopped, hold released exactly once', async () => {
    const { stream, audioTrack } = makeStream();
    let resolveGum!: (v: MediaStream) => void;
    getUserMediaMock.mockImplementationOnce(
      () =>
        new Promise<MediaStream>((res) => {
          resolveGum = res;
        }),
    );
    const capture = new AudioCapture(() => {});
    const starting = capture.start({ systemAudio: true, monitorSinkName: 'sink-a' });
    const assertion = expect(starting).rejects.toMatchObject({ name: 'AbortError' });
    // Let the acquire + waitForDevice settle so start() is inside getUserMedia.
    await vi.waitFor(() => expect(getUserMediaMock).toHaveBeenCalled());

    capture.stop(); // releases the already-taken hold
    expect(releaseMock).toHaveBeenCalledTimes(1);

    resolveGum(stream);
    await assertion;
    // The catch-path stop() cleaned the late-arriving stream and did NOT
    // double-release the hold.
    expect(audioTrack.stop).toHaveBeenCalled();
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  // ── mixMicWithSystem: a second MediaStream mixed alongside system audio ─
  //
  // Introduces a second getUserMedia acquisition and MediaStream, which is
  // exactly the class of resource this suite exists to protect — covered
  // here for the same teardown/leak guarantees as the primary stream above.

  it('mixMicWithSystem: stop() stops BOTH streams tracks', async () => {
    const { stream: primaryStream, audioTrack: primaryTrack } = makeStream();
    const { stream: micStream, audioTrack: micTrack } = makeStream();
    getUserMediaMock.mockResolvedValueOnce(primaryStream).mockResolvedValueOnce(micStream);

    const capture = new AudioCapture(() => {});
    await capture.start({
      systemAudio: true,
      monitorSinkName: 'sink-a',
      mixMicWithSystem: true,
    });

    capture.stop();

    expect(primaryTrack.stop).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it('mixMicWithSystem: acquires the mic BEFORE the AudioContext/worklet exist', async () => {
    const { stream: primaryStream } = makeStream();
    const { stream: micStream } = makeStream();
    getUserMediaMock.mockResolvedValueOnce(primaryStream).mockResolvedValueOnce(micStream);

    const capture = new AudioCapture(() => {});
    await capture.start({
      systemAudio: true,
      monitorSinkName: 'sink-a',
      mixMicWithSystem: true,
    });

    // Both getUserMedia calls (primary + mic) must land before the worklet
    // module loads — a mic failure must fail start() cleanly instead of
    // tearing down an already-wired, already-streaming session.
    expect(getUserMediaMock.mock.invocationCallOrder[1]).toBeLessThan(
      addModuleMock.mock.invocationCallOrder[0],
    );
  });

  it('mixMicWithSystem: external stop() during the secondary getUserMedia → secondary tracks stopped, loopback released exactly once', async () => {
    const { stream: primaryStream } = makeStream();
    const { stream: micStream, audioTrack: micTrack } = makeStream();
    let resolveMicGum!: (v: MediaStream) => void;
    getUserMediaMock.mockResolvedValueOnce(primaryStream).mockImplementationOnce(
      () =>
        new Promise<MediaStream>((res) => {
          resolveMicGum = res;
        }),
    );

    const capture = new AudioCapture(() => {});
    const starting = capture.start({
      systemAudio: true,
      monitorSinkName: 'sink-a',
      mixMicWithSystem: true,
    });
    const assertion = expect(starting).rejects.toMatchObject({ name: 'AbortError' });
    // Let the primary acquire settle so start() is inside the SECOND
    // (mic) getUserMedia call.
    await vi.waitFor(() => expect(getUserMediaMock).toHaveBeenCalledTimes(2));

    capture.stop();
    expect(releaseMock).toHaveBeenCalledTimes(1);

    resolveMicGum(micStream);
    await assertion;

    expect(micTrack.stop).toHaveBeenCalled();
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('mixMicWithSystem: secondary getUserMedia rejection → primary stream tracks stopped AND loopback released', async () => {
    const { stream: primaryStream, audioTrack: primaryTrack } = makeStream();
    getUserMediaMock
      .mockResolvedValueOnce(primaryStream)
      .mockRejectedValueOnce(new Error('NotFoundError'));

    const capture = new AudioCapture(() => {});
    await expect(
      capture.start({ systemAudio: true, monitorSinkName: 'sink-a', mixMicWithSystem: true }),
    ).rejects.toThrow('NotFoundError');

    expect(primaryTrack.stop).toHaveBeenCalled();
    expect(releaseMock).toHaveBeenCalledTimes(1);
  });

  it('mixMicWithSystem: the Capture Gain slider does not touch the mic gain stage', async () => {
    const { stream: primaryStream } = makeStream();
    const { stream: micStream } = makeStream();
    getUserMediaMock.mockResolvedValueOnce(primaryStream).mockResolvedValueOnce(micStream);

    const capture = new AudioCapture(() => {});
    await capture.start({
      systemAudio: true,
      monitorSinkName: 'sink-a',
      mixMicWithSystem: true,
    });

    capture.setGain(3);

    const gainNodes = lastCtx!.createGain.mock.results.map((r) => r.value);
    expect(gainNodes).toHaveLength(2);
    const [systemGain, micGain] = gainNodes;
    expect(systemGain.gain.value).toBe(3);
    expect(micGain.gain.value).toBe(1);

    capture.mute();
    expect(systemGain.gain.value).toBe(0);
    expect(micGain.gain.value).toBe(0);

    capture.unmute();
    expect(systemGain.gain.value).toBe(3);
    expect(micGain.gain.value).toBe(1);
  });
});
