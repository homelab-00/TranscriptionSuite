// @vitest-environment node

/**
 * installerCache — single-slot Linux AppImage cache manager tests per M6
 * I/O matrix.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, readdirSync } from 'fs';
import { promises as fsp } from 'fs';
import { tmpdir } from 'os';
import path from 'path';

import {
  cachePreviousInstaller,
  getCachedInstaller,
  MIN_CACHED_INSTALLER_BYTES,
  parseVersionFromFileName,
  restoreCachedInstaller,
} from '../installerCache.js';

// Real cached AppImages are ~60-200 MB; the size filter rejects anything below
// 1 MB to keep truncated-write artifacts out of the rollback path. Tests that
// expect the happy-path return must therefore write at least 1 MB of bytes.
const HEALTHY_BYTES = Buffer.alloc(MIN_CACHED_INSTALLER_BYTES, 'a');

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
    writeFileSync(src, HEALTHY_BYTES);
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    expect(result.cachedPath).toBeDefined();
    expect(readFileSync(result.cachedPath as string)).toEqual(HEALTHY_BYTES);
    expect(readdirSync(path.join(userData, 'previous-installer'))).toHaveLength(1);
  });

  it('unlinks any existing cache entries before writing the new one', async () => {
    const userData = path.join(tmp, 'userData');
    const dir = path.join(userData, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.0.AppImage'), 'old');
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.1.AppImage'), 'older');

    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

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
    writeFileSync(src, HEALTHY_BYTES);
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

  it('accepts a cache entry of exactly MIN_CACHED_INSTALLER_BYTES (inclusive lower bound)', async () => {
    // Boundary lock: the read-side filter uses `<` which makes
    // MIN_CACHED_INSTALLER_BYTES the inclusive lower bound. A future refactor
    // flipping `<` to `<=` would silently reject entries at exactly the
    // threshold; this test would fail and surface the regression.
    const dir = path.join(tmp, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    const file = path.join(dir, 'TranscriptionSuite-1.3.2.AppImage');
    writeFileSync(file, Buffer.alloc(MIN_CACHED_INSTALLER_BYTES, 'b'));

    const result = await getCachedInstaller(tmp);

    expect(result).toEqual({ path: file, version: '1.3.2' });
  });
});

// ── Deferred bug: userData-descendant allow-list defense (broader than the
// exact-parent equality check from the prior spec) ────────────────────────

describe('cachePreviousInstaller userData allow-list defense', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-allowlist-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('rejects when previous-installer symlinks to a sibling-of-source dir outside userData', async () => {
    // Setup: source in `tmp/apps/current/`, sibling target dir at
    // `tmp/apps/backups/`, cache symlinked to backups. The narrow exact-parent
    // check would have passed (backups != current), but the broader allow-list
    // rejects because backups does not descend from userData.
    const userData = path.join(tmp, 'userData');
    await fsp.mkdir(userData, { recursive: true });
    const sourceDir = path.join(tmp, 'apps', 'current');
    await fsp.mkdir(sourceDir, { recursive: true });
    const siblingDir = path.join(tmp, 'apps', 'backups');
    await fsp.mkdir(siblingDir, { recursive: true });
    // Pre-seed the sibling with files that match the cache name pattern; the
    // filename-filter unlink loop would otherwise be the last line of defense.
    // The allow-list catches it earlier — neither the bystander nor the
    // pattern-matching files should be touched.
    writeFileSync(path.join(siblingDir, 'bystander.txt'), 'should survive');
    writeFileSync(path.join(siblingDir, 'TranscriptionSuite-9.9.9.AppImage'), HEALTHY_BYTES);

    const src = path.join(sourceDir, 'TranscriptionSuite.AppImage');
    writeFileSync(src, HEALTHY_BYTES);
    await fsp.symlink(siblingDir, path.join(userData, 'previous-installer'));

    const before = readdirSync(siblingDir).sort();

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('cache-collision');
    expect(readdirSync(siblingDir).sort()).toEqual(before);
  });

  it('proceeds when previous-installer symlinks to a userData descendant', async () => {
    const userData = path.join(tmp, 'userData');
    const legitTarget = path.join(userData, 'legit-subfolder');
    await fsp.mkdir(legitTarget, { recursive: true });
    await fsp.symlink(legitTarget, path.join(userData, 'previous-installer'));

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
    // The cache file lands inside the symlink target.
    expect(readdirSync(legitTarget)).toContain('TranscriptionSuite-1.3.2.AppImage');
  });

  it('accepts the equality case but only unlinks our own filename pattern', async () => {
    // Pathological symlink-loop: previous-installer/ → userData/. Realpath
    // equality is allowed (frozen-spec invariant), so the unlink loop runs
    // against userData itself. The filename-pattern filter is the safety net:
    // only `TranscriptionSuite-*.AppImage` files get unlinked; unrelated
    // userData contents survive.
    const userData = path.join(tmp, 'userData');
    await fsp.mkdir(userData, { recursive: true });
    writeFileSync(path.join(userData, 'electron-store.json'), '{"k":"v"}');
    writeFileSync(path.join(userData, 'TranscriptionSuite-9.9.9.AppImage'), HEALTHY_BYTES);
    // Symlink-loop: previous-installer points to userData itself.
    await fsp.symlink(userData, path.join(userData, 'previous-installer'));

    const src = path.join(tmp, 'TranscriptionSuite.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    // Unrelated userData file survives — filename filter prevented wipe.
    expect(readFileSync(path.join(userData, 'electron-store.json'), 'utf8')).toBe('{"k":"v"}');
    // Pre-existing cache-pattern file was unlinked (replaced by the new one).
    const remaining = readdirSync(userData).filter((n) => n.endsWith('.AppImage'));
    expect(remaining).toEqual(['TranscriptionSuite-1.3.2.AppImage']);
  });
});

// ── Deferred bug: pre-copy source-size guard ──────────────────────────────

describe('cachePreviousInstaller pre-copy source-size guard', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-srcsize-'));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('rejects a 0-byte source AppImage with source-too-small (no cache write)', async () => {
    const src = path.join(tmp, 'truncated.AppImage');
    writeFileSync(src, Buffer.alloc(0));
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('source-too-small');
    // No cache dir created — the guard fires before mkdir.
    expect(() => readdirSync(path.join(userData, 'previous-installer'))).toThrow();
  });

  it('rejects a source AppImage of MIN_CACHED_INSTALLER_BYTES - 1 (just under threshold)', async () => {
    const src = path.join(tmp, 'almost.AppImage');
    writeFileSync(src, Buffer.alloc(MIN_CACHED_INSTALLER_BYTES - 1, 'a'));
    const userData = path.join(tmp, 'userData');

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('source-too-small');
  });

  it('accepts a source AppImage of exactly MIN_CACHED_INSTALLER_BYTES (inclusive lower bound)', async () => {
    const src = path.join(tmp, 'exactly-min.AppImage');
    writeFileSync(src, Buffer.alloc(MIN_CACHED_INSTALLER_BYTES, 'a'));
    const userData = path.join(tmp, 'userData');

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

// ── Spec: in-app-update-cache-write-hardening — atomic copy-then-rename ──
//
// Defends against the "delete-then-copy loses cache on copyFile failure"
// failure mode (M6 review #2). Write sequence is now:
//   copyFile(sourceReal, destPath.tmp) → rename(tmpPath, destPath) → unlink
//   priors. On any failure before the rename, prior cache survives.

describe('cachePreviousInstaller atomic-write', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-atomic-'));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    rmSync(tmp, { recursive: true, force: true });
  });

  it('preserves the prior cache entry when copyFile fails with ENOSPC mid-write', async () => {
    const userData = path.join(tmp, 'userData');
    const dir = path.join(userData, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.2.AppImage'), HEALTHY_BYTES);

    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

    vi.spyOn(fsp, 'copyFile').mockRejectedValueOnce(
      Object.assign(new Error('ENOSPC: no space left on device'), { code: 'ENOSPC' }),
    );

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.3',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('write-error');

    // The PRE-EXISTING cache entry must survive — that's the whole point.
    // No new `-1.3.3.AppImage`, and no `.tmp` residue either.
    expect(readdirSync(dir)).toEqual(['TranscriptionSuite-1.3.2.AppImage']);
  });

  it('sweeps orphan .tmp files from prior crashed / timed-out writes', async () => {
    const userData = path.join(tmp, 'userData');
    const dir = path.join(userData, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    // Two orphan tmps that look like crashed prior writes. Without the
    // .tmp-sweep patch these would accumulate indefinitely — the old
    // parseVersionFromFileName filter skipped them.
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.0.AppImage.tmp'), HEALTHY_BYTES);
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.1.AppImage.tmp'), HEALTHY_BYTES);
    // A non-sweepable orphan (wrong prefix) — must survive (not ours).
    writeFileSync(path.join(dir, 'unrelated-file.tmp'), 'keep');

    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.3',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    const remaining = readdirSync(dir).sort();
    expect(remaining).toEqual(['TranscriptionSuite-1.3.3.AppImage', 'unrelated-file.tmp']);
  });

  it('preserves the prior cache entry when rename fails (EXDEV)', async () => {
    const userData = path.join(tmp, 'userData');
    const dir = path.join(userData, 'previous-installer');
    await fsp.mkdir(dir, { recursive: true });
    writeFileSync(path.join(dir, 'TranscriptionSuite-1.3.2.AppImage'), HEALTHY_BYTES);

    const src = path.join(tmp, 'running.AppImage');
    writeFileSync(src, HEALTHY_BYTES);

    // rename fails: cross-filesystem rename (hypothetical) or a permissions
    // glitch on the tmp-to-dest rename step. copyFile ran, wrote the tmp;
    // our catch arm must unlink the orphan tmp, leaving only the prior.
    vi.spyOn(fsp, 'rename').mockRejectedValueOnce(
      Object.assign(new Error('EXDEV: cross-device link not permitted'), { code: 'EXDEV' }),
    );

    const result = await cachePreviousInstaller({
      sourcePath: src,
      version: '1.3.3',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('write-error');
    expect(readdirSync(dir)).toEqual(['TranscriptionSuite-1.3.2.AppImage']);
  });
});

// ── Spec: in-app-update-cache-write-hardening — source realpath parity ──
//
// Witnesses that both the pre-copy stat and the copyFile go through the
// same resolved path. Defends against a symlink-retarget race on
// process.env.APPIMAGE between stat and copy.

describe('cachePreviousInstaller source realpath parity', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(path.join(tmpdir(), 'installer-cache-realpath-'));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    rmSync(tmp, { recursive: true, force: true });
  });

  it('copyFile is invoked with the realpath of a symlinked sourcePath', async () => {
    const realTarget = path.join(tmp, 'real-v1.3.2.AppImage');
    writeFileSync(realTarget, HEALTHY_BYTES);
    const link = path.join(tmp, 'link.AppImage');
    await fsp.symlink(realTarget, link);
    const expectedReal = await fsp.realpath(link);
    const userData = path.join(tmp, 'userData');

    const copyFileSpy = vi.spyOn(fsp, 'copyFile');

    const result = await cachePreviousInstaller({
      sourcePath: link,
      version: '1.3.2',
      userDataDir: userData,
      platform: 'linux',
    });

    expect(result.ok).toBe(true);
    // The first argument of the FIRST copyFile call must be the
    // resolved realpath, not the symlink we were handed.
    expect(copyFileSpy).toHaveBeenCalled();
    const firstCallArgs = copyFileSpy.mock.calls[0];
    expect(firstCallArgs[0]).toBe(expectedReal);
    expect(firstCallArgs[0]).not.toBe(link);
  });
});
