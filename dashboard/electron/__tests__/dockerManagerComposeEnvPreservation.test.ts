// @vitest-environment node

/**
 * GH-200 — a hand-added compose env key must survive every server start.
 *
 * On a TLS-intercepting network (corporate proxy / antivirus HTTPS scanning) the
 * only way a packaged-app user can get their root CA into the container is to add
 * `EXTRA_CA_CERTS_DIR=...` to `<userData>/docker/.env` by hand: there is no UI for
 * it yet, and the compose files themselves are overwritten from the bundle on every
 * launch.
 *
 * `upsertComposeEnvValues` rewrites that same file on every start. It only strips
 * the keys it is about to write, so unknown keys survive — and this test pins that,
 * because a refactor to "rewrite the file from the known key set" would look
 * perfectly reasonable and would silently re-break exactly the users who are hardest
 * to support.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-compose-env-test-'));

// Simulate a PACKAGED install, which is the population that hits GH-200: resolveComposeDir()
// copies every file from resources/docker over <userData>/docker on each start. Packaging
// ships only the compose YAMLs (electron-builder `extraResources`), never a .env — which is
// precisely why a user-authored .env survives. Shipping a .env would silently kill the only
// escape hatch these users have, so this fixture mirrors the real resource set.
const resourcesRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-compose-res-test-'));
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

const composeEnvPath = path.join(userDataRoot, 'TranscriptionSuite', 'docker', '.env');

function readComposeEnv(): string {
  return fs.readFileSync(composeEnvPath, 'utf8');
}

function envValue(text: string, key: string): string | undefined {
  for (const line of text.split(/\r?\n/)) {
    const match = new RegExp(`^${key}=(.*)$`).exec(line.trim());
    if (match) return match[1];
  }
  return undefined;
}

describe('upsertComposeEnvValues — GH-200 CA escape hatch', () => {
  beforeEach(() => {
    fs.mkdirSync(path.dirname(composeEnvPath), { recursive: true });
    fs.rmSync(composeEnvPath, { force: true });
  });

  it('preserves a hand-added EXTRA_CA_CERTS_DIR across a server start', async () => {
    const { upsertComposeEnvValues } = await import('../dockerManager.js');

    fs.writeFileSync(
      composeEnvPath,
      '# user-added for corporate network (GH-200)\nEXTRA_CA_CERTS_DIR=C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca\nTAG=v1.3.7\n',
      'utf8',
    );

    // What a normal server start writes.
    upsertComposeEnvValues({ TAG: 'v1.3.8', PYTORCH_VARIANT: 'cpu' });

    const text = readComposeEnv();
    expect(envValue(text, 'EXTRA_CA_CERTS_DIR')).toBe(
      'C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca',
    );
    expect(envValue(text, 'TAG')).toBe('v1.3.8');
    expect(envValue(text, 'PYTORCH_VARIANT')).toBe('cpu');
    expect(text).toContain('# user-added for corporate network (GH-200)');
  });

  it('still preserves it after repeated starts', async () => {
    const { upsertComposeEnvValues } = await import('../dockerManager.js');

    fs.writeFileSync(
      composeEnvPath,
      'EXTRA_CA_CERTS_DIR=/home/me/.config/TranscriptionSuite/ca\n',
      'utf8',
    );

    for (let i = 0; i < 5; i += 1) {
      upsertComposeEnvValues({ TAG: `v1.3.${i}` });
    }

    const text = readComposeEnv();
    expect(envValue(text, 'EXTRA_CA_CERTS_DIR')).toBe('/home/me/.config/TranscriptionSuite/ca');
    expect(envValue(text, 'TAG')).toBe('v1.3.4');
    // The key must not accumulate duplicates that compose would resolve ambiguously.
    expect(text.match(/^EXTRA_CA_CERTS_DIR=/gm)?.length).toBe(1);
  });

  it('preserves other unrelated user keys too (proxy vars)', async () => {
    const { upsertComposeEnvValues } = await import('../dockerManager.js');

    fs.writeFileSync(
      composeEnvPath,
      'HTTPS_PROXY=http://proxy.corp:8080\nNO_PROXY=localhost,127.0.0.1\n',
      'utf8',
    );

    upsertComposeEnvValues({ TAG: 'v1.3.8' });

    const text = readComposeEnv();
    expect(envValue(text, 'HTTPS_PROXY')).toBe('http://proxy.corp:8080');
    expect(envValue(text, 'NO_PROXY')).toBe('localhost,127.0.0.1');
  });
});
