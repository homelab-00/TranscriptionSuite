/**
 * Progress for container image pulls (GH-318).
 *
 * Pure: turns pull output into the progress shape the DownloadHub takes. What
 * can be reported honestly depends on where the output comes from:
 *
 *  - docker CLI without a TTY prints per-layer states only ("Pulling fs
 *    layer", "Download complete", "Pull complete", "Already exists") - no
 *    bytes. Progress is the fraction of layers downloaded.
 *  - the Engine API streams bytes per layer. Layer totals only become known
 *    as each layer starts, so an overall byte percent would jump backwards;
 *    the bar instead averages the layers, each weighted by its own byte
 *    fraction, and the byte count is reported alongside it.
 *  - podman CLI without a TTY prints which blobs it started and never which
 *    finished. No fraction can be derived, so the item stays indeterminate.
 */

import type { DownloadProgress } from './downloadHub.js';

/** One JSON message of the Engine API `POST /images/create` stream. */
export interface EnginePullMessage {
  status?: string;
  id?: string;
  progressDetail?: { current?: number; total?: number };
  error?: string;
  errorDetail?: { message?: string };
}

interface LayerState {
  /** Bytes are in (downloaded now, or already present locally). */
  downloaded: boolean;
  current?: number;
  total?: number;
}

const DOCKER_LAYER_LINE_RE = /^([0-9a-f]{12}): (.+)$/;
const PODMAN_BLOB_LINE_RE = /^Copying blob (?:sha256:)?([0-9a-f]+)/;
const PODMAN_FINAL_LINE_RE = /^(Copying config|Writing manifest)/;

/** The daemon's error text if *message* reports a failed pull, else null. */
export function enginePullError(message: EnginePullMessage): string | null {
  return message.error || message.errorDetail?.message || null;
}

export class PullProgressAggregator {
  private readonly layers = new Map<string, LayerState>();
  private readonly podmanBlobs = new Set<string>();
  private podmanWriting = false;

  /** Consume one line of CLI output. Returns true when the progress changed. */
  applyCliLine(line: string): boolean {
    const text = line.trim();
    const layer = DOCKER_LAYER_LINE_RE.exec(text);
    if (layer) return this.applyLayerStatus(layer[1], layer[2]);

    const blob = PODMAN_BLOB_LINE_RE.exec(text);
    if (blob) {
      if (this.podmanBlobs.has(blob[1])) return false;
      this.podmanBlobs.add(blob[1]);
      return true;
    }
    if (PODMAN_FINAL_LINE_RE.test(text) && !this.podmanWriting) {
      this.podmanWriting = true;
      return true;
    }
    return false;
  }

  /** Consume one Engine API stream message. Returns true when the progress changed. */
  applyApiMessage(message: EnginePullMessage): boolean {
    if (!message.id || !message.status) return false;
    return this.applyLayerStatus(message.id, message.status, message.progressDetail);
  }

  progress(): DownloadProgress {
    if (this.layers.size === 0) {
      if (this.podmanBlobs.size === 0) return {};
      if (this.podmanWriting) return { detail: 'Writing image' };
      const count = this.podmanBlobs.size;
      return { detail: `Copying ${count} layer${count === 1 ? '' : 's'}` };
    }

    const layers = [...this.layers.values()];
    const downloadedCount = layers.filter((l) => l.downloaded).length;
    const fraction = layers.reduce((sum, l) => sum + layerFraction(l), 0) / layers.length;
    const hasBytes = layers.some((l) => l.current !== undefined || l.total !== undefined);

    return {
      percent: Math.round(fraction * 1000) / 10,
      ...(hasBytes ? { bytesDone: layers.reduce((sum, l) => sum + layerBytes(l), 0) } : {}),
      detail:
        downloadedCount === layers.length
          ? 'Extracting'
          : `${downloadedCount} of ${layers.length} layers`,
    };
  }

  private applyLayerStatus(
    id: string,
    status: string,
    detail?: { current?: number; total?: number },
  ): boolean {
    switch (status) {
      case 'Pulling fs layer':
      case 'Waiting': {
        if (this.layers.has(id)) return false;
        this.layers.set(id, { downloaded: false });
        return true;
      }
      case 'Downloading': {
        const layer = this.layer(id);
        if (typeof detail?.current === 'number') layer.current = detail.current;
        if (typeof detail?.total === 'number' && detail.total > 0) layer.total = detail.total;
        return true;
      }
      case 'Download complete':
      case 'Already exists':
      case 'Pull complete': {
        const layer = this.layer(id);
        if (layer.downloaded) return false;
        layer.downloaded = true;
        return true;
      }
      default:
        // "Verifying Checksum", "Extracting" (its progressDetail counts
        // extracted bytes, not downloaded ones) and the image-level lines.
        return false;
    }
  }

  private layer(id: string): LayerState {
    let layer = this.layers.get(id);
    if (!layer) {
      layer = { downloaded: false };
      this.layers.set(id, layer);
    }
    return layer;
  }
}

function layerFraction(layer: LayerState): number {
  if (layer.downloaded) return 1;
  if (layer.total && layer.current !== undefined) return Math.min(1, layer.current / layer.total);
  return 0;
}

function layerBytes(layer: LayerState): number {
  if (layer.downloaded) return layer.total ?? layer.current ?? 0;
  return layer.current ?? 0;
}
