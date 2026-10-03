// @vitest-environment node

/**
 * GH-318 - progress for image pulls.
 *
 * The fixtures are real output, captured from `docker pull` and `podman pull`
 * without a TTY and from the Docker Engine API (Docker 29.8, Podman 6.1).
 * What each source can honestly report differs, and the tests pin that:
 *  - docker CLI: per-layer states only, so a layer-count fraction, no bytes
 *  - Engine API: bytes per layer
 *  - podman CLI: which blobs it started, never which finished - indeterminate
 */

import { describe, it, expect } from 'vitest';
import { PullProgressAggregator, enginePullError } from '../pullProgress.js';

const DOCKER_CLI = `3.13-alpine: Pulling from library/python
e2de96513ba9: Pulling fs layer
48f6a2588427: Pulling fs layer
6f4c23997e2d: Pulling fs layer
82c48d7f22df: Pulling fs layer
82c48d7f22df: Waiting
e2de96513ba9: Verifying Checksum
e2de96513ba9: Download complete
48f6a2588427: Verifying Checksum
48f6a2588427: Download complete
82c48d7f22df: Verifying Checksum
82c48d7f22df: Download complete
6f4c23997e2d: Verifying Checksum
6f4c23997e2d: Download complete
e2de96513ba9: Pull complete
48f6a2588427: Pull complete
6f4c23997e2d: Pull complete
82c48d7f22df: Pull complete
Digest: sha256:2dd78ad5cf13a0b68f5134dc49aa9950203a8cf4b7463431b9f3b398287c5059
Status: Downloaded newer image for python:3.13-alpine
docker.io/library/python:3.13-alpine`.split('\n');

const PODMAN_CLI = `Trying to pull docker.io/library/python:3.13-alpine...
Getting image source signatures
Copying blob sha256:e2de96513ba9eb53b431787ec8a65cdde380ac4772a3e4c4b714dcfde2a102b5
Copying blob sha256:48f6a258842734fe23e0e4c69db9996cbaefd41c1cde2372b95449f9fc5601eb
Copying blob sha256:6f4c23997e2db272b9d27917c421c0322c90ce90f0b4eeecd39ce268bdb688d0
Copying blob sha256:82c48d7f22df9ea2f3393a3daf83a7abb5e933e5fb7f4d1b701dc8f71ebff248
Copying config sha256:050f6d1f4e5f89af62e03f6fcd1c06be2a401339b3694adc4c0a2850d9d8b1e7
Writing manifest to image destination`.split('\n');

function feedCli(agg: PullProgressAggregator, lines: string[]): void {
  for (const line of lines) agg.applyCliLine(line);
}

describe('PullProgressAggregator - docker CLI without a TTY', () => {
  it('knows the layers as soon as they are announced', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, DOCKER_CLI.slice(0, 6));

    expect(agg.progress()).toEqual({ percent: 0, detail: '0 of 4 layers' });
  });

  it('advances by finished layers and reports no bytes', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, DOCKER_CLI.slice(0, 10)); // two layers downloaded

    const progress = agg.progress();
    expect(progress).toEqual({ percent: 50, detail: '2 of 4 layers' });
    expect(progress.bytesDone).toBeUndefined();
  });

  it('reports extraction once every layer is downloaded', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, DOCKER_CLI.slice(0, 15));

    expect(agg.progress()).toEqual({ percent: 100, detail: 'Extracting' });
  });

  it('counts a layer that already exists locally as done', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, ['aaaaaaaaaaaa: Already exists', 'bbbbbbbbbbbb: Pulling fs layer']);

    expect(agg.progress()).toEqual({ percent: 50, detail: '1 of 2 layers' });
  });

  it('says which lines changed the progress', () => {
    const agg = new PullProgressAggregator();

    expect(agg.applyCliLine('3.13-alpine: Pulling from library/python')).toBe(false);
    expect(agg.applyCliLine('e2de96513ba9: Pulling fs layer')).toBe(true);
    expect(agg.applyCliLine('e2de96513ba9: Verifying Checksum')).toBe(false);
    expect(agg.applyCliLine('e2de96513ba9: Download complete')).toBe(true);
    expect(agg.applyCliLine('Digest: sha256:2dd78ad5cf13')).toBe(false);
  });

  it('is indeterminate before any layer is known', () => {
    expect(new PullProgressAggregator().progress()).toEqual({});
  });
});

describe('PullProgressAggregator - podman CLI without a TTY', () => {
  it('stays indeterminate: podman says which blobs it started, never which finished', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, PODMAN_CLI.slice(0, 6));

    const progress = agg.progress();
    expect(progress.percent).toBeUndefined();
    expect(progress.detail).toBe('Copying 4 layers');
  });

  it('reports the final write', () => {
    const agg = new PullProgressAggregator();
    feedCli(agg, PODMAN_CLI);

    expect(agg.progress()).toEqual({ detail: 'Writing image' });
  });
});

describe('PullProgressAggregator - Engine API', () => {
  it('reports bytes and weights each layer by its own fraction', () => {
    const agg = new PullProgressAggregator();
    agg.applyApiMessage({ status: 'Pulling fs layer', progressDetail: {}, id: 'e2de96513ba9' });
    agg.applyApiMessage({ status: 'Pulling fs layer', progressDetail: {}, id: '6f4c23997e2d' });
    agg.applyApiMessage({
      status: 'Downloading',
      progressDetail: { current: 1_000_000, total: 4_000_000 },
      id: 'e2de96513ba9',
    });

    // One of two layers is a quarter done.
    expect(agg.progress()).toEqual({
      percent: 12.5,
      bytesDone: 1_000_000,
      detail: '0 of 2 layers',
    });
  });

  it('counts a finished layer at its full size', () => {
    const agg = new PullProgressAggregator();
    agg.applyApiMessage({ status: 'Pulling fs layer', progressDetail: {}, id: 'a' });
    agg.applyApiMessage({ status: 'Pulling fs layer', progressDetail: {}, id: 'b' });
    agg.applyApiMessage({
      status: 'Downloading',
      progressDetail: { current: 100, total: 4_000 },
      id: 'a',
    });
    agg.applyApiMessage({ status: 'Download complete', progressDetail: {}, id: 'a' });

    expect(agg.progress()).toEqual({ percent: 50, bytesDone: 4_000, detail: '1 of 2 layers' });
  });

  it('does not mistake extraction progress for download bytes', () => {
    const agg = new PullProgressAggregator();
    agg.applyApiMessage({ status: 'Pulling fs layer', progressDetail: {}, id: 'a' });
    agg.applyApiMessage({
      status: 'Downloading',
      progressDetail: { current: 4_000, total: 4_000 },
      id: 'a',
    });
    agg.applyApiMessage({ status: 'Download complete', progressDetail: {}, id: 'a' });
    agg.applyApiMessage({
      status: 'Extracting',
      progressDetail: { current: 10, total: 4_000 },
      id: 'a',
    });

    expect(agg.progress()).toEqual({ percent: 100, bytesDone: 4_000, detail: 'Extracting' });
  });

  it('ignores messages that are not about a layer', () => {
    const agg = new PullProgressAggregator();

    expect(agg.applyApiMessage({ status: 'Pulling from library/python', id: '3.13-alpine' })).toBe(
      false,
    );
    expect(agg.applyApiMessage({ status: 'Digest: sha256:2dd78ad5' })).toBe(false);
    expect(agg.progress()).toEqual({});
  });
});

describe('enginePullError', () => {
  it('extracts the daemon error text', () => {
    expect(
      enginePullError({
        errorDetail: { message: 'manifest unknown' },
        error: 'manifest unknown',
      }),
    ).toBe('manifest unknown');
  });

  it('is null for a normal progress message', () => {
    expect(enginePullError({ status: 'Downloading', id: 'a' })).toBeNull();
  });
});
