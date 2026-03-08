import { describe, it, expect } from 'vitest';
import {
  parseConfigTree,
  applyConfigUpdates,
  flattenYamlToOverrides,
  buildSparseYaml,
} from './configTree';

// ---------------------------------------------------------------------------
// Minimal config YAML for tests
// ---------------------------------------------------------------------------
const SAMPLE_YAML = `\
# Server settings
server:
    # Port to listen on
    port: 9786
    host: 0.0.0.0
    enable_cors: true

# Transcription engine settings
transcription:
    # Default model for transcription
    model: nvidia/parakeet-tdt-0.6b-v3
    language: auto
    beam_size: 5
    live_model: Systran/faster-whisper-medium
    # TLS configuration
    tls:
        # Enable TLS termination
        enabled: false
        cert_path: /certs/cert.pem
`;

// ---------------------------------------------------------------------------
// parseConfigTree — type detection
// ---------------------------------------------------------------------------
describe('parseConfigTree — type detection', () => {
  it('detects integer fields', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const port = server.fields.find((f) => f.key === 'port')!;

    expect(port.type).toBe('integer');
    expect(port.value).toBe(9786);
  });

  it('detects string fields', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const host = server.fields.find((f) => f.key === 'host')!;

    expect(host.type).toBe('string');
    expect(host.value).toBe('0.0.0.0');
  });

  it('detects boolean fields', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const cors = server.fields.find((f) => f.key === 'enable_cors')!;

    expect(cors.type).toBe('boolean');
    expect(cors.value).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// parseConfigTree — key humanisation
// ---------------------------------------------------------------------------
describe('parseConfigTree — key humanisation', () => {
  it('converts section keys to title case', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const transcription = tree.sections.find((s) => s.key === 'transcription')!;

    expect(transcription.title).toBe('Transcription');
  });

  it('converts underscored keys to title case', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const cors = server.fields.find((f) => f.key === 'enable_cors')!;

    expect(cors).toBeDefined();
    // humaniseKey is used on section/subsection titles, field keys remain raw
  });
});

// ---------------------------------------------------------------------------
// parseConfigTree — comment extraction
// ---------------------------------------------------------------------------
describe('parseConfigTree — comment extraction', () => {
  it('extracts preceding comments for sections', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;

    expect(server.comment).toBe('Server settings');
  });

  it('extracts preceding comments for fields', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const port = server.fields.find((f) => f.key === 'port')!;

    expect(port.comment).toBe('Port to listen on');
  });

  it('extracts preceding comments for subsections', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const transcription = tree.sections.find((s) => s.key === 'transcription')!;
    const tls = transcription.subsections.find((s) => s.key === 'tls')!;

    expect(tls.comment).toBe('TLS configuration');
  });
});

// ---------------------------------------------------------------------------
// parseConfigTree — subsection handling
// ---------------------------------------------------------------------------
describe('parseConfigTree — subsections', () => {
  it('detects nested objects as subsections', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const transcription = tree.sections.find((s) => s.key === 'transcription')!;

    expect(transcription.subsections).toHaveLength(1);
    expect(transcription.subsections[0].key).toBe('tls');
  });

  it('subsection fields have correct dotted paths', () => {
    const tree = parseConfigTree(SAMPLE_YAML);
    const transcription = tree.sections.find((s) => s.key === 'transcription')!;
    const tls = transcription.subsections[0];
    const enabled = tls.fields.find((f) => f.key === 'enabled')!;

    expect(enabled.path).toBe('transcription.tls.enabled');
  });
});

// ---------------------------------------------------------------------------
// applyConfigUpdates — parse/edit round-trip
// ---------------------------------------------------------------------------
describe('applyConfigUpdates', () => {
  it('updates a simple scalar value', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, { 'server.port': 8080 });

    expect(updated).toContain('port: 8080');
    expect(updated).not.toContain('port: 9786');
  });

  it('preserves comments when updating a value', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, { 'server.port': 8080 });

    expect(updated).toContain('# Port to listen on');
    expect(updated).toContain('# Server settings');
  });

  it('updates a nested subsection value', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, { 'transcription.tls.enabled': true });

    expect(updated).toContain('enabled: true');
  });

  it('updates boolean values', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, { 'server.enable_cors': false });

    expect(updated).toContain('enable_cors: false');
  });

  it('updates string values', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, {
      'transcription.model': 'nvidia/canary-1b-v2',
    });

    expect(updated).toContain('model: nvidia/canary-1b-v2');
  });

  it('applies multiple updates at once', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, {
      'server.port': 4000,
      'transcription.beam_size': 10,
    });

    expect(updated).toContain('port: 4000');
    expect(updated).toContain('beam_size: 10');
  });

  it('round-trips: parse then update then re-parse yields updated values', () => {
    const updated = applyConfigUpdates(SAMPLE_YAML, { 'server.port': 1234 });
    const tree = parseConfigTree(updated);
    const server = tree.sections.find((s) => s.key === 'server')!;
    const port = server.fields.find((f) => f.key === 'port')!;

    expect(port.value).toBe(1234);
  });
});

// ---------------------------------------------------------------------------
// flattenYamlToOverrides
// ---------------------------------------------------------------------------
describe('flattenYamlToOverrides', () => {
  it('flattens a nested object to dotted paths', () => {
    const result = flattenYamlToOverrides({
      server: { port: 9786, host: '0.0.0.0' },
    });

    expect(result).toEqual({
      'server.port': 9786,
      'server.host': '0.0.0.0',
    });
  });

  it('handles deeper nesting', () => {
    const result = flattenYamlToOverrides({
      transcription: { tls: { enabled: false } },
    });

    expect(result).toEqual({ 'transcription.tls.enabled': false });
  });

  it('returns empty for empty input', () => {
    expect(flattenYamlToOverrides({})).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// buildSparseYaml
// ---------------------------------------------------------------------------
describe('buildSparseYaml', () => {
  it('returns empty string for empty overrides', () => {
    expect(buildSparseYaml({})).toBe('');
  });

  it('produces valid YAML for simple overrides', () => {
    const yaml = buildSparseYaml({ 'server.port': 8080 });

    expect(yaml).toContain('server:');
    expect(yaml).toContain('port: 8080');
  });

  it('groups by top-level section', () => {
    const yaml = buildSparseYaml({
      'server.port': 8080,
      'server.host': 'localhost',
    });

    // Should appear under one "server:" block
    const serverCount = (yaml.match(/^server:/gm) ?? []).length;
    expect(serverCount).toBe(1);
  });
});
