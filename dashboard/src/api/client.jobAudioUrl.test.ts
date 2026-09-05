import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { APIClient } from './client';

// getJobAudioUrl backs the "Save Audio" action: the renderer hands the URL to
// the Electron main process, which streams the WAV to disk. Two properties are
// load-bearing and asserted here - it gates on isBaseUrlConfigured() like its
// getAudioUrl / getExportUrl neighbours, and it never carries the auth token as
// a query param (the token travels as an Authorization header instead, so it
// stays out of any access log).

function installConfigBridge(seed: Record<string, unknown>) {
  (window as any).electronAPI = {
    config: {
      get: vi.fn(async (key: string) => seed[key]),
      set: vi.fn(),
    },
  };
}

describe('APIClient.getJobAudioUrl', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('returns null on a pre-sync client', () => {
    const client = new APIClient();
    expect(client.getJobAudioUrl('job-1')).toBeNull();
  });

  it('returns null after sync when baseUrl is blank-remote', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '',
    });
    const client = new APIClient();
    await client.syncFromConfig();
    expect(client.getJobAudioUrl('job-1')).toBeNull();
  });

  it('returns an absolute URL under the configured base after sync', async () => {
    installConfigBridge({ 'connection.useRemote': false });
    const client = new APIClient();
    await client.syncFromConfig();

    const url = client.getJobAudioUrl('job-1');
    expect(url).not.toBeNull();
    expect(url).toBe(`${client.getBaseUrl()}/api/transcribe/audio/job-1`);
  });

  it('never appends a token query param, even when a token is set', async () => {
    installConfigBridge({ 'connection.useRemote': false });
    const client = new APIClient();
    await client.syncFromConfig();
    client.setAuthToken('secret-token');

    const url = client.getJobAudioUrl('job-1');
    expect(url).not.toBeNull();
    expect(url).not.toContain('?');
    expect(url).not.toContain('secret-token');
  });

  it('URL-encodes the job id', async () => {
    installConfigBridge({ 'connection.useRemote': false });
    const client = new APIClient();
    await client.syncFromConfig();

    expect(client.getJobAudioUrl('a b/c')).toBe(
      `${client.getBaseUrl()}/api/transcribe/audio/a%20b%2Fc`,
    );
  });
});
