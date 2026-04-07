import { describe, it, expect } from 'vitest';
import {
  parseVersionTag,
  compareVersionTags,
  sortVersionTagsDesc,
  IMAGE_REPO,
} from './versionUtils';

describe('parseVersionTag', () => {
  it('parses a stable version tag', () => {
    expect(parseVersionTag('v1.2.3')).toEqual({
      major: 1,
      minor: 2,
      patch: 3,
      isRC: false,
      raw: 'v1.2.3',
    });
  });

  it('parses an RC version tag', () => {
    expect(parseVersionTag('v1.2.3rc')).toEqual({
      major: 1,
      minor: 2,
      patch: 3,
      isRC: true,
      raw: 'v1.2.3rc',
    });
  });

  it('parses RC tag with number suffix', () => {
    expect(parseVersionTag('v2.0.0rc2')).toEqual({
      major: 2,
      minor: 0,
      patch: 0,
      isRC: true,
      raw: 'v2.0.0rc2',
    });
  });

  it('returns null for non-version tags', () => {
    expect(parseVersionTag('latest')).toBeNull();
    expect(parseVersionTag('main')).toBeNull();
    expect(parseVersionTag('sha-abc123')).toBeNull();
    expect(parseVersionTag('')).toBeNull();
  });

  it('returns null for tags with extra segments', () => {
    expect(parseVersionTag('v1.2.3.4')).toBeNull();
    expect(parseVersionTag('v1.2')).toBeNull();
  });
});

describe('compareVersionTags', () => {
  it('sorts higher major versions first (descending)', () => {
    expect(compareVersionTags('v2.0.0', 'v1.0.0')).toBeLessThan(0);
    expect(compareVersionTags('v1.0.0', 'v2.0.0')).toBeGreaterThan(0);
  });

  it('sorts higher minor versions first', () => {
    expect(compareVersionTags('v1.3.0', 'v1.2.0')).toBeLessThan(0);
  });

  it('sorts higher patch versions first', () => {
    expect(compareVersionTags('v1.2.3', 'v1.2.2')).toBeLessThan(0);
  });

  it('sorts stable above RC at same version', () => {
    expect(compareVersionTags('v1.2.3', 'v1.2.3rc')).toBeLessThan(0);
    expect(compareVersionTags('v1.2.3rc', 'v1.2.3')).toBeGreaterThan(0);
  });

  it('returns 0 for equal versions', () => {
    expect(compareVersionTags('v1.0.0', 'v1.0.0')).toBe(0);
    expect(compareVersionTags('v1.0.0rc', 'v1.0.0rc')).toBe(0);
  });

  it('handles unparsable tags by pushing them to end', () => {
    expect(compareVersionTags('v1.0.0', 'latest')).toBeLessThan(0);
    expect(compareVersionTags('latest', 'v1.0.0')).toBeGreaterThan(0);
    expect(compareVersionTags('latest', 'main')).toBe(0);
  });
});

describe('sortVersionTagsDesc', () => {
  it('sorts tags in descending semver order', () => {
    const tags = ['v1.0.0', 'v1.2.3rc', 'v1.2.3', 'v1.1.0', 'v2.0.0'];
    expect(sortVersionTagsDesc(tags)).toEqual(['v2.0.0', 'v1.2.3', 'v1.2.3rc', 'v1.1.0', 'v1.0.0']);
  });

  it('returns empty array for empty input', () => {
    expect(sortVersionTagsDesc([])).toEqual([]);
  });
});

describe('IMAGE_REPO', () => {
  it('matches the canonical image repository', () => {
    expect(IMAGE_REPO).toBe('ghcr.io/homelab-00/transcriptionsuite-server');
  });
});
