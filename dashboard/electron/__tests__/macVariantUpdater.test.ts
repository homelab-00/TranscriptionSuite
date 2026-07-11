import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as os from 'node:os';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { downloadMacVariantDmg } from '../macVariantUpdater.js';
import type { InstallerStatus } from '../updateManager.js';

const DMG_BYTES = Buffer.from('fake-dmg-contents');
const DMG_SHA512 = createHash('sha512').update(DMG_BYTES).digest('base64');

let tmpDir: string;
beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'macvariant-'));
});
afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function bodyFrom(buf: Buffer): AsyncIterable<Uint8Array> {
  return (async function* () {
    yield new Uint8Array(buf);
  })();
}

function fakeFetch(map: Record<string, { ok: boolean; body?: Buffer; text?: string }>) {
  return vi.fn(async (url: string) => {
    const hit = map[url];
    if (!hit)
      return { ok: false, status: 404, headers: new Map(), body: null } as unknown as Response;
    return {
      ok: hit.ok,
      status: hit.ok ? 200 : 500,
      headers: {
        get: (k: string) => (k === 'content-length' ? String(hit.body?.length ?? 0) : null),
      },
      body: hit.body ? bodyFrom(hit.body) : null,
      text: async () => hit.text ?? '',
    } as unknown as Response;
  });
}

describe('downloadMacVariantDmg', () => {
  it('downloads, verifies a standard DMG against latest-mac.yml, and reveals it', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const ymlUrl =
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/latest-mac.yml';
    const yml = `version: 1.4.0\nfiles:\n  - url: ${asset}\n    sha512: ${DMG_SHA512}\n    size: ${DMG_BYTES.length}\npath: ${asset}\nsha512: ${DMG_SHA512}\n`;
    const statuses: InstallerStatus[] = [];
    const revealed: string[] = [];

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: (s) => statuses.push(s),
      revealFile: async (p) => {
        revealed.push(p);
      },
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({
        [dmgUrl]: { ok: true, body: DMG_BYTES },
        [ymlUrl]: { ok: true, text: yml },
      }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(true);
    expect(revealed).toHaveLength(1);
    expect(path.basename(revealed[0])).toBe(asset);
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(true);
    expect(statuses.some((s) => s.state === 'downloading')).toBe(true);
  });

  it('deletes the file and errors on sha512 mismatch (standard variant)', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const ymlUrl =
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/latest-mac.yml';
    const yml = `version: 1.4.0\nfiles:\n  - url: ${asset}\n    sha512: WRONGsha==\n    size: ${DMG_BYTES.length}\n`;

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({
        [dmgUrl]: { ok: true, body: DMG_BYTES },
        [ymlUrl]: { ok: true, text: yml },
      }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('checksum-mismatch');
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(false);
  });

  it('skips verification for the metal variant (no feed) and still reveals', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac-metal.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const revealed: string[] = [];

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-metal',
      onStatus: () => {},
      revealFile: async (p) => {
        revealed.push(p);
      },
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({ [dmgUrl]: { ok: true, body: DMG_BYTES } }) as unknown as typeof fetch,
    });

    expect(result.ok).toBe(true);
    expect(revealed).toHaveLength(1);
  });

  it('returns a manual-download fallback when the download request fails', async () => {
    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({}) as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe('manual-download-required');
      expect(result.downloadUrl).toContain('/releases/');
    }
  });

  it('rejects a malformed target version before fetching (path-safety guard)', async () => {
    const fetchSpy = vi.fn();
    const result = await downloadMacVariantDmg('1.4.0/../evil', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: fetchSpy as unknown as typeof fetch,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('manual-download-required');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('deletes the partial file and falls back when the stream fails mid-download', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac.dmg';
    const throwingFetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => '999' },
      body: (async function* () {
        yield new Uint8Array(Buffer.from('partial'));
        throw new Error('connection reset');
      })(),
      text: async () => '',
    })) as unknown as typeof fetch;

    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-standard-arm64',
      onStatus: () => {},
      revealFile: async () => {},
      getDownloadsDir: () => tmpDir,
      fetchImpl: throwingFetch,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('manual-download-required');
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(false);
  });

  it('keeps the verified download and returns ok when reveal fails (no data loss)', async () => {
    const asset = 'TranscriptionSuite-1.4.0-arm64-mac-metal.dmg';
    const dmgUrl = `https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.4.0/${asset}`;
    const result = await downloadMacVariantDmg('1.4.0', {
      variant: 'mac-metal',
      onStatus: () => {},
      revealFile: async () => {
        throw new Error('Finder unavailable');
      },
      getDownloadsDir: () => tmpDir,
      fetchImpl: fakeFetch({ [dmgUrl]: { ok: true, body: DMG_BYTES } }) as unknown as typeof fetch,
    });
    expect(result.ok).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, asset))).toBe(true);
  });
});
