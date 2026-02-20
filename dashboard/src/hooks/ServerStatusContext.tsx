/**
 * ServerStatusContext — shared React context for server status polling.
 *
 * Wraps useServerStatus() so App, SessionView, Sidebar, and other
 * components all share a single polling loop instead of each mounting
 * their own interval.
 */

import React, { createContext, useContext } from 'react';
import { useServerStatus, type ServerConnectionInfo } from './useServerStatus';

const ServerStatusCtx = createContext<ServerConnectionInfo | null>(null);

export const ServerStatusProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const status = useServerStatus();
  return <ServerStatusCtx.Provider value={status}>{children}</ServerStatusCtx.Provider>;
};

/**
 * Access the shared server status. Must be used inside <ServerStatusProvider>.
 */
export function useServerStatusContext(): ServerConnectionInfo {
  const ctx = useContext(ServerStatusCtx);
  if (!ctx) throw new Error('useServerStatusContext must be used within <ServerStatusProvider>');
  return ctx;
}
