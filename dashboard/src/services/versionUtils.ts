/**
 * Version tag parsing and comparison utilities for Docker image tags.
 *
 * Tag format: v{major}.{minor}.{patch}[rc{N}]
 * Examples: v1.2.3, v1.2.3rc, v2.0.0rc2
 */

export const IMAGE_REPO = 'ghcr.io/homelab-00/transcriptionsuite-server';

const VERSION_RE = /^v(\d+)\.(\d+)\.(\d+)(rc\d*)?$/;

export interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  isRC: boolean;
  raw: string;
}

/** Parse a version tag string into its components, or null if invalid. */
export function parseVersionTag(tag: string): ParsedVersion | null {
  const m = VERSION_RE.exec(tag);
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    isRC: m[4] != null,
    raw: tag,
  };
}

/**
 * Compare two version tag strings for descending sort.
 * Returns negative if a > b, positive if a < b, 0 if equal.
 * Unparsable tags sort to the end.
 */
export function compareVersionTags(a: string, b: string): number {
  const pa = parseVersionTag(a);
  const pb = parseVersionTag(b);

  if (!pa && !pb) return 0;
  if (!pa) return 1;
  if (!pb) return -1;

  const majorDiff = pb.major - pa.major;
  if (majorDiff !== 0) return majorDiff;

  const minorDiff = pb.minor - pa.minor;
  if (minorDiff !== 0) return minorDiff;

  const patchDiff = pb.patch - pa.patch;
  if (patchDiff !== 0) return patchDiff;

  // Same version: stable (not RC) sorts before RC
  if (!pa.isRC && pb.isRC) return -1;
  if (pa.isRC && !pb.isRC) return 1;

  return 0;
}

/** Sort an array of version tag strings in descending semver order (immutable). */
export function sortVersionTagsDesc(tags: readonly string[]): string[] {
  return [...tags].sort(compareVersionTags);
}

/**
 * Returns true if tag `a` has a strictly higher major.minor.patch than tag `b`,
 * ignoring the RC suffix. Used to filter RC tags: only show RCs whose base
 * version exceeds the latest stable release.
 */
export function isNewerVersion(a: string, b: string): boolean {
  const pa = parseVersionTag(a);
  const pb = parseVersionTag(b);
  if (!pa || !pb) return false;
  return (
    pa.major > pb.major ||
    (pa.major === pb.major && pa.minor > pb.minor) ||
    (pa.major === pb.major && pa.minor === pb.minor && pa.patch > pb.patch)
  );
}

/**
 * Format a date string as DD/MM/YYYY.
 * Accepts ISO strings, Docker's "YYYY-MM-DD HH:MM:SS" format, or any
 * string parseable by `new Date()`. Returns null if parsing fails.
 */
export function formatDateDMY(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  const day = String(d.getUTCDate()).padStart(2, '0');
  const month = String(d.getUTCMonth() + 1).padStart(2, '0');
  const year = d.getUTCFullYear();
  return `${day}/${month}/${year}`;
}
