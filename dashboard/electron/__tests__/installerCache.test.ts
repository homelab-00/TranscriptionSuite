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
  parseVersionFromFileName,
  restoreCachedInstaller,
} from '../installerCache.js';

// Real cached AppImages are ~60-200 MB; the size filter rejects anything below
// 1 MB to keep truncated-write artifacts out of the rollback path. Tests that
// expect the happy-path return must therefore write at least 1 MB of bytes.
const HEALTHY_BYTES = Buffer.alloc(1_000_000, 'a');

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
    writeFileSync(file, HEALTHY_BYTES);

    const result = await getCachedInstaller(tmp);

    expect(result).toEqual({ path: file, version: '1.3.1' });
  });

  it('skips files that do not match the cache naming convention', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'random.txt'), HEALTHY_BYTES);
    writeFileSync(path.join(dir, 'OtherApp-1.0.0.AppImage'), HEALTHY_BYTES);
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.1.AppImage'), HEALTHY_BYTES);

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

// ── Deferred bug: charset guard on parseVersionFromFileName ─────────────

describe('parseVersionFromFileName charset guard', () => {
  it('rejects path-traversal-style inner segments', () => {
    // Linux filenames cannot contain `/`, so this exact filename can't exist
    // on disk — but the parser must reject it defensively in case a future
    // caller passes a string from another source (manifest-derived, IPC, etc.)
    // where `..` would surface in the rollback dialog or store payload.
    expect(parseVersionFromFileName('TranscriptionSuite-../../evil.AppImage')).toBeNull();
  });

  it('rejects shell-meta characters in the inner', () => {
    expect(parseVersionFromFileName('TranscriptionSuite-evil$cmd.AppImage')).toBeNull();
    expect(parseVersionFromFileName('TranscriptionSuite-evil`cmd`.AppImage')).toBeNull();
    expect(parseVersionFromFileName('TranscriptionSuite-evil;cmd.AppImage')).toBeNull();
  });

  it('rejects whitespace and control characters', () => {
    expect(parseVersionFromFileName('TranscriptionSuite-1.3 2.AppImage')).toBeNull();
    expect(parseVersionFromFileName('TranscriptionSuite-1.3\t2.AppImage')).toBeNull();
  });

  it('accepts legitimate semver-style versions including prereleases', () => {
    expect(parseVersionFromFileName('TranscriptionSuite-1.3.2.AppImage')).toBe('1.3.2');
    expect(parseVersionFromFileName('TranscriptionSuite-1.3.2-rc.1.AppImage')).toBe('1.3.2-rc.1');
    expect(parseVersionFromFileName('TranscriptionSuite-1.3.2_dev.AppImage')).toBe('1.3.2_dev');
  });

  it('rejects pure-dot inners (.., ., ...)', () => {
    // SAFE_VERSION_RE allows `.`, so `..` and `...` would pass without an
    // explicit dot-only guard. They cannot be path traversal at file-read
    // time (no slash in basename) but would surface as nonsensical
    // "version" strings in the rollback dialog and store payload.
    // Filenames built as `TranscriptionSuite-{inner}.AppImage`:
    expect(parseVersionFromFileName('TranscriptionSuite-..AppImage')).toBeNull(); // inner = '.'
    expect(parseVersionFromFileName('TranscriptionSuite-...AppImage')).toBeNull(); // inner = '..'
    expect(parseVersionFromFileName('TranscriptionSuite-....AppImage')).toBeNull(); // inner = '...'
  });
});

// ── Deferred bug: symlink-collision defense in cachePreviousInstaller ───

describe('cachePreviousInstaller symlink-collision defense', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-collide-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('aborts with cache-collision when previous-installer symlinks to source parent', async () => {
    // Pathological dotfiles-rig setup: previous-installer/ → AppImage parent dir.
    // Without the realpath check, the unlink loop would delete the running binary.
    const userData = path.join(tmp, 'userData');
    await fsp.mkdir(userData, { recursive: true });
    const sourceDir = path.join(tmp, 'apps');
    await fsp.mkdir(sourceDir, { recursive: true });
    const src = path.join(sourceDir, 'TranscriptionSuite.AppImage');
    writeFileSync(src, HEALTHY_BYTES);
    // Symlink the cache dir to the source's parent dir.
    await fsp.symlink(sourceDir, path.join(userData, 'previous-installer'));

    const sourceContentsBefore = readdirSync(sourceDir);

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('cache-collision');
    // No filesystem mutation: source dir contents unchanged.
    expect(readdirSync(sourceDir)).toEqual(sourceContentsBefore);
    // Source AppImage still intact.
    expect(readFileSync(src)).toEqual(HEALTHY_BYTES);
  });

  it('proceeds normally when previous-installer is a regular dir (not a symlink to source)', async () => {
    // Sanity check: the realpath check must not false-positive on the normal case.
    const userData = path.join(tmp, 'userData');
    const src = path.join(tmp, 'TranscriptionSuite.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    expect(result.cachedPath).toBeDefined();
  });
});

// ── Deferred bug: 0-byte / truncated cache filter in getCachedInstaller ──

describe('getCachedInstaller size filter', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-size-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('skips a 0-byte cache entry', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.2.AppImage'), Buffer.alloc(0));

    const result = await getCachedInstaller(tmp);

    expect(result).toBeNull();
  });

  it('skips a truncated cache entry below the 1 MB minimum', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    // 999_999 bytes — just under the 1 MB threshold.
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.2.AppImage'), Buffer.alloc(999_999, 'x'));

    const result = await getCachedInstaller(tmp);

    expect(result).toBeNull();
  });

  it('returns a healthy ≥1 MB cache entry', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    const file = path.join(dir, 'TranscriptionSuite-1.3.2.AppImage');
    writeFileSync(file, HEALTHY_BYTES);

    const result = await getCachedInstaller(tmp);

    expect(result).toEqual({ path: file, version: '1.3.2' });
  });

  it('skips an under-sized entry but returns a sibling healthy entry', async () => {
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.0.AppImage'), Buffer.alloc(0));
    const healthyFile = path.join(dir, 'TranscriptionSuite-1.3.2.AppImage');
    writeFileSync(healthyFile, HEALTHY_BYTES);

    const result = await getCachedInstaller(tmp);

    expect(result?.version).toBe('1.3.2');
  });
});
