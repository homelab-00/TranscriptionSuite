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
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ErrorBoundary } from 'react-error-boundary';
import { Toaster } from 'sonner';
import { ErrorFallback } from './components/ui/ErrorFallback';
import { queryClient } from './src/queryClient';
import { useServerStatus } from './src/hooks/useServerStatus';
import { initApiClient } from './src/api/client';
import { DockerProvider, useDockerContext } from './src/hooks/DockerContext';
import { getConfig, setConfig } from './src/config/store';
import { useLiveMode } from './src/hooks/useLiveMode';
import { isNemoModel, isVibeVoiceASRModel } from './src/services/modelCapabilities';

type RuntimeProfile = 'gpu' | 'cpu';
type HfTokenDecision = 'unset' | 'provided' | 'skipped';
type OptionalInstallDecision = 'unset' | 'enabled' | 'skipped';
type OptionalDependencyPromptMode = 'optional' | 'required';
type OptionalDependencyBootstrapStatus = {
  source: 'runtime-volume-bootstrap-status';
  nemo?: { available: boolean; reason?: string };
  vibevoiceAsr?: { available: boolean; reason?: string };
} | null;

const HF_TERMS_URL = 'https://huggingface.co/pyannote/speaker-diarization-community-1';
function normalizeHfDecision(value: unknown): HfTokenDecision {
  if (value === 'provided' || value === 'skipped' || value === 'unset') {
    return value;
  }
  return 'unset';
}

function normalizeOptionalInstallDecision(value: unknown): OptionalInstallDecision {
  if (value === 'enabled' || value === 'skipped' || value === 'unset') {
    return value;
  }
  return 'unset';
}

function isComposeEnvFlagEnabled(value: string | null | undefined): boolean {
  return (value ?? '').trim().toLowerCase() === 'true';
}

const AppInner: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const serverConnection = useServerStatus();
  const docker = useDockerContext();

  // Track clientRunning at app level so Sidebar can derive Session status
  const [clientRunning, setClientRunning] = useState(false);

  // Live mode lifted to App level so state survives tab switches
  const live = useLiveMode();

  // Lifted upload/import status so tray sync (in SessionView) can reflect it
  const [isUploading, setIsUploading] = useState(false);

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

  const [nemoPromptOpen, setNemoPromptOpen] = useState(false);
  const [nemoPromptMode, setNemoPromptMode] = useState<OptionalDependencyPromptMode>('optional');
  const nemoResolverRef = useRef<((install: boolean | null) => void) | null>(null);
  const [vibevoicePromptOpen, setVibevoicePromptOpen] = useState(false);
  const [vibevoicePromptMode, setVibevoicePromptMode] =
    useState<OptionalDependencyPromptMode>('optional');
  const vibevoiceResolverRef = useRef<((install: boolean | null) => void) | null>(null);

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

  const requestNemoPrompt = useCallback(
    async (mode: OptionalDependencyPromptMode): Promise<boolean | null> => {
      return new Promise((resolve) => {
        nemoResolverRef.current = resolve;
        setNemoPromptMode(mode);
        setNemoPromptOpen(true);
      });
    },
    [],
  );

  const resolveNemoPrompt = useCallback((install: boolean | null) => {
    setNemoPromptOpen(false);
    setNemoPromptMode('optional');
    const resolver = nemoResolverRef.current;
    nemoResolverRef.current = null;
    resolver?.(install);
  }, []);

  const requestVibeVoicePrompt = useCallback(
    async (mode: OptionalDependencyPromptMode): Promise<boolean | null> => {
      return new Promise((resolve) => {
        vibevoiceResolverRef.current = resolve;
        setVibevoicePromptMode(mode);
        setVibevoicePromptOpen(true);
      });
    },
    [],
  );

  const resolveVibeVoicePrompt = useCallback((install: boolean | null) => {
    setVibevoicePromptOpen(false);
    setVibevoicePromptMode('optional');
    const resolver = vibevoiceResolverRef.current;
    vibevoiceResolverRef.current = null;
    resolver?.(install);
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
      if (nemoResolverRef.current) {
        nemoResolverRef.current(null);
        nemoResolverRef.current = null;
      }
      if (vibevoiceResolverRef.current) {
        vibevoiceResolverRef.current(null);
        vibevoiceResolverRef.current = null;
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
      void setConfig('server.nemoDecision', 'unset');
      void setConfig('server.vibevoiceAsrDecision', 'unset');
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
    async (
      mode: 'local' | 'remote',
      runtimeProfile: RuntimeProfile,
      imageTag?: string,
      models?: {
        mainTranscriberModel?: string;
        liveTranscriberModel?: string;
        diarizationModel?: string;
      },
    ) => {
      if (startupFlowPendingRef.current || docker.operating || docker.loading) return;

      startupFlowPendingRef.current = true;
      setStartupFlowPending(true);

      try {
        const shouldRunPrompts = !docker.container.exists;
        const dockerApi = (window as any).electronAPI?.docker;

        // Check if the runtime volume exists. If missing (e.g. wiped volumes, fresh install),
        // treat as first-start so optional install prompts are shown even when the container
        // already exists.
        const runtimeVolumeExists: boolean = dockerApi?.volumeExists
          ? await (dockerApi.volumeExists('transcriptionsuite-runtime') as Promise<boolean>).catch(
              () => true,
            )
          : true;
        const runtimeVolumeMissing = !runtimeVolumeExists;

        let optionalDependencyBootstrapStatusPromise: Promise<OptionalDependencyBootstrapStatus> | null =
          null;

        const getOptionalDependencyBootstrapStatus =
          async (): Promise<OptionalDependencyBootstrapStatus> => {
            if (!optionalDependencyBootstrapStatusPromise) {
              optionalDependencyBootstrapStatusPromise =
                dockerApi?.readOptionalDependencyBootstrapStatus
                  ? (dockerApi
                      .readOptionalDependencyBootstrapStatus()
                      .catch(() => null) as Promise<OptionalDependencyBootstrapStatus>)
                  : Promise.resolve(null);
            }
            return optionalDependencyBootstrapStatusPromise;
          };

        const storedTokenRaw = await getConfig<string>('server.hfToken');
        let hfToken = typeof storedTokenRaw === 'string' ? storedTokenRaw.trim() : '';
        let hfDecision = normalizeHfDecision(await getConfig('server.hfTokenDecision'));

        const envMainModel = (await dockerApi
          ?.readComposeEnvValue('MAIN_TRANSCRIBER_MODEL')
          .catch(() => null)) as string | null | undefined;
        const explicitMainModel =
          typeof models?.mainTranscriberModel === 'string'
            ? models.mainTranscriberModel.trim()
            : undefined;
        const selectedMainModel =
          explicitMainModel !== undefined ? explicitMainModel : (envMainModel ?? '').trim();
        const selectedRequiresNemo = isNemoModel(selectedMainModel);
        const selectedRequiresVibeVoice = isVibeVoiceASRModel(selectedMainModel);

        const resolveNemoInstallPreference = async ({
          firstStart,
          requiredBySelectedModel,
        }: {
          firstStart: boolean;
          requiredBySelectedModel: boolean;
        }): Promise<boolean | undefined | null> => {
          const envNemo = (await dockerApi
            ?.readComposeEnvValue('INSTALL_NEMO')
            .catch(() => null)) as string | null | undefined;
          const storedDecision = normalizeOptionalInstallDecision(
            await getConfig('server.nemoDecision'),
          );

          if (isComposeEnvFlagEnabled(envNemo)) {
            if (storedDecision !== 'enabled') {
              await setConfig('server.nemoDecision', 'enabled');
            }
            return true;
          }

          // If the runtime deps volume already reports NeMo as available, skip prompting
          // and avoid forcing INSTALL_NEMO=true again.
          if ((await getOptionalDependencyBootstrapStatus())?.nemo?.available === true) {
            return undefined;
          }

          const promptMode: OptionalDependencyPromptMode | null = requiredBySelectedModel
            ? 'required'
            : firstStart
              ? 'optional'
              : null;
          if (!promptMode) {
            return undefined;
          }

          if (storedDecision === 'enabled') {
            return true;
          }
          if (promptMode === 'optional' && storedDecision === 'skipped') {
            return false;
          }

          const nemoResult = await requestNemoPrompt(promptMode);
          if (nemoResult === null) return null;

          await setConfig('server.nemoDecision', nemoResult ? 'enabled' : 'skipped');
          return nemoResult;
        };

        const resolveVibeVoiceInstallPreference = async ({
          firstStart,
          requiredBySelectedModel,
        }: {
          firstStart: boolean;
          requiredBySelectedModel: boolean;
        }): Promise<boolean | undefined | null> => {
          const envVibeVoice = (await dockerApi
            ?.readComposeEnvValue('INSTALL_VIBEVOICE_ASR')
            .catch(() => null)) as string | null | undefined;
          const storedDecision = normalizeOptionalInstallDecision(
            await getConfig('server.vibevoiceAsrDecision'),
          );

          if (isComposeEnvFlagEnabled(envVibeVoice)) {
            if (storedDecision !== 'enabled') {
              await setConfig('server.vibevoiceAsrDecision', 'enabled');
            }
            return true;
          }

          // Same as NeMo: treat persisted runtime bootstrap availability as installed.
          if ((await getOptionalDependencyBootstrapStatus())?.vibevoiceAsr?.available === true) {
            return undefined;
          }

          const promptMode: OptionalDependencyPromptMode | null = requiredBySelectedModel
            ? 'required'
            : firstStart
              ? 'optional'
              : null;
          if (!promptMode) {
            return undefined;
          }

          if (storedDecision === 'enabled') {
            return true;
          }
          if (promptMode === 'optional' && storedDecision === 'skipped') {
            return false;
          }

          const vibeVoiceResult = await requestVibeVoicePrompt(promptMode);
          if (vibeVoiceResult === null) return null;

          await setConfig('server.vibevoiceAsrDecision', vibeVoiceResult ? 'enabled' : 'skipped');
          return vibeVoiceResult;
        };

        if (shouldRunPrompts) {
          if (hfToken.length > 0) {
            if (hfDecision !== 'provided') {
              hfDecision = 'provided';
              await setConfig('server.hfTokenDecision', hfDecision);
            }
          } else {
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

          const installNemo = await resolveNemoInstallPreference({
            firstStart: true,
            requiredBySelectedModel: selectedRequiresNemo,
          });
          if (installNemo === null) return; // cancelled

          // Keep VibeVoice prompt immediately after NeMo in the first-start onboarding flow.
          const installVibeVoiceAsr = await resolveVibeVoiceInstallPreference({
            firstStart: true,
            requiredBySelectedModel: selectedRequiresVibeVoice,
          });
          if (installVibeVoiceAsr === null) return; // cancelled

          // Check if both data and models volumes are absent — first-ever startup
          const [dataVolExists, modelsVolExists] = await Promise.all([
            dockerApi
              ?.volumeExists('transcriptionsuite-data')
              .catch(() => false) as Promise<boolean>,
            dockerApi
              ?.volumeExists('transcriptionsuite-models')
              .catch(() => false) as Promise<boolean>,
          ]);
          if (!dataVolExists && !modelsVolExists) {
            await requestFirstRunInfo();
          }

          await docker.startContainer(mode, runtimeProfile, undefined, imageTag, hfToken, {
            hfTokenDecision: hfDecision,
            installNemo: installNemo ?? undefined,
            installVibeVoiceAsr: installVibeVoiceAsr ?? undefined,
            ...models,
          });
          return;
        }

        const installNemo = await resolveNemoInstallPreference({
          firstStart: runtimeVolumeMissing,
          requiredBySelectedModel: selectedRequiresNemo,
        });
        if (installNemo === null) return; // cancelled

        const installVibeVoiceAsr = await resolveVibeVoiceInstallPreference({
          firstStart: runtimeVolumeMissing,
          requiredBySelectedModel: selectedRequiresVibeVoice,
        });
        if (installVibeVoiceAsr === null) return; // cancelled

        await docker.startContainer(
          mode,
          runtimeProfile,
          undefined,
          imageTag,
          hfToken || undefined,
          {
            ...(models ?? {}),
            installNemo: installNemo ?? undefined,
            installVibeVoiceAsr: installVibeVoiceAsr ?? undefined,
          },
        );
      } finally {
        startupFlowPendingRef.current = false;
        setStartupFlowPending(false);
      }
    },
    [docker, requestHfPrompt, requestNemoPrompt, requestVibeVoicePrompt],
  );

  const renderView = () => {
    switch (currentView) {
      case View.SESSION:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <SessionView
              serverConnection={serverConnection}
              clientRunning={clientRunning}
              setClientRunning={setClientRunning}
              onStartServer={startServerWithOnboarding}
              startupFlowPending={startupFlowPending}
              isUploading={isUploading}
              live={live}
            />
          </ErrorBoundary>
        );
      case View.NOTEBOOK:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <NotebookView onUploadingChange={setIsUploading} />
          </ErrorBoundary>
        );
      case View.SERVER:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <ServerView
              onStartServer={startServerWithOnboarding}
              startupFlowPending={startupFlowPending}
            />
          </ErrorBoundary>
        );
      default:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <SessionView
              serverConnection={serverConnection}
              clientRunning={clientRunning}
              setClientRunning={setClientRunning}
              onStartServer={startServerWithOnboarding}
              startupFlowPending={startupFlowPending}
              isUploading={isUploading}
              live={live}
            />
          </ErrorBoundary>
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

      {nemoPromptOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() => resolveNemoPrompt(null)}
          />
          <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">
                {nemoPromptMode === 'required'
                  ? 'NVIDIA NeMo Required'
                  : 'Optional NVIDIA NeMo Setup'}
              </h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-3 text-sm text-slate-300">
                {nemoPromptMode === 'required' ? (
                  <p>
                    The selected main transcriber model requires NVIDIA NeMo support (Parakeet /
                    Canary). Install NeMo to continue starting the server.
                  </p>
                ) : (
                  <p>Install NVIDIA NeMo toolkit for Parakeet and Canary models?</p>
                )}
                <p className="text-slate-400">
                  Parakeet and Canary models offer high-accuracy multilingual transcription and
                  translation as an alternative to Whisper. This is a large optional dependency (~2
                  GB+).
                </p>
                {nemoPromptMode === 'required' ? (
                  <p className="text-slate-400">
                    Cancel stops startup. Install NeMo to continue with the selected model.
                  </p>
                ) : (
                  <p className="text-slate-400">
                    If skipped, Whisper models will still work normally. You can enable this later
                    by setting{' '}
                    <code className="rounded bg-white/10 px-1 py-0.5 text-xs">
                      INSTALL_NEMO=true
                    </code>{' '}
                    in your Docker environment.
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-none flex-nowrap items-center justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button
                variant="ghost"
                className="shrink-0 whitespace-nowrap"
                onClick={() => resolveNemoPrompt(null)}
              >
                Cancel
              </Button>
              {nemoPromptMode === 'optional' && (
                <Button
                  variant="danger"
                  className="shrink-0 whitespace-nowrap"
                  onClick={() => resolveNemoPrompt(false)}
                >
                  Skip for now
                </Button>
              )}
              <Button
                variant="primary"
                className="shrink-0 whitespace-nowrap"
                onClick={() => resolveNemoPrompt(true)}
              >
                Install NeMo
              </Button>
            </div>
          </div>
        </div>
      )}

      {vibevoicePromptOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() => resolveVibeVoicePrompt(null)}
          />
          <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">
                {vibevoicePromptMode === 'required'
                  ? 'VibeVoice-ASR Support Required'
                  : 'Optional VibeVoice-ASR Setup'}
              </h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-3 text-sm text-slate-300">
                {vibevoicePromptMode === 'required' ? (
                  <p>
                    The selected main transcriber model uses the VibeVoice-ASR backend and requires
                    VibeVoice-ASR support. Install it to continue starting the server.
                  </p>
                ) : (
                  <p>
                    Install the optional VibeVoice-ASR dependency for the selected VibeVoice-ASR
                    model?
                  </p>
                )}
                <p className="text-slate-400">
                  This is required to use the VibeVoice-ASR transcription backend. It installs an
                  additional optional dependency into the server runtime.
                </p>
                {vibevoicePromptMode === 'required' ? (
                  <p className="text-slate-400">
                    Cancel stops startup. Install VibeVoice-ASR support to continue with the
                    selected model.
                  </p>
                ) : (
                  <p className="text-slate-400">
                    If skipped, the server can still start, but VibeVoice-ASR will not load until
                    you enable{' '}
                    <code className="rounded bg-white/10 px-1 py-0.5 text-xs">
                      INSTALL_VIBEVOICE_ASR=true
                    </code>{' '}
                    and restart.
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-none flex-nowrap items-center justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button
                variant="ghost"
                className="shrink-0 whitespace-nowrap"
                onClick={() => resolveVibeVoicePrompt(null)}
              >
                Cancel
              </Button>
              {vibevoicePromptMode === 'optional' && (
                <Button
                  variant="danger"
                  className="shrink-0 whitespace-nowrap"
                  onClick={() => resolveVibeVoicePrompt(false)}
                >
                  Skip for now
                </Button>
              )}
              <Button
                variant="primary"
                className="shrink-0 whitespace-nowrap"
                onClick={() => resolveVibeVoicePrompt(true)}
              >
                Install VibeVoice-ASR
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
  <QueryClientProvider client={queryClient}>
    <DockerProvider>
      <AppInner />
    </DockerProvider>
    <Toaster position="bottom-right" theme="dark" richColors />
    <ReactQueryDevtools initialIsOpen={false} />
  </QueryClientProvider>
);

export default App;
