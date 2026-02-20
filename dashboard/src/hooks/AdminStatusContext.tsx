/**
 * AdminStatusContext — shared React context for admin status polling.
 *
 * Wraps useAdminStatus() so SessionView, ServerView, and SettingsModal
 * all share a single polling loop instead of each mounting their own interval.
 */

import React, { createContext, useContext } from 'react';
import { useAdminStatus, type AdminStatusState } from './useAdminStatus';

const AdminStatusCtx = createContext<AdminStatusState | null>(null);

export const AdminStatusProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const admin = useAdminStatus();
  return <AdminStatusCtx.Provider value={admin}>{children}</AdminStatusCtx.Provider>;
};

/**
 * Access the shared admin status. Must be used inside <AdminStatusProvider>.
 */
export function useAdminStatusContext(): AdminStatusState {
  const ctx = useContext(AdminStatusCtx);
  if (!ctx) throw new Error('useAdminStatusContext must be used within <AdminStatusProvider>');
  return ctx;
}
