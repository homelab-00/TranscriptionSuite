import { describe, it, expect } from 'vitest';
import { mapStartupEvent, serverStartPatch, SERVER_START_ID } from '../startupEventMapping';

describe('mapStartupEvent (individual log entries)', () => {
  it('returns null for download events - the download bar owns them', () => {
    expect(
      mapStartupEvent({
        id: 'model-load-openai--whisper-large-v3',
        category: 'download',
        label: 'Downloading Whisper large-v3...',
        status: 'active',
        progress: 42,
        downloadedSize: '1.2 GB',
        totalSize: '3.1 GB',
      }),
    ).toBeNull();
  });

  it('still surfaces a failed model preload from an older server', () => {
    // Older servers emit this load failure with category "download". It is
    // not a download, and it must not vanish with the download mapping.
    const entry = mapStartupEvent({
      id: 'model-preload-error',
      category: 'download',
      label: 'Model preload failed for large-v3. The server started without a loaded model.',
      status: 'error',
      severity: 'error',
      persistent: true,
    });
    expect(entry).toMatchObject({
      id: 'model-preload-error',
      category: 'server',
      status: 'error',
      severity: 'error',
    });
  });

  it('maps a warning event to a server-category record', () => {
    const entry = mapStartupEvent({
      id: 'warn-nemo',
      category: 'warning',
      label: 'NeMo backend unavailable',
      severity: 'warning',
      persistent: true,
    });
    expect(entry).toMatchObject({
      id: 'warn-nemo',
      category: 'server',
      title: 'NeMo backend unavailable',
      status: 'complete',
      severity: 'warning',
    });
  });

  it('returns null for server stage events (they only feed the aggregate)', () => {
    expect(
      mapStartupEvent({ id: 'lifespan-start', category: 'server', label: 'Starting server...' }),
    ).toBeNull();
  });
});

describe('serverStartPatch (aggregate "Starting server" card)', () => {
  it('shows the current stage as the detail, without a made-up percent', () => {
    const patch = serverStartPatch({
      id: 'lifespan-start',
      category: 'server',
      label: 'Starting server...',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      status: 'active',
      detail: 'Starting server...',
    });
    expect(patch).not.toHaveProperty('progress');
  });

  it('shows the model being loaded into memory as the stage', () => {
    const patch = serverStartPatch({
      id: 'model-load-x',
      category: 'download',
      label: 'Loading X into memory...',
      phase: 'load',
      status: 'active',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      status: 'active',
      detail: 'Loading X into memory...',
    });
    expect(patch).not.toHaveProperty('progress');
  });

  it('leaves a model download to the download bar', () => {
    expect(
      serverStartPatch({
        id: 'model-load-x',
        category: 'download',
        label: 'Downloading X...',
        phase: 'download',
        status: 'active',
        progress: 50,
      }),
    ).toBeNull();
  });

  it('completes as Server ready', () => {
    const patch = serverStartPatch({
      id: 'server-ready',
      category: 'server',
      label: 'Server ready',
      status: 'complete',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      title: 'Server ready',
      status: 'complete',
    });
    expect(patch).not.toHaveProperty('progress');
  });

  it('ignores unrelated download events', () => {
    expect(
      serverStartPatch({
        id: 'ggml-download-x',
        category: 'download',
        label: 'GGML',
        progress: 10,
      }),
    ).toBeNull();
  });
});
