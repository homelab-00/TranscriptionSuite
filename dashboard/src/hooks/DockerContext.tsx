/**
 * DockerContext — shared React context for Docker state.
 *
 * Wraps the useDocker() hook so SessionView, ServerView, and Sidebar
 * all share a single instance of Docker state with one poll interval.
 */

import React, { createContext, useContext } from 'react';
import { useDocker, type UseDockerReturn } from './useDocker';

const DockerContext = createContext<UseDockerReturn | null>(null);

export const DockerProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const docker = useDocker();
  return <DockerContext.Provider value={docker}>{children}</DockerContext.Provider>;
};

/**
 * Access the shared Docker state. Must be used inside <DockerProvider>.
 */
export function useDockerContext(): UseDockerReturn {
  const ctx = useContext(DockerContext);
  if (!ctx) throw new Error('useDockerContext must be used within <DockerProvider>');
  return ctx;
}
