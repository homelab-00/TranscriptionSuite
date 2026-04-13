// @vitest-environment node

/**
 * installerCache — single-slot Linux AppImage cache manager tests per M6
 * I/O matrix.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, readdirSync } from 'fs';
import { promises as fsp } from 'fs';
import { tmpdir } from 'os';
import path from 'path';

import {
  cachePreviousInstaller,
  getCachedInstaller,
  restoreCachedInstaller,
} from '../installerCache.js';

describe('cachePreviousInstaller', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('copies the source AppImage into the cache dir on Linux', async () => {
    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, Buffer.from('binary-v1'));
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    expect(result.cachedPath).toBeDefined();
    expect(readFileSync(result.cachedPath as string)).toEqual(Buffer.from('binary-v1'));
    expect(readdirSync(path.join(userData, 'previous-installer'))).toHaveLength(1);
  });

  it('unlinks any existing cache entries before writing the new one', async () => {
    const userData = path.join(tmp, 'userData');
    const dir = path.join(userData, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.0.AppImage'), 'old');
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.1.AppImage'), 'older');

    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, Buffer.from('binary-v2'));

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    const remaining = readdirSync(dir);
    expect(remaining).toEqual(['TranscriptionSuite-1.3.2.AppImage']);
  });

  it('returns platform-not-supported on win32 without touching disk', async () => {
    const src = path.join(tmp, 'running.exe');
    writeFileSync(src, 'nsis');
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'win32',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('platform-not-supported');
    expect(() => readdirSync(path.join(userData, 'previous-installer'))).toThrow();
  });

  it('returns platform-not-supported on darwin', async () => {
    const src = path.join(tmp, 'running.dmg');
    writeFileSync(src, 'dmg');
    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: path.join(tmp, 'userData'),
      platform: 'darwin',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('platform-not-supported');
  });

  it('returns source-missing when the source path does not exist', async () => {
    const result = await cachePreviousInstaller({
      sourcePath: path.join(tmp, 'does-not-exist.AppImage'),
      version: '1.3.2',
      userDataDir: path.join(tmp, 'userData'),
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('source-missing');
  });

  it('sanitizes version strings for use as a filename', async () => {
    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, 'x');
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2+meta/beta',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    // '+' and '/' replaced
    expect(path.basename(result.cachedPath as string)).toBe(
      'TranscriptionSuite-1.3.2-meta-beta.AppImage',
    );
  });
});

describe('getCachedInstaller', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-get-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('returns null when the cache dir does not exist', async () => {
    const result = await getCachedInstaller(path.join(tmp, 'missing-userdata'));
    expect(result).toBeNull();
  });

  it('returns null when the cache dir is empty', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    const result = await getCachedInstaller(tmp);
    expect(result).toBeNull();
  });

  it('returns path + version for a cached AppImage', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    const file = path.join(dir, 'TranscriptionSuite-1.3.1.AppImage');
    writeFileSync(file, 'bin');

    const result = await getCachedInstaller(tmp);

    expect(result).toEqual({ path: file, version: '1.3.1' });
  });

  it('skips files that do not match the cache naming convention', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'random.txt'), 'x');
    writeFileSync(path.join(dir, 'OtherApp-1.0.0.AppImage'), 'x');
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.1.AppImage'), 'x');

    const result = await getCachedInstaller(tmp);
    expect(result?.version).toBe('1.3.1');
  });
});

describe('restoreCachedInstaller', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-restore-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('copies the cached installer to the target path on Linux', async () => {
    const cached = path.join(tmp, 'cached.AppImage');
    writeFileSync(cached, Buffer.from('cached-binary'));
    const target = path.join(tmp, 'target.AppImage');

    const result = await restoreCachedInstaller({
      cachedPath: cached,
      targetPath: target,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    expect(readFileSync(target)).toEqual(Buffer.from('cached-binary'));
  });

  it('returns cache-missing when the cached path does not exist', async () => {
    const result = await restoreCachedInstaller({
      cachedPath: path.join(tmp, 'nope.AppImage'),
      targetPath: path.join(tmp, 'target.AppImage'),
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('cache-missing');
  });

  it('returns platform-not-supported on non-Linux', async () => {
    const result = await restoreCachedInstaller({
      cachedPath: path.join(tmp, 'x'),
      targetPath: path.join(tmp, 'y'),
      platform: 'win32',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('platform-not-supported');
  });
});
