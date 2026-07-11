import { describe, it, expect } from 'vitest';
import { forceEnableWeeklyUpdatesOnce } from '../updateMigration.js';

function makeStore(initial: Record<string, unknown> = {}) {
  const data = new Map<string, unknown>(Object.entries(initial));
  return {
    get: (k: string) => data.get(k),
    set: (k: string, v: unknown) => {
      data.set(k, v);
    },
    _data: data,
  };
}

describe('forceEnableWeeklyUpdatesOnce', () => {
  it('force-enables weekly checks on first run and sets the flag', () => {
    const store = makeStore({
      'app.updateChecksEnabled': false,
      'app.updateCheckIntervalMode': '24h',
    });
    const ran = forceEnableWeeklyUpdatesOnce(store);
    expect(ran).toBe(true);
    expect(store._data.get('app.updateChecksEnabled')).toBe(true);
    expect(store._data.get('app.updateCheckIntervalMode')).toBe('7d');
    expect(store._data.get('updates.forceOnMigrationDone')).toBe(true);
  });

  it('overrides a user who had explicitly disabled checks (force-on semantics)', () => {
    const store = makeStore({ 'app.updateChecksEnabled': false });
    forceEnableWeeklyUpdatesOnce(store);
    expect(store._data.get('app.updateChecksEnabled')).toBe(true);
  });

  it('is a no-op after it has run once (user choice persists thereafter)', () => {
    const store = makeStore({
      'updates.forceOnMigrationDone': true,
      'app.updateChecksEnabled': false,
    });
    const ran = forceEnableWeeklyUpdatesOnce(store);
    expect(ran).toBe(false);
    expect(store._data.get('app.updateChecksEnabled')).toBe(false);
  });
});
