/**
 * CompatGuard — pre-flight server-compatibility check for in-app updates.
 *
 * Scope (M4):
 *  - Fetches manifest.json from the GitHub releases/latest asset list.
 *  - Probes the running server version via /api/admin/status.version
 *    (added alongside M4 in server/backend/api/routes/admin.py).
 *  - Evaluates the manifest's compatibleServerRange (semver) against the
 *    server version using the `semver` package.
 *  - Persists the last successfully-parsed manifest in electron-store under
 *    `updates.lastManifest` so M6 can later read `sha256`.
 *
 * Fail-open philosophy: every "unknown" outcome (network failure, missing
 * manifest, unreachable server, missing .version field, unparsable range)
 * returns a `{result:'unknown', ...}` and lets the caller decide. The
 * `updates:download` IPC handler delegates through to
 * `UpdateInstaller.startDownload()` in every unknown case — blocking every
 * user on a transient outage would be worse than the rare miss of a
 * legitimate incompatibility signal. Downstream defenses: M6's SHA-256 +
 * watchdog rollback.
 *
 * Intentionally deferred:
 *  - M5 renders incompatibility into the pre-install modal (via the new
 *    `updates:checkCompatibility` IPC).
 *  - M6 verifies the downloaded binary against `sha256` from the persisted
 *    manifest.
 */

import semver from 'semver';
import type Store from 'electron-store';

import { getServerUrl, getAuthToken } from './appState.js';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyStore = Store<any>;

const RELEASES_URL = 'https://api.github.com/repos/homelab-00/TranscriptionSuite/releases/latest';
const MANIFEST_ASSET_NAME = 'manifest.json';
const RELEASES_TIMEOUT_MS = 15_000;
const SERVER_STATUS_TIMEOUT_MS = 5_000;
const MANIFEST_STORE_KEY = 'updates.lastManifest';

/**
 * Upper bound on a legitimate manifest payload (~200 bytes typical per
 * brainstorming doc D1). A 1 MB ceiling is a DoS defense against a
 * malformed or malicious release asset without risking false negatives on
 * any realistic manifest.
 */
const MAX_MANIFEST_BYTES = 1 * 1024 * 1024;

/**
 * Upper bound on `sha256` entry count. Typical releases ship 3-5 binaries
 * (Linux/Windows/Mac variants). 32 is a very generous headroom that still
 * rejects adversarial manifests aimed at store/memory inflation.
 */
const MAX_SHA256_ENTRIES = 32;

const SHA256_HEX_RE = /^[a-f0-9]{64}$/;

/**
 * Host allow-list for the manifest asset download. GitHub serves release
 * assets from github.com (redirecting to) objects.githubusercontent.com.
 * Restricting the scheme+host prevents a poisoned release payload from
 * redirecting the fetch to an attacker-controlled origin.
 */
const ALLOWED_ASSET_HOSTS = new Set([
  'github.com',
  'api.github.com',
  'objects.githubusercontent.com',
]);

/** Keys forbidden in `sha256` — blocks prototype-pollution attempts. */
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

// ─── Types ──────────────────────────────────────────────────────────────────

export interface Manifest {
  version: string;
  compatibleServerRange: string;
  sha256: Record<string, string>;
  releaseType: string;
}

export type CompatUnknownReason =
  | 'no-manifest'
  | 'manifest-fetch-failed'
  | 'manifest-parse-error'
  | 'server-version-unavailable'
  | 'invalid-range';

export type CompatResult =
  | { result: 'compatible'; manifest: Manifest; serverVersion: string }
  | {
      result: 'incompatible';
      manifest: Manifest;
      serverVersion: string;
      compatibleRange: string;
      deployment: 'local' | 'remote';
    }
  | { result: 'unknown'; reason: CompatUnknownReason; detail?: string };

export interface CompatGuardLogger {
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

export interface CompatGuardOptions {
  store: AnyStore;
  logger?: CompatGuardLogger;
  fetchImpl?: typeof fetch;
}

const defaultLogger: CompatGuardLogger = {
  info: (...args) => console.info('[CompatGuard]', ...args),
  warn: (...args) => console.warn('[CompatGuard]', ...args),
  error: (...args) => console.error('[CompatGuard]', ...args),
};

// ─── Manifest parsing ───────────────────────────────────────────────────────

function isManifest(x: unknown): x is Manifest {
  if (!x || typeof x !== 'object' || Array.isArray(x)) return false;
  const m = x as Record<string, unknown>;
  if (
    typeof m.version !== 'string' ||
    typeof m.compatibleServerRange !== 'string' ||
    typeof m.releaseType !== 'string'
  ) {
    return false;
  }
  if (!semver.valid(m.version)) return false;
  if (!m.sha256 || typeof m.sha256 !== 'object' || Array.isArray(m.sha256)) {
    return false;
  }
  const sha256 = m.sha256 as Record<string, unknown>;
  // `Object.keys` only enumerates own properties, so a parent's
  // `__proto__` getter can't smuggle in additional keys — but an explicit
  // own key named `__proto__` in the JSON text CAN land here. Reject the
  // trio of prototype-adjacent names regardless.
  const keys = Object.keys(sha256);
  if (keys.length === 0 || keys.length > MAX_SHA256_ENTRIES) return false;
  for (const key of keys) {
    if (FORBIDDEN_KEYS.has(key)) return false;
    const value = sha256[key];
    if (typeof value !== 'string') return false;
    if (!SHA256_HEX_RE.test(value)) return false;
  }
  return true;
}

function isAllowedAssetUrl(raw: string): boolean {
  try {
    const u = new URL(raw);
    return u.protocol === 'https:' && ALLOWED_ASSET_HOSTS.has(u.hostname);
  } catch {
    return false;
  }
}

function exceedsManifestSize(resp: Response): boolean {
  const lengthHeader = resp.headers?.get?.('content-length');
  if (!lengthHeader) return false;
  const bytes = Number.parseInt(lengthHeader, 10);
  return Number.isFinite(bytes) && bytes > MAX_MANIFEST_BYTES;
}

// ─── CompatGuard ────────────────────────────────────────────────────────────

export class CompatGuard {
  private readonly store: AnyStore;
  private readonly logger: CompatGuardLogger;
  private readonly fetchFn: typeof fetch;
  private inflight: Promise<CompatResult> | null = null;
  private destroyed = false;

  constructor(opts: CompatGuardOptions) {
    this.store = opts.store;
    this.logger = opts.logger ?? defaultLogger;
    this.fetchFn = opts.fetchImpl ?? fetch;
  }

  /**
   * Run a full compatibility check. Single-flight — concurrent callers
   * await the same in-flight Promise. Post-destroy calls short-circuit
   * so `gracefulShutdown` ordering can't re-enter the network path.
   */
  check(): Promise<CompatResult> {
    if (this.destroyed) {
      return Promise.resolve({
        result: 'unknown',
        reason: 'manifest-fetch-failed',
        detail: 'destroyed',
      });
    }
    if (this.inflight) return this.inflight;
    const promise = this.doCheck().finally(() => {
      // Clear AFTER the promise settles so late `.then()` chains don't race
      // with a new inflight assignment.
      if (this.inflight === promise) {
        this.inflight = null;
      }
    });
    this.inflight = promise;
    return promise;
  }

  getLastManifest(): Manifest | null {
    try {
      const raw = this.store.get(MANIFEST_STORE_KEY);
      if (!isManifest(raw)) return null;
      return raw;
    } catch (err) {
      // A corrupt or locked electron-store must not propagate out of a
      // read-side accessor. Treat as "no cached manifest".
      this.logger.warn('getLastManifest: store read failed', err);
      return null;
    }
  }

  destroy(): void {
    this.destroyed = true;
  }

  // ─── Internals ────────────────────────────────────────────────────────

  private async doCheck(): Promise<CompatResult> {
    const manifestResult = await this.fetchManifest();
    if (manifestResult.kind !== 'ok') {
      return manifestResult.result;
    }
    const manifest = manifestResult.manifest;

    // If destroyed mid-fetch, discard the result and skip persistence.
    if (this.destroyed) {
      return {
        result: 'unknown',
        reason: 'manifest-fetch-failed',
        detail: 'destroyed',
      };
    }

    // Persist on every successful parse — even on incompatible. M6 needs
    // `sha256` regardless of the compat outcome for this specific call.
    try {
      this.store.set(MANIFEST_STORE_KEY, manifest);
    } catch (err) {
      // Persistence is best-effort; don't fail the whole check on a store
      // write error (e.g. disk full, permissions).
      this.logger.warn('manifest persistence failed', err);
    }

    const serverVersion = await this.fetchServerVersion();
    if (serverVersion === null) {
      return {
        result: 'unknown',
        reason: 'server-version-unavailable',
        detail: 'could-not-probe',
      };
    }
    if (!semver.valid(serverVersion)) {
      this.logger.warn('server version is not valid semver:', serverVersion);
      return {
        result: 'unknown',
        reason: 'server-version-unavailable',
        detail: `invalid-semver: ${serverVersion}`,
      };
    }

    if (!semver.validRange(manifest.compatibleServerRange)) {
      this.logger.warn('invalid compatibleServerRange:', manifest.compatibleServerRange);
      return {
        result: 'unknown',
        reason: 'invalid-range',
        detail: manifest.compatibleServerRange,
      };
    }

    const compatible = semver.satisfies(serverVersion, manifest.compatibleServerRange, {
      includePrerelease: false,
    });

    if (compatible) {
      return { result: 'compatible', manifest, serverVersion };
    }

    const useRemote = (this.store.get('connection.useRemote') as boolean) ?? false;
    return {
      result: 'incompatible',
      manifest,
      serverVersion,
      compatibleRange: manifest.compatibleServerRange,
      deployment: useRemote ? 'remote' : 'local',
    };
  }

  /**
   * Fetch and parse manifest.json from the GitHub releases/latest asset
   * list. Returns a tagged result so the caller can short-circuit on
   * unknown outcomes without losing access to the parsed manifest on
   * success.
   */
  private async fetchManifest(): Promise<
    | { kind: 'ok'; manifest: Manifest }
    | { kind: 'err'; result: Extract<CompatResult, { result: 'unknown' }> }
  > {
    // Step 1: fetch the release payload
    let releaseResp: Response;
    try {
      releaseResp = await this.fetchFn(RELEASES_URL, {
        headers: { Accept: 'application/vnd.github+json' },
        signal: AbortSignal.timeout(RELEASES_TIMEOUT_MS),
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: manifest-fetch-failed (releases)', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-fetch-failed', detail },
      };
    }
    if (!releaseResp.ok) {
      const detail = `releases/latest HTTP ${releaseResp.status}`;
      this.logger.warn('unknown: manifest-fetch-failed', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-fetch-failed', detail },
      };
    }

    let releaseData: {
      assets?: Array<{ name?: string; browser_download_url?: string }>;
    };
    try {
      releaseData = (await releaseResp.json()) as typeof releaseData;
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: manifest-fetch-failed (releases-json)', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-fetch-failed', detail },
      };
    }

    // Guard: GitHub's releases API normally returns assets as an array,
    // but a malformed response or API change shouldn't crash .find().
    const assetsList = Array.isArray(releaseData.assets) ? releaseData.assets : [];
    const asset = assetsList.find(
      (a) => a && typeof a.name === 'string' && a.name === MANIFEST_ASSET_NAME,
    );
    if (!asset || typeof asset.browser_download_url !== 'string') {
      this.logger.warn('unknown: no-manifest');
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'no-manifest' },
      };
    }
    // Defense-in-depth: the asset URL comes from the releases payload. A
    // poisoned payload (or future GitHub API shape change) must not be able
    // to redirect the fetch to an arbitrary origin.
    if (!isAllowedAssetUrl(asset.browser_download_url)) {
      this.logger.warn('unknown: manifest-fetch-failed (asset-url-rejected)');
      return {
        kind: 'err',
        result: {
          result: 'unknown',
          reason: 'manifest-fetch-failed',
          detail: 'asset-url-rejected',
        },
      };
    }

    // Step 2: fetch the manifest asset
    let manifestResp: Response;
    try {
      manifestResp = await this.fetchFn(asset.browser_download_url, {
        headers: { Accept: 'application/json, */*;q=0.1' },
        signal: AbortSignal.timeout(RELEASES_TIMEOUT_MS),
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: manifest-fetch-failed (asset)', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-fetch-failed', detail },
      };
    }
    if (!manifestResp.ok) {
      const detail = `manifest asset HTTP ${manifestResp.status}`;
      this.logger.warn('unknown: manifest-fetch-failed', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-fetch-failed', detail },
      };
    }
    if (exceedsManifestSize(manifestResp)) {
      this.logger.warn('unknown: manifest-fetch-failed (oversized)');
      return {
        kind: 'err',
        result: {
          result: 'unknown',
          reason: 'manifest-fetch-failed',
          detail: 'oversized',
        },
      };
    }

    let manifestJson: unknown;
    try {
      manifestJson = await manifestResp.json();
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: manifest-parse-error', detail);
      return {
        kind: 'err',
        result: { result: 'unknown', reason: 'manifest-parse-error', detail },
      };
    }

    if (!isManifest(manifestJson)) {
      this.logger.warn('unknown: manifest-parse-error (shape)');
      return {
        kind: 'err',
        result: {
          result: 'unknown',
          reason: 'manifest-parse-error',
          detail: 'shape-mismatch',
        },
      };
    }

    return { kind: 'ok', manifest: manifestJson };
  }

  /**
   * Fetch the server's running version from /api/admin/status. Returns
   * `null` on any probe failure (HTTP error, timeout, missing field, etc.).
   */
  private async fetchServerVersion(): Promise<string | null> {
    const url = `${getServerUrl(this.store)}/api/admin/status`;
    const token = getAuthToken(this.store);
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;

    let resp: Response;
    try {
      resp = await this.fetchFn(url, {
        method: 'GET',
        headers,
        signal: AbortSignal.timeout(SERVER_STATUS_TIMEOUT_MS),
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: server-version-unavailable', detail);
      return null;
    }

    if (!resp.ok) {
      this.logger.warn('unknown: server-version-unavailable', `HTTP ${resp.status}`);
      return null;
    }

    let body: unknown;
    try {
      body = await resp.json();
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      this.logger.warn('unknown: server-version-unavailable', detail);
      return null;
    }

    // Null body or non-object (e.g. FastAPI returning "null" on an odd
    // error path) must not throw when we read `.version`.
    if (!body || typeof body !== 'object') {
      this.logger.warn('unknown: server-version-unavailable', 'body-not-object');
      return null;
    }
    const version = (body as Record<string, unknown>).version;
    if (typeof version !== 'string' || version.length === 0) {
      this.logger.warn('unknown: server-version-unavailable', 'version-field-absent');
      return null;
    }
    return version;
  }
}
