// @vitest-environment node

/**
 * Unit tests for the pure parseDiagnosticLog() helper. Exercises the row
 * regex, the suggested-command extractor, the canonical Summary block, and
 * the row-count fallback used when no Summary block is present.
 */

import { describe, it, expect, vi } from 'vitest';

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => `/tmp/mock-${name}`,
    setPath: vi.fn(),
  },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

import { parseDiagnosticLog } from '../dockerManager.js';

describe('parseDiagnosticLog', () => {
  it('parses the all-PASS happy path summary block and emits no issues', () => {
    const log = [
      '[PASS] #1  nvidia-smi present                                 driver=595.58.03',
      '[PASS] #2  nvidia-ctk installed                               NVIDIA Container Toolkit CLI version 1.19.0',
      '',
      'PASS: 9   WARN: 0   FAIL: 0',
      '',
      'RESULT: All checks passed.',
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.parsed).toBe(true);
    expect(result.passCount).toBe(9);
    expect(result.warnCount).toBe(0);
    expect(result.failCount).toBe(0);
    expect(result.issues).toEqual([]);
  });

  it('extracts the stale-CDI WARN row and its regenerate command (real user repro)', () => {
    const log = [
      '[PASS] #3  CDI spec at /etc/cdi/nvidia.yaml                   size=21907B mtime=2026-04-16 21:58:05 +0300',
      '[WARN] #4  CDI spec vs driver mtime                           CDI spec is older than driver modules — regenerate with: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
      '',
      'PASS: 9   WARN: 1   FAIL: 0',
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.warnCount).toBe(1);
    expect(result.issues).toHaveLength(1);
    const [issue] = result.issues;
    expect(issue.status).toBe('WARN');
    expect(issue.checkNumber).toBe(4);
    expect(issue.title).toBe('CDI spec vs driver mtime');
    expect(issue.detail).toContain('CDI spec is older than driver modules');
    expect(issue.suggestedCommand).toBe(
      'sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
    );
  });

  it('extracts a "fix:" command and trims trailing parentheticals', () => {
    const log = [
      '[FAIL] #5  /dev/char NVIDIA symlinks                          missing — fix: sudo nvidia-ctk system create-dev-char-symlinks --create-all (also add udev rule per nvidia-container-toolkit issue #48)',
      'PASS: 8   WARN: 0   FAIL: 1',
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.failCount).toBe(1);
    expect(result.issues[0].status).toBe('FAIL');
    expect(result.issues[0].suggestedCommand).toBe(
      'sudo nvidia-ctk system create-dev-char-symlinks --create-all',
    );
  });

  it('surfaces multiple WARN/FAIL rows and skips PASS/INFO rows', () => {
    const log = [
      '[PASS] #1  nvidia-smi present                                 driver=595.58.03',
      '[INFO] #7  Docker daemon.json                                 no daemon.json present',
      '[WARN] #4  CDI spec vs driver mtime                           older — regenerate with: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
      '[FAIL] #6  module nvidia_uvm loaded                           fix: sudo modprobe nvidia_uvm',
      'PASS: 7   WARN: 1   FAIL: 1',
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.issues.map((i) => i.checkNumber)).toEqual([4, 6]);
    expect(result.issues.map((i) => i.status)).toEqual(['WARN', 'FAIL']);
    expect(result.issues[0].suggestedCommand).toContain('nvidia-ctk cdi generate');
    expect(result.issues[1].suggestedCommand).toBe('sudo modprobe nvidia_uvm');
  });

  it('keeps the row but leaves suggestedCommand undefined when no fix-pattern is present', () => {
    const log = [
      '[WARN] #5  /dev/char NVIDIA symlinks                          /dev/char does not exist on this host',
      'PASS: 10   WARN: 1   FAIL: 0',
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.issues).toHaveLength(1);
    expect(result.issues[0].suggestedCommand).toBeUndefined();
    expect(result.issues[0].detail).toBe('/dev/char does not exist on this host');
  });

  it('falls back to row-counting and parsed=false when the Summary block is missing', () => {
    const log = [
      '[PASS] #1  nvidia-smi present                                 driver=595.58.03',
      '[WARN] #4  CDI spec vs driver mtime                           older — regenerate with: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml',
      '[FAIL] #6  module nvidia_uvm loaded                           fix: sudo modprobe nvidia_uvm',
      // (no PASS/WARN/FAIL summary line)
    ].join('\n');

    const result = parseDiagnosticLog(log);

    expect(result.parsed).toBe(false);
    expect(result.passCount).toBe(1);
    expect(result.warnCount).toBe(1);
    expect(result.failCount).toBe(1);
    expect(result.issues).toHaveLength(2);
  });

  it('handles a completely empty log without throwing', () => {
    const result = parseDiagnosticLog('');
    expect(result).toEqual({
      passCount: 0,
      warnCount: 0,
      failCount: 0,
      issues: [],
      parsed: false,
    });
  });

  it('parses titles that contain spaces (regression for lazy-title regex bug)', () => {
    // Multi-word titles must not be split at the first internal space.
    // The %-50s budget guarantees ≥2 spaces between title and detail.
    const log = [
      '[WARN] #5  /dev/char NVIDIA symlinks                          /dev/char does not exist on this host',
    ].join('\n');
    const result = parseDiagnosticLog(log);
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0].title).toBe('/dev/char NVIDIA symlinks');
    expect(result.issues[0].detail).toBe('/dev/char does not exist on this host');
  });
});
