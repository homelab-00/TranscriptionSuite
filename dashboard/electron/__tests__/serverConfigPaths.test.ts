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
