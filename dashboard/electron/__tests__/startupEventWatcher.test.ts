// @vitest-environment node

/**
 * P1-DOCK-003 — Startup event parsing from JSONL
 *
 * Tests that StartupEventWatcher correctly parses JSON Lines from a file,
 * handles malformed lines, file truncation, and incremental reads.
 *
 * Uses real temp files for reliable filesystem behavior.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { StartupEventWatcher, type StartupEvent } from '../startupEventWatcher.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

let tmpDir: string;
let eventsFile: string;

function makeEvent(
  overrides: Partial<StartupEvent> & { id: string; category: string; label: string },
): string {
  return JSON.stringify(overrides);
}

/** Wait for the watcher's fs.watch callback to fire after a write. */
async function waitForEvents(ms = 200): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dock003-'));
  eventsFile = path.join(tmpDir, 'startup-events.jsonl');
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

// ─── P1-DOCK-003: Startup Event Parsing ─────────────────────────────────────

describe('[P1] StartupEventWatcher', () => {
  it('parses valid JSONL events and invokes callback', async () => {
    // Write some events before starting the watcher
    const events = [
      makeEvent({
        id: 'bootstrap',
        category: 'bootstrap',
        label: 'Starting',
        status: 'downloading',
      }),
      makeEvent({
        id: 'model-dl',
        category: 'model-download',
        label: 'Whisper Large',
        progress: 45,
      }),
    ];
    fs.writeFileSync(eventsFile, events.join('\n') + '\n');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();

    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    expect(received).toHaveLength(2);
    expect(received[0].id).toBe('bootstrap');
    expect(received[0].category).toBe('bootstrap');
    expect(received[0].label).toBe('Starting');
    expect(received[0].status).toBe('downloading');
    expect(received[1].id).toBe('model-dl');
    expect(received[1].progress).toBe(45);

    watcher.stop();
  });

  it('reads new lines appended after watcher starts', async () => {
    // Start with empty file
    fs.writeFileSync(eventsFile, '');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));

    // Append an event after watcher is watching
    fs.appendFileSync(
      eventsFile,
      makeEvent({ id: 'late', category: 'lifespan', label: 'Ready' }) + '\n',
    );
    await waitForEvents();

    expect(received.some((e) => e.id === 'late')).toBe(true);

    watcher.stop();
  });

  it('skips malformed JSON lines without crashing', async () => {
    const lines = [
      makeEvent({ id: 'good1', category: 'bootstrap', label: 'OK' }),
      'this is not json {{{',
      '{"partial": true}', // Valid JSON but missing required fields
      makeEvent({ id: 'good2', category: 'lifespan', label: 'Done' }),
    ];
    fs.writeFileSync(eventsFile, lines.join('\n') + '\n');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    // Only events with id + category + label should be passed through
    expect(received).toHaveLength(2);
    expect(received[0].id).toBe('good1');
    expect(received[1].id).toBe('good2');

    watcher.stop();
  });

  it('skips empty lines', async () => {
    const content = '\n\n' + makeEvent({ id: 'x', category: 'c', label: 'l' }) + '\n\n';
    fs.writeFileSync(eventsFile, content);

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    expect(received).toHaveLength(1);
    expect(received[0].id).toBe('x');

    watcher.stop();
  });

  it('handles file truncation (container restart) by resetting offset', async () => {
    // Write initial events
    const longLine = makeEvent({
      id: 'initial',
      category: 'bootstrap',
      label: 'First run, lots of content to make this long',
    });
    fs.writeFileSync(eventsFile, longLine + '\n');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    expect(received).toHaveLength(1);
    expect(received[0].id).toBe('initial');

    // Truncate and write shorter content (simulates container restart)
    fs.writeFileSync(
      eventsFile,
      makeEvent({ id: 'restart', category: 'bootstrap', label: 'Second run' }) + '\n',
    );
    await waitForEvents();

    expect(received.some((e) => e.id === 'restart')).toBe(true);

    watcher.stop();
  });

  it('does not duplicate events on repeated reads', async () => {
    fs.writeFileSync(eventsFile, makeEvent({ id: 'once', category: 'c', label: 'l' }) + '\n');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    // Append nothing — just wait again
    await waitForEvents();

    const onceCount = received.filter((e) => e.id === 'once').length;
    expect(onceCount).toBe(1);

    watcher.stop();
  });

  it('all StartupEvent fields are preserved', async () => {
    const full: StartupEvent = {
      id: 'model-dl',
      category: 'model-download',
      label: 'Whisper Large v3',
      status: 'downloading',
      progress: 72,
      totalSize: '2.5GB',
      downloadedSize: '1.8GB',
      detail: 'Downloading from HuggingFace',
      severity: 'info',
      persistent: true,
      phase: 'model-loading',
      syncMode: 'streaming',
      expandableDetail: 'Full stack trace here...',
      durationMs: 45000,
      ts: 1712275200,
    };
    fs.writeFileSync(eventsFile, JSON.stringify(full) + '\n');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    await waitForEvents();

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual(full);

    watcher.stop();
  });

  it('stop() cleans up and prevents further callbacks', async () => {
    fs.writeFileSync(eventsFile, '');

    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();
    watcher.start(eventsFile, (event) => received.push(event));
    watcher.stop();

    // Write after stop — should NOT be received
    fs.appendFileSync(
      eventsFile,
      makeEvent({ id: 'after-stop', category: 'c', label: 'l' }) + '\n',
    );
    await waitForEvents();

    expect(received.filter((e) => e.id === 'after-stop')).toHaveLength(0);
  });

  it('retries when file does not exist yet', async () => {
    // Don't create the file yet
    const received: StartupEvent[] = [];
    const watcher = new StartupEventWatcher();

    // Start watching a file that doesn't exist
    watcher.start(eventsFile, (event) => received.push(event));

    // Wait for retry interval (1s) + buffer
    await new Promise((resolve) => setTimeout(resolve, 300));

    // Now create the file with events
    fs.writeFileSync(
      eventsFile,
      makeEvent({ id: 'delayed', category: 'bootstrap', label: 'Late start' }) + '\n',
    );

    // Wait for retry + read
    await new Promise((resolve) => setTimeout(resolve, 1500));

    expect(received.some((e) => e.id === 'delayed')).toBe(true);

    watcher.stop();
  });
});
