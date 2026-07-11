/**
 * updateMigration — one-shot "force-on" migration for the default-on weekly
 * update-checks rollout. electron-store defaults only fill ABSENT keys, so a
 * user who explicitly disabled checks keeps that value; the product decision
 * is to force weekly checks ON for everyone exactly once, after which the
 * user's own toggle is respected permanently. The `forceOnMigrationDone`
 * boolean sentinel is required because config.get never returns undefined for
 * a defaulted key, so key-absence is not a usable trigger.
 */
export interface MigratableStore {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
}

/**
 * Returns true if the migration ran this call, false if it was already done.
 */
export function forceEnableWeeklyUpdatesOnce(store: MigratableStore): boolean {
  if (store.get('updates.forceOnMigrationDone') === true) return false;
  store.set('app.updateChecksEnabled', true);
  store.set('app.updateCheckIntervalMode', '7d');
  store.set('updates.forceOnMigrationDone', true);
  return true;
}
