// @vitest-environment node

/**
 * serverConfigPaths — the dedicated server-config dir helper.
 *
 * We mount ONLY userData/server-config into the container (not the whole
 * Electron userData dir), so the server never sees the Chromium profile.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-servercfg-test-'));

vi.mock('electron', () => ({
  app: { getPath: (_name: string) => userDataRoot },
}));

import {
  getServerConfigDir,
  getServerConfigPath,
  ensureServerConfigSeed,
  resolveDiarizationModelForLaunch,
} from '../serverConfigPaths.js';

function cleanup(): void {
  fs.rmSync(getServerConfigDir(), { recursive: true, force: true });
  fs.rmSync(path.join(userDataRoot, 'config.yaml'), { force: true });
}

beforeEach(cleanup);
afterEach(cleanup);

describe('serverConfigPaths', () => {
  it('points at the dedicated server-config subdir', () => {
    expect(getServerConfigDir()).toBe(path.join(userDataRoot, 'server-config'));
    expect(getServerConfigPath()).toBe(path.join(userDataRoot, 'server-config', 'config.yaml'));
  });

  it('seeds a sparse comment-only stub when nothing exists', () => {
    const p = ensureServerConfigSeed();
    expect(p).toBe(getServerConfigPath());
    const text = fs.readFileSync(p, 'utf-8');
    expect(text).toContain('sparse overrides');
    expect(text).toContain('# diarization:');
  });

  it('migrates a legacy userData/config.yaml into the subdir', () => {
    const legacy = path.join(userDataRoot, 'config.yaml');
    fs.writeFileSync(legacy, 'diarization:\n  parallel: false\n', 'utf-8');
    const p = ensureServerConfigSeed();
    expect(fs.existsSync(legacy)).toBe(false); // moved, not copied
    expect(fs.readFileSync(p, 'utf-8')).toContain('parallel: false');
  });

  it('is idempotent — leaves an existing overlay untouched', () => {
    fs.mkdirSync(getServerConfigDir(), { recursive: true });
    fs.writeFileSync(getServerConfigPath(), 'stt:\n  buffer_size: 256\n', 'utf-8');
    ensureServerConfigSeed();
    expect(fs.readFileSync(getServerConfigPath(), 'utf-8')).toContain('buffer_size: 256');
  });
});

describe('resolveDiarizationModelForLaunch (GH-288)', () => {
  const DEFAULT = 'pyannote/speaker-diarization-community-1';

  function writeOverlay(text: string): void {
    fs.mkdirSync(getServerConfigDir(), { recursive: true });
    fs.writeFileSync(getServerConfigPath(), text, 'utf-8');
  }

  it('substitutes the overlay diarization.model for the PyAnnote-default request', () => {
    writeOverlay('diarization:\n    model: pyannote/speaker-diarization-3.1\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe('pyannote/speaker-diarization-3.1');
  });

  it('matches the PyAnnote default case-insensitively and ignores padding', () => {
    writeOverlay('diarization:\n    model: pyannote/speaker-diarization-3.1\n');
    expect(resolveDiarizationModelForLaunch('  Pyannote/Speaker-Diarization-Community-1 ')).toBe(
      'pyannote/speaker-diarization-3.1',
    );
  });

  it('is section-aware: never picks up model keys from other sections', () => {
    writeOverlay(
      'main_transcriber:\n    model: nvidia/parakeet-tdt-0.6b-v3\n' +
        'diarization:\n    model: pyannote/speaker-diarization-3.1\n',
    );
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe('pyannote/speaker-diarization-3.1');

    // diarization section present but without a model key — the
    // main_transcriber model must NOT leak into the diarization env.
    writeOverlay(
      'main_transcriber:\n    model: nvidia/parakeet-tdt-0.6b-v3\n' +
        'diarization:\n    parallel: false\n',
    );
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
  });

  it('unquotes quoted overlay values', () => {
    writeOverlay('diarization:\n    model: "pyannote/speaker-diarization-3.1"\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe('pyannote/speaker-diarization-3.1');
  });

  it('passes explicit Custom models through untouched even when the overlay is set', () => {
    writeOverlay('diarization:\n    model: pyannote/speaker-diarization-3.1\n');
    expect(resolveDiarizationModelForLaunch('org/some-custom-diarizer')).toBe(
      'org/some-custom-diarizer',
    );
  });

  it('leaves the empty sentinel (Sortformer/CAM++ server auto-select) untouched', () => {
    writeOverlay('diarization:\n    model: pyannote/speaker-diarization-3.1\n');
    expect(resolveDiarizationModelForLaunch('')).toBe('');
  });

  it('keeps the default when no overlay file exists', () => {
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
  });

  it('keeps the default on the seeded comment-only stub', () => {
    ensureServerConfigSeed();
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
  });

  it('treats an empty overlay model value as unset', () => {
    writeOverlay('diarization:\n    model: ""\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
  });

  it('treats YAML null forms as unset — clearing the Settings field writes a bare null', () => {
    // ServerConfigEditor's parseFieldValue() maps a cleared text input to JS
    // null, and YAML.stringify emits the bare line `model: null`.
    writeOverlay('diarization:\n    model: null\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
    writeOverlay('diarization:\n    model: ~\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
    writeOverlay('diarization:\n    model: NULL\n');
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe(DEFAULT);
  });

  it('runs the seed/legacy migration before reading, so the first launch after an upgrade sees the legacy value', () => {
    // Legacy layout: overlay still at userData/config.yaml, server-config dir
    // absent. startContainer only seeds/migrates AFTER the env assembly, so the
    // resolver must trigger the migration itself or the first launch misses it.
    fs.writeFileSync(
      path.join(userDataRoot, 'config.yaml'),
      'diarization:\n    model: pyannote/speaker-diarization-3.1\n',
      'utf-8',
    );
    expect(resolveDiarizationModelForLaunch(DEFAULT)).toBe('pyannote/speaker-diarization-3.1');
  });
});
