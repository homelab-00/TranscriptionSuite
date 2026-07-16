import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { NotificationLog } from '../notificationLog';

function makeDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'notif-log-'));
}

describe('NotificationLog', () => {
  it('round-trips a persist + load', () => {
    const log = new NotificationLog(makeDir());
    const items = [{ entryId: 'a#1', id: 'a', title: 'Hello' }];
    log.persist(items);
    expect(log.load()).toEqual(items);
  });

  it('returns an empty array when the file is missing', () => {
    const log = new NotificationLog(makeDir());
    expect(log.load()).toEqual([]);
  });

  it('returns an empty array when the file is corrupt', () => {
    const dir = makeDir();
    fs.writeFileSync(path.join(dir, 'session-notifications.json'), '{not json');
    const log = new NotificationLog(dir);
    expect(log.load()).toEqual([]);
  });

  it('clear removes the file and is idempotent', () => {
    const dir = makeDir();
    const log = new NotificationLog(dir);
    log.persist([{ id: 'x' }]);
    log.clear();
    expect(fs.existsSync(path.join(dir, 'session-notifications.json'))).toBe(false);
    log.clear(); // second call must not throw
    expect(log.load()).toEqual([]);
  });
});
