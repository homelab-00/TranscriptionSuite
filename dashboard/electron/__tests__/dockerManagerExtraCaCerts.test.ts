// @vitest-environment node

/**
 * GH-200 — the Server-tab CA folder picker must reach compose interpolation.
 *
 * Two units under test, both consumed by startContainer (which itself is not
 * unit-testable without a Docker runtime):
 * - `readExtraCaCertsDirFromStore()` reads `server.extraCaCertsDir` from the
 *   electron-store JSON. Blank/absent MUST yield null, not '': an empty
 *   process-env value would override a hand-edited .env entry in compose
 *   interpolation and silently re-break the pre-UI escape hatch that
 *   dockerManagerComposeEnvPreservation.test.ts pins.
 * - `applyExtraCaCertsEnv(composeEnv, envUpdates)` applies the value to
 *   composeEnv ONLY. It must never let the key reach envUpdates (the record
 *   upsertComposeEnvValues persists to the compose .env), and must skip a
 *   folder that no longer exists on disk (compose would auto-create an empty
 *   dir and mount it, silently reproducing the no-cert failure).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-ca-store-test-'));

// Mirror the packaged-install fixture of dockerManagerComposeEnvPreservation.test.ts
// so importing dockerManager.js behaves identically here.
const resourcesRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-ca-res-test-'));
fs.mkdirSync(path.join(resourcesRoot, 'docker'), { recursive: true });
fs.writeFileSync(path.join(resourcesRoot, 'docker', 'docker-compose.yml'), 'services: {}\n');
(process as NodeJS.Process & { resourcesPath: string }).resourcesPath = resourcesRoot;

vi.mock('electron', () => ({
  app: {
    isPackaged: true,
    getPath: (_name: string) => userDataRoot,
    setPath: vi.fn(),
  },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

const storePath = path.join(userDataRoot, 'dashboard-config.json');

function writeStore(data: Record<string, unknown>): void {
  fs.writeFileSync(storePath, JSON.stringify(data), 'utf8');
}

describe('readExtraCaCertsDirFromStore — GH-200 CA folder picker', () => {
  beforeEach(() => {
    fs.rmSync(storePath, { force: true });
  });

  it('returns the configured folder (Windows path intact)', async () => {
    const { readExtraCaCertsDirFromStore } = await import('../dockerManager.js');
    writeStore({
      'server.extraCaCertsDir': 'C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca',
    });
    expect(readExtraCaCertsDirFromStore()).toBe(
      'C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca',
    );
  });

  it('trims surrounding whitespace', async () => {
    const { readExtraCaCertsDirFromStore } = await import('../dockerManager.js');
    writeStore({ 'server.extraCaCertsDir': '  /home/me/.config/TranscriptionSuite/ca  ' });
    expect(readExtraCaCertsDirFromStore()).toBe('/home/me/.config/TranscriptionSuite/ca');
  });

  it('returns null when the key is absent, blank, or not a string', async () => {
    const { readExtraCaCertsDirFromStore } = await import('../dockerManager.js');

    writeStore({ 'server.port': 9786 });
    expect(readExtraCaCertsDirFromStore()).toBeNull();

    // Blank is what the UI Clear button writes — it must read back as unset.
    writeStore({ 'server.extraCaCertsDir': '' });
    expect(readExtraCaCertsDirFromStore()).toBeNull();

    writeStore({ 'server.extraCaCertsDir': '   ' });
    expect(readExtraCaCertsDirFromStore()).toBeNull();

    writeStore({ 'server.extraCaCertsDir': 42 });
    expect(readExtraCaCertsDirFromStore()).toBeNull();
  });

  it('returns null when the store file is missing or corrupt', async () => {
    const { readExtraCaCertsDirFromStore } = await import('../dockerManager.js');

    expect(readExtraCaCertsDirFromStore()).toBeNull();

    fs.writeFileSync(storePath, 'not json at all', 'utf8');
    expect(readExtraCaCertsDirFromStore()).toBeNull();
  });
});

describe('applyExtraCaCertsEnv — composeEnv-only contract', () => {
  beforeEach(() => {
    fs.rmSync(storePath, { force: true });
  });

  it('sets composeEnv but never envUpdates when the folder exists', async () => {
    const { applyExtraCaCertsEnv } = await import('../dockerManager.js');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-ca-real-dir-'));
    writeStore({ 'server.extraCaCertsDir': dir });

    const composeEnv: Record<string, string> = {};
    const envUpdates: Record<string, string> = { TAG: 'v1.3.8' };
    applyExtraCaCertsEnv(composeEnv, envUpdates);

    expect(composeEnv['EXTRA_CA_CERTS_DIR']).toBe(dir);
    // The .env-persisted record must stay untouched: a persisted copy would
    // keep applying after the picker is cleared and clobber hand-edited values.
    expect(envUpdates).toEqual({ TAG: 'v1.3.8' });
  });

  it('leaves composeEnv without the key entirely when unset', async () => {
    const { applyExtraCaCertsEnv } = await import('../dockerManager.js');
    writeStore({ 'server.port': 9786 });

    const composeEnv: Record<string, string> = {};
    applyExtraCaCertsEnv(composeEnv, {});

    // Absence, not '', is required: an empty process-env value overrides a
    // hand-edited .env entry in compose interpolation.
    expect('EXTRA_CA_CERTS_DIR' in composeEnv).toBe(false);
  });

  it('skips a configured folder that no longer exists on disk', async () => {
    const { applyExtraCaCertsEnv } = await import('../dockerManager.js');
    writeStore({
      'server.extraCaCertsDir': path.join(os.tmpdir(), 'ts-ca-vanished-does-not-exist'),
    });

    const composeEnv: Record<string, string> = {};
    applyExtraCaCertsEnv(composeEnv, {});

    expect('EXTRA_CA_CERTS_DIR' in composeEnv).toBe(false);
  });

  it('drops a stray EXTRA_CA_CERTS_DIR from envUpdates (invariant enforcement)', async () => {
    const { applyExtraCaCertsEnv } = await import('../dockerManager.js');

    const composeEnv: Record<string, string> = {};
    const envUpdates: Record<string, string> = { EXTRA_CA_CERTS_DIR: '/somewhere', TAG: 'v1' };
    applyExtraCaCertsEnv(composeEnv, envUpdates);

    expect('EXTRA_CA_CERTS_DIR' in envUpdates).toBe(false);
    expect(envUpdates['TAG']).toBe('v1');
  });
});
