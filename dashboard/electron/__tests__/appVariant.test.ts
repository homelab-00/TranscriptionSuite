import { describe, it, expect } from 'vitest';
import {
  resolveMacDmgAssetName,
  buildAssetDownloadUrl,
  isTrustedAssetUrl,
  sha512FromLatestYml,
} from '../appVariant.js';

describe('resolveMacDmgAssetName', () => {
  it('names the metal DMG for the metal variant', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-metal')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('names the standard arm64 DMG', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-standard-arm64')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac.dmg',
    );
  });
  it('names the standard x64 DMG', () => {
    expect(resolveMacDmgAssetName('1.3.7', 'mac-standard-x64')).toBe(
      'TranscriptionSuite-1.3.7-x64-mac.dmg',
    );
  });
  it('strips a leading v from the version', () => {
    expect(resolveMacDmgAssetName('v1.3.7', 'mac-metal')).toBe(
      'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('throws for non-mac variants', () => {
    expect(() => resolveMacDmgAssetName('1.3.7', 'linux')).toThrow();
  });
});

describe('buildAssetDownloadUrl', () => {
  it('builds a tagged release asset URL', () => {
    expect(buildAssetDownloadUrl('1.3.7', 'TranscriptionSuite-1.3.7-arm64-mac-metal.dmg')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/TranscriptionSuite-1.3.7-arm64-mac-metal.dmg',
    );
  });
  it('strips a leading v from version', () => {
    expect(buildAssetDownloadUrl('v1.3.7', 'latest-mac.yml')).toBe(
      'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/latest-mac.yml',
    );
  });
});

describe('isTrustedAssetUrl', () => {
  it('accepts a well-formed asset URL', () => {
    expect(
      isTrustedAssetUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/TranscriptionSuite-1.3.7-arm64-mac.dmg',
      ),
    ).toBe(true);
  });
  it('rejects a non-github origin', () => {
    expect(
      isTrustedAssetUrl(
        'https://evil.example/homelab-00/TranscriptionSuite/releases/download/v1.3.7/x.dmg',
      ),
    ).toBe(false);
  });
  it('rejects userinfo bypass', () => {
    expect(
      isTrustedAssetUrl(
        'https://github.com@evil.example/homelab-00/TranscriptionSuite/releases/download/v1.3.7/x.dmg',
      ),
    ).toBe(false);
  });
  it('rejects percent-encoded path traversal', () => {
    expect(
      isTrustedAssetUrl(
        'https://github.com/homelab-00/TranscriptionSuite/releases/download/v1.3.7/%2e%2e/secret',
      ),
    ).toBe(false);
  });
  it('rejects the wrong repo', () => {
    expect(
      isTrustedAssetUrl('https://github.com/homelab-00/OtherRepo/releases/download/v1.3.7/x.dmg'),
    ).toBe(false);
  });
});

describe('sha512FromLatestYml', () => {
  const yml = [
    'version: 1.3.7',
    'files:',
    '  - url: TranscriptionSuite-1.3.7-arm64-mac.dmg',
    '    sha512: AAAAsha512forArm64==',
    '    size: 111',
    '  - url: TranscriptionSuite-1.3.7-x64-mac.dmg',
    '    sha512: BBBBsha512forX64==',
    '    size: 222',
    'path: TranscriptionSuite-1.3.7-arm64-mac.dmg',
    'sha512: AAAAsha512forArm64==',
  ].join('\n');
  it('returns the sha512 for the named asset', () => {
    expect(sha512FromLatestYml(yml, 'TranscriptionSuite-1.3.7-x64-mac.dmg')).toBe(
      'BBBBsha512forX64==',
    );
  });
  it('returns null when the asset is absent', () => {
    expect(sha512FromLatestYml(yml, 'not-present.dmg')).toBeNull();
  });
  it('returns null on unparsable yaml', () => {
    expect(sha512FromLatestYml(': : not yaml : :', 'x.dmg')).toBeNull();
  });
});
