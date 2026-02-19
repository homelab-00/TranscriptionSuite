import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { View } from './types';
import { Sidebar } from './components/Sidebar';
import { SessionView } from './components/views/SessionView';
import { NotebookView } from './components/views/NotebookView';
import { ServerView } from './components/views/ServerView';
import { SettingsModal } from './components/views/SettingsModal';
import { AboutModal } from './components/views/AboutModal';
import { Button } from './components/ui/Button';
import { useServerStatus } from './src/hooks/useServerStatus';
import { initApiClient } from './src/api/client';
import { DockerProvider, useDockerContext } from './src/hooks/DockerContext';
import { getConfig, setConfig } from './src/config/store';

type RuntimeProfile = 'gpu' | 'cpu';
type HfTokenDecision = 'unset' | 'provided' | 'skipped';

const HF_TERMS_URL = 'https://huggingface.co/pyannote/speaker-diarization-community-1';

function normalizeHfDecision(value: unknown): HfTokenDecision {
  if (value === 'provided' || value === 'skipped' || value === 'unset') {
    return value;
  }
  return 'unset';
}

const AppInner: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const serverConnection = useServerStatus();
  const docker = useDockerContext();

  // Track clientRunning at app level so Sidebar can derive Session status
  const [clientRunning, setClientRunning] = useState(false);

  const [startupFlowPending, setStartupFlowPending] = useState(false);
  const startupFlowPendingRef = useRef(false);

  const [hfPromptOpen, setHfPromptOpen] = useState(false);
  const [hfTokenDraft, setHfTokenDraft] = useState('');
  const [showHfTokenDraft, setShowHfTokenDraft] = useState(false);
  const hfResolverRef = useRef<
    ((result: { action: 'cancel' | 'skip' | 'provided'; token: string }) => void) | null
  >(null);

  const [firstRunInfoOpen, setFirstRunInfoOpen] = useState(false);
  const firstRunInfoResolverRef = useRef<(() => void) | null>(null);

  const containerLastSeenRef = useRef<boolean | null>(null);

  useEffect(() => {
    void initApiClient();
  }, []);

  const resolveHfPrompt = useCallback(
    (result: { action: 'cancel' | 'skip' | 'provided'; token: string }) => {
      setHfPromptOpen(false);
      setHfTokenDraft('');
      setShowHfTokenDraft(false);
      const resolver = hfResolverRef.current;
      hfResolverRef.current = null;
      resolver?.(result);
    },
    [],
  );

  const requestHfPrompt = useCallback(async (): Promise<{
    action: 'cancel' | 'skip' | 'provided';
    token: string;
  }> => {
    return new Promise((resolve) => {
      hfResolverRef.current = resolve;
      setHfTokenDraft('');
      setShowHfTokenDraft(false);
      setHfPromptOpen(true);
    });
  }, []);

  const requestFirstRunInfo = useCallback(async (): Promise<void> => {
    return new Promise((resolve) => {
      firstRunInfoResolverRef.current = resolve;
      setFirstRunInfoOpen(true);
    });
  }, []);

  const resolveFirstRunInfo = useCallback(() => {
    setFirstRunInfoOpen(false);
    const resolver = firstRunInfoResolverRef.current;
    firstRunInfoResolverRef.current = null;
    resolver?.();
  }, []);

  useEffect(() => {
    return () => {
      if (hfResolverRef.current) {
        hfResolverRef.current({ action: 'cancel', token: '' });
        hfResolverRef.current = null;
      }
      if (firstRunInfoResolverRef.current) {
        firstRunInfoResolverRef.current();
        firstRunInfoResolverRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const storedLastSeen = await getConfig<boolean>('server.containerExistsLastSeen');
      if (cancelled) return;
      const normalizedLastSeen = storedLastSeen === true;
      containerLastSeenRef.current = normalizedLastSeen;
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (docker.loading) return;
    if (containerLastSeenRef.current === null) return;

    const currentExists = docker.container.exists;
    const previousExists = containerLastSeenRef.current;
    if (currentExists === previousExists) return;

    containerLastSeenRef.current = currentExists;
    void setConfig('server.containerExistsLastSeen', currentExists);

    if (previousExists && !currentExists) {
      void setConfig('server.hfTokenDecision', 'unset');
    }
  }, [docker.container.exists, docker.loading]);

  const openExternal = useCallback(async (url: string): Promise<void> => {
    try {
      if (window.electronAPI?.app?.openExternal) {
        await window.electronAPI.app.openExternal(url);
        return;
      }
    } catch {
      // Fall back to browser open in non-Electron mode.
    }

    if (!window.electronAPI) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }, []);

  const startServerWithOnboarding = useCallback(
    async (mode: 'local' | 'remote', runtimeProfile: RuntimeProfile, imageTag?: string) => {
      if (startupFlowPendingRef.current || docker.operating || docker.loading) return;

      startupFlowPendingRef.current = true;
      setStartupFlowPending(true);

      try {
        const shouldRunPrompts = !docker.container.exists;

        const storedTokenRaw = await getConfig<string>('server.hfToken');
        let hfToken = typeof storedTokenRaw === 'string' ? storedTokenRaw.trim() : '';
        let hfDecision = normalizeHfDecision(await getConfig('server.hfTokenDecision'));

        if (shouldRunPrompts) {
          if (hfToken.length > 0) {
            if (hfDecision !== 'provided') {
              hfDecision = 'provided';
              await setConfig('server.hfTokenDecision', hfDecision);
            }
          } else if (hfDecision === 'unset') {
            // Also skip if the .env already has a HUGGINGFACE_TOKEN set
            const envToken = (await (window as any).electronAPI?.docker
              ?.readComposeEnvValue('HUGGINGFACE_TOKEN')
              .catch(() => null)) as string | null | undefined;
            if (envToken) {
              hfToken = envToken;
              hfDecision = 'provided';
              await Promise.all([
                setConfig('server.hfToken', hfToken),
                setConfig('server.hfTokenDecision', hfDecision),
              ]);
            } else {
              const hfPromptResult = await requestHfPrompt();
              if (hfPromptResult.action === 'cancel') return;

              if (hfPromptResult.action === 'provided') {
                hfToken = hfPromptResult.token.trim();
                hfDecision = 'provided';
              } else {
                hfToken = '';
                hfDecision = 'skipped';
              }

              await Promise.all([
                setConfig('server.hfToken', hfToken),
                setConfig('server.hfTokenDecision', hfDecision),
              ]);
            }
          }

          // Check if both data and models volumes are absent — first-ever startup
          const [dataVolExists, modelsVolExists] = await Promise.all([
            (window as any).electronAPI?.docker
              ?.volumeExists('transcriptionsuite-data')
              .catch(() => false) as Promise<boolean>,
            (window as any).electronAPI?.docker
              ?.volumeExists('transcriptionsuite-models')
              .catch(() => false) as Promise<boolean>,
          ]);
          if (!dataVolExists && !modelsVolExists) {
            await requestFirstRunInfo();
          }

          await docker.startContainer(mode, runtimeProfile, undefined, imageTag, hfToken, {
            hfTokenDecision: hfDecision,
          });
          return;
        }

        await docker.startContainer(
          mode,
          runtimeProfile,
          undefined,
          imageTag,
          hfToken || undefined,
        );
      } finally {
        startupFlowPendingRef.current = false;
        setStartupFlowPending(false);
      }
    },
    [docker, requestHfPrompt],
  );

  const renderView = () => {
    switch (currentView) {
      case View.SESSION:
        return (
          <SessionView
            serverConnection={serverConnection}
            clientRunning={clientRunning}
            setClientRunning={setClientRunning}
            onStartServer={startServerWithOnboarding}
            startupFlowPending={startupFlowPending}
          />
        );
      case View.NOTEBOOK:
        return <NotebookView />;
      case View.SERVER:
        return (
          <ServerView
            onStartServer={startServerWithOnboarding}
            startupFlowPending={startupFlowPending}
          />
        );
      default:
        return (
          <SessionView
            serverConnection={serverConnection}
            clientRunning={clientRunning}
            setClientRunning={setClientRunning}
            onStartServer={startServerWithOnboarding}
            startupFlowPending={startupFlowPending}
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
        containerHealth={docker.container.health}
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

      {hfPromptOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() => resolveHfPrompt({ action: 'cancel', token: '' })}
          />
          <div className="relative flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">Optional Diarization Setup</h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-3 text-sm text-slate-300">
                <p>Set up HuggingFace token for speaker diarization?</p>
                <p className="text-slate-400">
                  You can skip this now. Core transcription will still work.
                </p>
                <p className="text-slate-400">
                  If skipped, diarization stays disabled until you add a token.
                </p>
                <p className="text-slate-400">
                  Accept model terms first:{' '}
                  <button
                    type="button"
                    onClick={() => void openExternal(HF_TERMS_URL)}
                    className="text-accent-cyan hover:underline"
                  >
                    {HF_TERMS_URL}
                  </button>
                </p>
                <div className="relative pt-1">
                  <input
                    type={showHfTokenDraft ? 'text' : 'password'}
                    value={hfTokenDraft}
                    onChange={(e) => setHfTokenDraft(e.target.value)}
                    placeholder="hf_xxxxxxxxxxxxxxxxxxxx"
                    className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-10 font-mono text-sm text-white focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowHfTokenDraft((prev) => !prev)}
                    className="absolute top-1/2 right-2 -translate-y-1/2 text-slate-400 transition-colors hover:text-white"
                  >
                    {showHfTokenDraft ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>
            <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button
                variant="ghost"
                onClick={() => resolveHfPrompt({ action: 'cancel', token: '' })}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => resolveHfPrompt({ action: 'skip', token: '' })}
              >
                Skip for now
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  const cleanToken = hfTokenDraft.trim();
                  if (cleanToken) {
                    resolveHfPrompt({ action: 'provided', token: cleanToken });
                  } else {
                    resolveHfPrompt({ action: 'skip', token: '' });
                  }
                }}
              >
                Save Token
              </Button>
            </div>
          </div>
        </div>
      )}

      {firstRunInfoOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={resolveFirstRunInfo}
          />
          <div className="relative flex w-full max-w-sm flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl">
            <div className="flex flex-none items-center border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">First Startup — Please Wait</h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-3 text-sm text-slate-300">
                <p>
                  This is the server's first startup. It needs to download roughly{' '}
                  <span className="font-semibold text-white">10 GB</span> of AI models before it's
                  ready.
                </p>
                <p className="text-slate-400">
                  Expect the server to take up to{' '}
                  <span className="font-semibold text-white">~10 minutes</span> to fully start
                  depending on your internet connection.
                </p>
                <p className="text-slate-400">
                  The app is <span className="font-semibold text-white">not stuck</span> — sit back
                  and let it finish.
                </p>
              </div>
            </div>
            <div className="flex flex-none justify-end border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button variant="primary" onClick={resolveFirstRunInfo}>
                Got it
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const App: React.FC = () => (
  <DockerProvider>
    <AppInner />
  </DockerProvider>
);

export default App;
