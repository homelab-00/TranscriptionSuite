/**
 * appVariant — pure helpers identifying which build of the dashboard is
 * running and mapping that to the matching GitHub release asset.
 *
 * The desktop app varies only by platform, except on macOS where a "metal"
 * DMG (bundles the MLX Python backend under resources/backend) is shipped
 * alongside the standard DMG. The updater must fetch the SAME variant.
 *
 * Detection mirrors the probe previously embedded in mlxServerManager
 * (packaged app + resources/backend existence). Kept side-effect-light and
 * Electron-decoupled (detectAppVariant takes its inputs) so it is unit-testable.
 */
import * as path from 'node:path';
import * as fs from 'node:fs';

export type AppVariant =
  | 'mac-metal'
  | 'mac-standard-arm64'
  | 'mac-standard-x64'
  | 'linux'
  | 'windows';

const PRODUCT_NAME = 'TranscriptionSuite';
const REPO_PATH = 'homelab-00/TranscriptionSuite';

export interface VariantProbe {
  platform: NodeJS.Platform;
  arch: string;
  isPackaged: boolean;
  resourcesPath: string | undefined;
}

/**
 * Determine the running app variant. On macOS, "metal" is inferred from the
 * bundled backend directory (resources/backend) exactly like mlxServerManager's
 * diagnostic. In dev (isPackaged=false) resourcesPath points at Electron's own
 * resources, so metal is never claimed unless packaged.
 */
export function detectAppVariant(probe: VariantProbe): AppVariant {
  if (probe.platform === 'win32') return 'windows';
  if (probe.platform === 'linux') return 'linux';
  // darwin
  const hasBundledBackend =
    probe.isPackaged &&
    !!probe.resourcesPath &&
    fs.existsSync(path.join(probe.resourcesPath, 'backend'));
  if (hasBundledBackend && probe.arch === 'arm64') return 'mac-metal';
  return probe.arch === 'arm64' ? 'mac-standard-arm64' : 'mac-standard-x64';
}

function stripV(version: string): string {
  return version.replace(/^v/i, '');
}

/** Resolve the release DMG filename for a macOS variant + version. */
export function resolveMacDmgAssetName(version: string, variant: AppVariant): string {
  const v = stripV(version);
  switch (variant) {
    case 'mac-metal':
      return `${PRODUCT_NAME}-${v}-arm64-mac-metal.dmg`;
    case 'mac-standard-arm64':
      return `${PRODUCT_NAME}-${v}-arm64-mac.dmg`;
    case 'mac-standard-x64':
      return `${PRODUCT_NAME}-${v}-x64-mac.dmg`;
    default:
      throw new Error(`resolveMacDmgAssetName: not a macOS variant: ${variant}`);
  }
}

/** Construct the GitHub release asset download URL. */
export function buildAssetDownloadUrl(version: string, assetName: string): string {
  const v = stripV(version);
  return `https://github.com/${REPO_PATH}/releases/download/v${v}/${assetName}`;
}

const ASSET_PATH_RE =
  /^\/homelab-00\/TranscriptionSuite\/releases\/download\/v[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;

/**
 * Allow-list guard for asset URLs, mirroring releaseUrl.isTrustedReleaseUrl:
 * origin must be github.com, no userinfo, no percent-encoded path segments,
 * and the path must be a release-download under this repo.
 */
export function isTrustedAssetUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    if (parsed.origin !== 'https://github.com') return false;
    if (parsed.username !== '' || parsed.password !== '') return false;
    if (parsed.pathname.includes('%')) return false;
    return ASSET_PATH_RE.test(parsed.pathname);
  } catch {
    return false;
  }
}

/**
 * Extract the base64 sha512 for a given asset filename by parsing the
 * electron-builder latest-mac.yml text directly. Returns null on a miss
 * (caller treats a null as "verification unavailable" and proceeds).
 */
export function sha512FromLatestYml(ymlText: string, assetName: string): string | null {
  const lines = ymlText.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const urlMatch = lines[i].match(/^\s*-?\s*url:\s*(.+?)\s*$/);
    if (!urlMatch || urlMatch[1] !== assetName) continue;
    // Scan this file entry's fields until the next "- url:" entry begins.
    for (let j = i + 1; j < lines.length; j++) {
      if (/^\s*-\s*url:/.test(lines[j])) break;
      const shaMatch = lines[j].match(/^\s*sha512:\s*(.+?)\s*$/);
      if (shaMatch) return shaMatch[1];
    }
    return null;
  }
  return null;
}
