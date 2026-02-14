import React, { useState } from 'react';
import { View } from './types';
import { Sidebar } from './components/Sidebar';
import { SessionView } from './components/views/SessionView';
import { NotebookView } from './components/views/NotebookView';
import { ServerView } from './components/views/ServerView';
import { SettingsModal } from './components/views/SettingsModal';
import { AboutModal } from './components/views/AboutModal';
import { useServerStatus } from './src/hooks/useServerStatus';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const serverConnection = useServerStatus();

  const renderView = () => {
    switch (currentView) {
      case View.SESSION:
        return <SessionView />;
      case View.NOTEBOOK:
        return <NotebookView />;
      case View.SERVER:
        return <ServerView />;
      default:
        return <SessionView />;
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
        serverStatus={serverConnection.serverStatus}
        clientStatus={serverConnection.clientStatus}
      />

      {/* Main Content Area */}
      <main className="flex-1 relative flex flex-col min-w-0">
        
        {/* Top Gradient Fade for aesthetic scrolling */}
        <div className="absolute top-0 left-0 right-0 h-8 bg-gradient-to-b from-slate-900/10 to-transparent z-10 pointer-events-none"></div>

        {/* Scrollable View Content - Removed p-6 to allow full-width scrolling in Server View */}
        <div className="flex-1 overflow-hidden h-full relative">
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 ease-out h-full w-full">
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

export default App;