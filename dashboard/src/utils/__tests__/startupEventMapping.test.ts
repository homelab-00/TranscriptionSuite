import { describe, it, expect } from 'vitest';
import { mapStartupEvent, serverStartPatch, SERVER_START_ID } from '../startupEventMapping';

describe('mapStartupEvent (individual log entries)', () => {
  it('maps a download event with progress', () => {
    const entry = mapStartupEvent({
      id: 'model-load-openai--whisper-large-v3',
      category: 'download',
      label: 'Downloading Whisper large-v3...',
      status: 'active',
      progress: 42,
      downloadedSize: '1.2 GB',
      totalSize: '3.1 GB',
    });
    expect(entry).toMatchObject({
      id: 'model-load-openai--whisper-large-v3',
      category: 'download',
      title: 'Downloading Whisper large-v3...',
      status: 'active',
      progress: 42,
      downloadedSize: '1.2 GB',
      totalSize: '3.1 GB',
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
  it('advances the aggregate through known stages', () => {
    const patch = serverStartPatch({
      id: 'lifespan-start',
      category: 'server',
      label: 'Starting server...',
    });
    expect(patch).toMatchObject({
      id: SERVER_START_ID,
      status: 'active',
      progress: 55,
      detail: 'Starting server...',
    });
  });

  it('scales model-load percent into the 65-95 band', () => {
    const patch = serverStartPatch({
      id: 'model-load-x',
      category: 'download',
      label: 'Downloading X...',
      progress: 50,
    });
    expect(patch).toMatchObject({ id: SERVER_START_ID, progress: 80 });
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
      progress: 100,
    });
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
