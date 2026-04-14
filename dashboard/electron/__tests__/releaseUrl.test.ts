// @vitest-environment node

/**
 * releaseUrl — direct unit tests for the GitHub release URL helpers
 * extracted from main.ts. The IPC handler `updates:openReleasePage`
 * exercises these implicitly, but security-relevant guards
 * (origin allow-list, userinfo bypass, percent-encoding bypass,
 * `vv` prefix injection) deserve dedicated direct coverage so a
 * future refactor that touches the regex or the URL parser path
 * fails the test before it ships.
 *
 * Spec: in-app-update-test-coverage-closeout.md
 */

import { describe, it, expect } from 'vitest';
import { buildReleaseUrl, isTrustedReleaseUrl, RELEASE_PATH_RE } from '../releaseUrl.js';

describe('isTrustedReleaseUrl', () => {
  // ── Valid inputs ──────────────────────────────────────────────────

  it('accepts the canonical /releases/latest path', () => {
    expect(
      isTrustedReleaseUrl('https://github.com/homelab-00/TranscriptionSuite/releases/latest'),
    ).toBe(true);
  });

  it('accepts a /releases/tag/v<version> path', () => {
    expect(
      isTrustedReleaseUrl('https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3'),
    ).toBe(true);
  });

  it('accepts the bare /releases path', () => {
    expect(isTrustedReleaseUrl('https://github.com/homelab-00/TranscriptionSuite/releases')).toBe(
      true,
    );
  });

  // ── Origin spoofing ───────────────────────────────────────────────

  it('rejects a host-confusion URL whose host contains "github.com" as a prefix', () => {
    expect(
      isTrustedReleaseUrl(
        'https://github.com.evil.com/homelab-00/TranscriptionSuite/releases/latest',
      ),
    ).toBe(false);
  });

  it('rejects http:// (not https://)', () => {
    expect(
      isTrustedReleaseUrl('http://github.com/homelab-00/TranscriptionSuite/releases/latest'),
    ).toBe(false);
  });

  // ── Userinfo bypass — `URL.origin` ignores userinfo so the
  //    explicit `username`/`password` check is the only barrier ──────

  it('rejects a userinfo-bearing URL (https://x:y@github.com/...)', () => {
    expect(
      isTrustedReleaseUrl(
        'https://attacker:hunter2@github.com/homelab-00/TranscriptionSuite/releases/latest',
      ),
    ).toBe(false);
  });

  it('rejects a username-only userinfo URL (https://x@github.com/...)', () => {
    expect(
      isTrustedReleaseUrl(
        'https://attacker@github.com/homelab-00/TranscriptionSuite/releases/latest',
      ),
    ).toBe(false);
  });

  // ── Percent-encoding traversal — WHATWG URL parser normalizes
  //    `..` segments BUT keeps percent-encoded segments encoded ──────

  it('rejects a percent-encoded path traversal (e.g. /%2e%2e/)', () => {
    expect(
      isTrustedReleaseUrl('https://github.com/homelab-00/TranscriptionSuite/releases/%2e%2e/foo'),
    ).toBe(false);
  });

  it('rejects a path with any percent-encoded byte', () => {
    expect(
      isTrustedReleaseUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3%20',
      ),
    ).toBe(false);
  });

  it('intentionally accepts percent-encoded segments in QUERY (path-only check)', () => {
    // Witness: `parsed.pathname` excludes the query string, so a `%`
    // in the query passes the path-percent guard. Acceptable because
    // (a) the URL still resolves to github.com origin, and (b) GitHub
    // ignores unknown query params on release pages. If a downstream
    // consumer ever uses `parsed.search` / `parsed.href` in a security-
    // sensitive way (e.g. server-side redirect, SSRF), tighten the
    // guard to inspect the full URL.
    expect(
      isTrustedReleaseUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/latest?x=%2e%2e',
      ),
    ).toBe(true);
  });

  it('intentionally accepts percent-encoded segments in FRAGMENT (path-only check)', () => {
    // Same caveat as the query case above.
    expect(
      isTrustedReleaseUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/latest#%2e%2e',
      ),
    ).toBe(true);
  });

  // ── Wrong-repo path ───────────────────────────────────────────────

  it('rejects a different repo under the same owner', () => {
    expect(isTrustedReleaseUrl('https://github.com/homelab-00/OtherRepo/releases/latest')).toBe(
      false,
    );
  });

  it('rejects a different owner', () => {
    expect(
      isTrustedReleaseUrl('https://github.com/attacker/TranscriptionSuite/releases/latest'),
    ).toBe(false);
  });

  // ── Path injection beyond the allowed shapes ──────────────────────

  it('rejects an extra path segment after /releases/tag/v…', () => {
    expect(
      isTrustedReleaseUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3/foo',
      ),
    ).toBe(false);
  });

  it('rejects a non-version tag path', () => {
    expect(
      isTrustedReleaseUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/tag/notaversion',
      ),
    ).toBe(false);
  });

  // ── Malformed input ───────────────────────────────────────────────

  it('rejects a non-URL string', () => {
    expect(isTrustedReleaseUrl('not-a-url')).toBe(false);
  });

  it('rejects the empty string', () => {
    expect(isTrustedReleaseUrl('')).toBe(false);
  });

  it('exports RELEASE_PATH_RE for downstream auditability', () => {
    // Witness: the regex constant is a public-by-extraction symbol
    // so future refactors that touch the allow-list shape are surfaced
    // by the test file's import block.
    expect(RELEASE_PATH_RE).toBeInstanceOf(RegExp);
  });
});

describe('buildReleaseUrl', () => {
  it('returns /releases/latest when version is null', () => {
    expect(buildReleaseUrl(null)).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
    );
  });

  it('returns /releases/latest when version is the empty string', () => {
    expect(buildReleaseUrl('')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/latest',
    );
  });

  it('builds a single-v tag URL from a bare semver', () => {
    expect(buildReleaseUrl('1.3.3')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
    );
  });

  it('strips a leading lower-case v from the input version', () => {
    expect(buildReleaseUrl('v1.3.3')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
    );
  });

  it('strips a leading upper-case V (case-insensitive)', () => {
    expect(buildReleaseUrl('V1.3.3')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/tag/v1.3.3',
    );
  });

  it('strips a SINGLE leading v (the documented one-v-strip behavior)', () => {
    // The regex `^v/i` strips ONE leading v only — designed for the
    // case where `app.latest` carries the canonical tag prefix `v1.3.3`.
    // It does NOT defend against multi-v prefixes like `vv1.3.3`; that
    // input becomes `tag/vv1.3.3` (witness regression below). A future
    // hardening pass that wants to fully canonicalize should use
    // `/^v+/i`.
    expect(buildReleaseUrl('vv1.3.3')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/tag/vv1.3.3',
    );
  });
});
