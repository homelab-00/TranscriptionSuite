/**
 * releaseUrl — pure helpers for constructing and validating GitHub
 * release URLs used by the in-app update flow.
 *
 * Extracted from main.ts so the security-relevant guards in
 * `isTrustedReleaseUrl` (origin allow-list, userinfo bypass defense,
 * percent-encoding bypass defense, repo-path regex) can be exercised
 * by direct unit tests rather than only implicitly via the
 * `updates:openReleasePage` IPC handler. Pure functions, no side
 * effects, no Electron imports.
 */

/**
 * Construct the GitHub release URL the manual-download banner exposes via
 * `[Download from GitHub]`. When `version` is known, link directly to the
 * tagged release; otherwise fall back to `/releases/latest`.
 *
 * Strips ONE leading `v` from `version` so `app.latest` may be stored
 * either as `1.3.3` (canonical) or `v1.3.3` (carrying the tag prefix)
 * and both yield the same `tag/v1.3.3` output. Multi-`v` prefixes
 * (e.g. `vv1.3.3`) are NOT collapsed — that input round-trips to
 * `tag/vv1.3.3`, which `isTrustedReleaseUrl` happens to accept (its
 * regex inner is `[A-Za-z0-9._-]+`) but lands the user on a GitHub
 * 404 page. A future hardening pass can tighten the regex to `/^v+/i`
 * (see deferred-work.md). The release-URL contract has no security
 * exposure either way — the origin is always github.com.
 */
export function buildReleaseUrl(version: string | null): string {
  const base = 'https://github.com/homelab-00/TranscriptionSuite/releases';
  if (version && version.length > 0) {
    const stripped = version.replace(/^v/i, '');
    return `${base}/tag/v${stripped}`;
  }
  return `${base}/latest`;
}

/**
 * Strict allow-list for `updates:openReleasePage`. The renderer-supplied
 * URL is treated as untrusted: must be `https://github.com` (origin),
 * MUST NOT carry userinfo (defeats `https://x:y@github.com/...` bypass —
 * `origin` ignores userinfo), MUST NOT contain percent-encoded segments
 * in the path (defeats `%2e%2e` traversal that survives WHATWG
 * normalization), and the path must match exactly one of the known
 * release shapes: `/releases/latest`, `/releases`, or `/releases/tag/v…`.
 */
export const RELEASE_PATH_RE =
  /^\/homelab-00\/TranscriptionSuite\/releases(\/(latest|tag\/v[A-Za-z0-9._-]+))?\/?$/;

export function isTrustedReleaseUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    if (parsed.origin !== 'https://github.com') return false;
    if (parsed.username !== '' || parsed.password !== '') return false;
    if (parsed.pathname.includes('%')) return false;
    return RELEASE_PATH_RE.test(parsed.pathname);
  } catch {
    return false;
  }
}
