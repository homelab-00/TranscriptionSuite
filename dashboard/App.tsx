import React, { useState } from 'react';
import { View } from './types';
import { Sidebar } from './components/Sidebar';
import { SessionView } from './components/views/SessionView';
import { NotebookView } from './components/views/NotebookView';
import { ServerView } from './components/views/ServerView';
import { SettingsModal } from './components/views/SettingsModal';
import { AboutModal } from './components/views/AboutModal';
import { useServerStatus } from './src/hooks/useServerStatus';
import { DockerProvider, useDockerContext } from './src/hooks/DockerContext';

const AppInner: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const serverConnection = useServerStatus();
  const docker = useDockerContext();

  // Track clientRunning at app level so Sidebar can derive Session status
  const [clientRunning, setClientRunning] = useState(false);

  const renderView = () => {
    switch (currentView) {
      case View.SESSION:
        return (
          <SessionView
            serverConnection={serverConnection}
            clientRunning={clientRunning}
            setClientRunning={setClientRunning}
          />
        );
      case View.NOTEBOOK:
        return <NotebookView />;
      case View.SERVER:
        return <ServerView />;
      default:
        return (
          <SessionView
            serverConnection={serverConnection}
            clientRunning={clientRunning}
            setClientRunning={setClientRunning}
          />
        );
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-transparent font-sans text-slate-200">
      {/* Sidebar Navigation */}
      <Sidebar
        currentView={currentView}
        onChangeView={setCurrentView}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenAbout={() => setIsAboutOpen(true)}
        containerRunning={docker.container.running}
        containerExists={docker.container.exists}
        clientRunning={clientRunning}
      />

      {/* Main Content Area */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {/* Top Gradient Fade for aesthetic scrolling */}
        <div className="pointer-events-none absolute top-0 right-0 left-0 z-10 h-8 bg-linear-to-b from-slate-900/10 to-transparent"></div>

        {/* Scrollable View Content - Removed p-6 to allow full-width scrolling in Server View */}
        <div className="relative h-full flex-1 overflow-hidden">
          <div className="animate-in fade-in slide-in-from-bottom-4 h-full w-full duration-500 ease-out">
            {renderView()}
          </div>
        </div>
      </main>

      {/* Modals */}
      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <AboutModal isOpen={isAboutOpen} onClose={() => setIsAboutOpen(false)} />
    </div>
  );
};

const App: React.FC = () => (
  <DockerProvider>
    <AppInner />
  </DockerProvider>
);

export default App;
