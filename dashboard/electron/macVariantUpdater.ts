/**
 * macVariantUpdater — download-and-reveal update path for macOS.
 *
 * macOS builds are unsigned (electron-updater cannot silently install), and the
 * Metal DMG is published outside electron-builder (no latest-mac.yml feed). So
 * on macOS the "Update" action downloads the release DMG that matches the
 * running variant (metal <-> standard), verifies STANDARD variants against
 * latest-mac.yml (best-effort; skipped for metal), and reveals it in Finder for
 * a manual drag-install. No quitAndInstall.
 *
 * Dependency-injected (fetch/reveal/downloads-dir) for unit-testability.
 */
import * as path from 'node:path';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import type { InstallerStatus } from './updateManager.js';
import {
  type AppVariant,
  resolveMacDmgAssetName,
  buildAssetDownloadUrl,
  isTrustedAssetUrl,
  sha512FromLatestYml,
} from './appVariant.js';
import { buildReleaseUrl } from './releaseUrl.js';

export interface MacVariantDeps {
  variant: AppVariant;
  onStatus: (status: InstallerStatus) => void;
  revealFile: (filePath: string) => Promise<void>;
  getDownloadsDir: () => string;
  fetchImpl?: typeof fetch;
}

/**
 * Result of a variant-matched DMG download.
 *
 * A flat (non-discriminated) shape is used deliberately. This file is compiled
 * under BOTH the dashboard's root tsconfig (no `strictNullChecks`) AND
 * electron/tsconfig.json (`strict: true`), and the non-strict compile is the
 * binding constraint: under it, truthiness narrowing of a discriminated union
 * (`if (!result.ok) { … result.reason … }`) does NOT narrow, so the properties
 * would be inaccessible to callers of that shape. A flat interface sidesteps
 * this, mirroring the established `VerifyChecksumResult` convention in
 * checksumVerifier.ts.
 *
 * - `ok: true`  → `path` is set (the revealed DMG).
 * - `ok: false` → `reason` is set; `downloadUrl` is additionally set when
 *   `reason === 'manual-download-required'`.
 */
export interface MacVariantResult {
  ok: boolean;
  path?: string;
  reason?: 'checksum-mismatch' | 'manual-download-required';
  downloadUrl?: string;
}

/**
 * Download the matching DMG for `targetVersion`, verify (standard only),
 * reveal it, and report progress via onStatus. On any network/validation
 * failure returns a manual-download fallback carrying the release-page URL.
 */
export async function downloadMacVariantDmg(
  targetVersion: string,
  deps: MacVariantDeps,
): Promise<MacVariantResult> {
  const doFetch = deps.fetchImpl ?? fetch;

  // Defense-in-depth: this value becomes part of a filesystem path (destPath),
  // so validate its shape directly rather than relying only on URL normalization.
  const VERSION_RE = /^v?\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$/;
  if (!VERSION_RE.test(targetVersion)) {
    console.warn('[macVariantUpdater] refusing malformed target version:', targetVersion);
    deps.onStatus({ state: 'error', message: 'Invalid update version' });
    return { ok: false, reason: 'manual-download-required', downloadUrl: buildReleaseUrl(null) };
  }

  const assetName = resolveMacDmgAssetName(targetVersion, deps.variant);
  const url = buildAssetDownloadUrl(targetVersion, assetName);
  const releaseUrl = buildReleaseUrl(targetVersion);

  if (!isTrustedAssetUrl(url)) {
    console.warn('[macVariantUpdater] refusing untrusted asset url:', url);
    deps.onStatus({ state: 'error', message: 'Untrusted download URL' });
    return { ok: false, reason: 'manual-download-required', downloadUrl: releaseUrl };
  }

  const destPath = path.join(deps.getDownloadsDir(), assetName);

  try {
    deps.onStatus({
      state: 'downloading',
      version: targetVersion,
      percent: 0,
      bytesPerSecond: 0,
      transferred: 0,
      total: 0,
    });

    const res = await doFetch(url);
    if (!res.ok || !res.body) {
      throw new Error(`download failed: HTTP ${res.status}`);
    }
    const total = Number(res.headers.get('content-length') ?? 0);
    const hash = createHash('sha512');
    let transferred = 0;

    // res.body is a web ReadableStream in Node/Electron; it is async-iterable.
    const body = res.body as unknown as AsyncIterable<Uint8Array>;
    const source = (async function* () {
      for await (const chunk of body) {
        const buf = Buffer.from(chunk);
        transferred += buf.length;
        hash.update(buf);
        deps.onStatus({
          state: 'downloading',
          version: targetVersion,
          percent: total > 0 ? (transferred / total) * 100 : 0,
          bytesPerSecond: 0,
          transferred,
          total,
        });
        yield buf;
      }
    })();

    await pipeline(source, fs.createWriteStream(destPath));
    const actualSha512 = hash.digest('base64');

    // Verify STANDARD variants against latest-mac.yml (best-effort). Metal has
    // no feed entry, so verification is skipped (user decision).
    if (deps.variant !== 'mac-metal') {
      deps.onStatus({ state: 'verifying', version: targetVersion });
      const expected = await fetchExpectedSha512(doFetch, targetVersion, assetName);
      if (expected && expected !== actualSha512) {
        fs.rmSync(destPath, { force: true });
        console.error(`[macVariantUpdater] sha512 mismatch for ${assetName}`);
        deps.onStatus({ state: 'error', message: 'Checksum verification failed' });
        return { ok: false, reason: 'checksum-mismatch' };
      }
      if (!expected) {
        console.warn(
          `[macVariantUpdater] no sha512 in latest-mac.yml for ${assetName}; proceeding unverified`,
        );
      }
    }

    // Download + verification succeeded — the DMG is safe on disk. A failure of
    // the cosmetic reveal (opening Finder) must NOT discard the verified file
    // (project invariant: never drop completed work on a delivery failure).
    try {
      await deps.revealFile(destPath);
    } catch (revealErr) {
      console.warn(
        '[macVariantUpdater] reveal failed (verified download kept):',
        revealErr instanceof Error ? revealErr.message : String(revealErr),
      );
    }
    deps.onStatus({ state: 'idle' });
    return { ok: true, path: destPath };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[macVariantUpdater] download failed:', message);
    fs.rmSync(destPath, { force: true });
    deps.onStatus({ state: 'error', message });
    return { ok: false, reason: 'manual-download-required', downloadUrl: releaseUrl };
  }
}

async function fetchExpectedSha512(
  doFetch: typeof fetch,
  version: string,
  assetName: string,
): Promise<string | null> {
  try {
    const ymlUrl = buildAssetDownloadUrl(version, 'latest-mac.yml');
    if (!isTrustedAssetUrl(ymlUrl)) return null;
    const res = await doFetch(ymlUrl);
    if (!res.ok) {
      console.warn(
        `[macVariantUpdater] latest-mac.yml fetch failed (HTTP ${res.status}); proceeding unverified`,
      );
      return null;
    }
    return sha512FromLatestYml(await res.text(), assetName);
  } catch {
    console.warn('[macVariantUpdater] latest-mac.yml fetch threw; proceeding unverified');
    return null;
  }
}
