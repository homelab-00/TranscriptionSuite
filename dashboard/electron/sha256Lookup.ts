import path from 'node:path';

interface Logger {
  warn: (...args: unknown[]) => void;
}

/**
 * Resolve the expected SHA-256 for a downloaded installer file against a
 * manifest's sha256 map. The manifest publishes canonical asset names
 * (e.g. `TranscriptionSuite.AppImage`), but electron-builder's default
 * artifactName embeds the version (`TranscriptionSuite-1.3.3.AppImage`).
 *
 * Resolution order:
 *   1. Exact basename match — the direct happy path.
 *   2. Single same-extension fallback — bridges the canonical-vs-versioned
 *      mismatch when the manifest lists exactly one entry of that extension.
 *   3. Ambiguous (>1 same-extension matches) — fail-closed. Returns null
 *      and warns so the verifier falls through to its "no expected hash
 *      → skip with warn" path, rather than silently cross-validating an
 *      arm64 binary against an x64 hash (the multi-arch spoofing seam
 *      this function exists to close).
 *
 * Returns null for 0 matches and for ambiguous matches; callers must
 * treat both the same (verifier's fail-open posture for missing hashes).
 */
export function resolveExpectedSha256(
  sha256Map: Record<string, string>,
  downloadedFile: string,
  logger?: Logger,
): string | null {
  const basename = path.basename(downloadedFile);
  if (Object.prototype.hasOwnProperty.call(sha256Map, basename)) {
    return sha256Map[basename];
  }
  const ext = path.extname(basename);
  if (!ext) return null;
  const matches: string[] = [];
  for (const key of Object.keys(sha256Map)) {
    if (key.endsWith(ext)) {
      matches.push(key);
    }
  }
  if (matches.length === 0) return null;
  if (matches.length === 1) return sha256Map[matches[0]];
  logger?.warn(
    `sha256Lookup: ambiguous fallback — ${matches.length} manifest entries share extension ${ext}; refusing to guess`,
    { downloaded: basename, candidates: matches },
  );
  return null;
}
