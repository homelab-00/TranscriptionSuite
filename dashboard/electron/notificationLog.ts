/**
 * NotificationLog - semi-persistent storage for the session notification log.
 *
 * A plain JSON file in userData. "Semi-persistent" means: it survives
 * renderer reloads/crashes WITHIN one app session, but is wiped both at app
 * boot (covers a crashed previous session) and inside gracefulShutdown()
 * (normal quit). Atomic tmp+rename writes mirror watcherManager.ts.
 */

import fs from 'node:fs';
import path from 'node:path';

const FILE_NAME = 'session-notifications.json';

export class NotificationLog {
  private readonly filePath: string;

  constructor(userDataDir: string) {
    this.filePath = path.join(userDataDir, FILE_NAME);
  }

  load(): unknown[] {
    try {
      const data = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      return Array.isArray(data) ? data : [];
    } catch {
      // Missing or corrupt file - a fresh session starts empty.
      return [];
    }
  }

  persist(items: unknown[]): void {
    const tmp = `${this.filePath}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify(items));
      fs.renameSync(tmp, this.filePath);
    } catch (err) {
      console.warn('[NotificationLog] persist failed:', err);
    }
  }

  clear(): void {
    try {
      fs.rmSync(this.filePath, { force: true });
    } catch (err) {
      console.warn('[NotificationLog] clear failed:', err);
    }
  }
}
