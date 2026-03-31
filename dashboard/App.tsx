import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { View, NotebookTab, SessionTab, LogsTab } from './types';
import { Sidebar } from './components/Sidebar';
import { SessionView } from './components/views/SessionView';
import { NotebookView } from './components/views/NotebookView';
import { ServerView } from './components/views/ServerView';
import { LogsView } from './components/views/LogsView';
import { ModelManagerView } from './components/views/ModelManagerView';
import { SettingsModal } from './components/views/SettingsModal';
import { AboutModal } from './components/views/AboutModal';
import { BugReportModal } from './components/views/BugReportModal';
import { StarPopupModal } from './components/views/StarPopupModal';
import { Button } from './components/ui/Button';
import { CustomSelect } from './components/ui/CustomSelect';
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
import { useImportQueueStore, selectIsUploading } from './src/stores/importQueueStore';
import { QueuePausedBanner } from './components/ui/QueuePausedBanner';
import { DownloadNotifications } from './components/ui/DownloadNotifications';
import { useStarPopup } from './src/hooks/useStarPopup';
import { useServerEventReactor } from './src/hooks/useServerEventReactor';
import { useAuthTokenSync } from './src/hooks/useAuthTokenSync';
import {
  MAIN_RECOMMENDED_MODEL,
  LIVE_RECOMMENDED_MODEL,
  DISABLED_MODEL_SENTINEL,
  ONBOARDING_MAIN_MODEL_OPTIONS,
  ONBOARDING_LIVE_MODEL_OPTIONS,
  OptionalDependencyBootstrapStatus,
  computeMissingModelFamilies,
  toInstallFlagPatch,
  familyDisplayName,
  mapBackendModelToUiSelection,
  resolveMainModelSelectionValue,
  resolveLiveModelSelectionValue,
  toBackendModelEnvValue,
} from './src/services/modelSelection';

type RuntimeProfile = 'gpu' | 'cpu' | 'vulkan';
type HfTokenDecision = 'unset' | 'provided' | 'skipped';
type MissingFamily = 'whisper' | 'nemo' | 'vibevoice';

const HF_TERMS_URL = 'https://huggingface.co/pyannote/speaker-diarization-community-1';

function normalizeHfDecision(value: unknown): HfTokenDecision {
  if (value === 'provided' || value === 'skipped' || value === 'unset') {
    return value;
  }
  return 'unset';
}

function isComposeEnvFlagEnabled(value: string | null | undefined): boolean {
  return (value ?? '').trim().toLowerCase() === 'true';
}

const AppInner: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [notebookTab, setNotebookTab] = useState<NotebookTab>(NotebookTab.CALENDAR);
  const [sessionTab, setSessionTab] = useState<SessionTab>(SessionTab.MAIN);
  const [logsTab, setLogsTab] = useState<LogsTab>(LogsTab.MAIN);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  const [isBugReportOpen, setIsBugReportOpen] = useState(false);
  const serverConnection = useServerStatus();
  const docker = useDockerContext();

  // Reactive cache invalidations on server state transitions
  useServerEventReactor(serverConnection);
  // Always-on Docker log token scanner
  useAuthTokenSync(serverConnection.reachable);

  // Track clientRunning at app level so Sidebar can derive Session status
  const [clientRunning, setClientRunning] = useState(false);

  // Live mode lifted to App level so state survives tab switches
  const live = useLiveMode();

  // Star popup (one-time after 2+ hours cumulative use)
  const { showStarPopup, dismissStarPopup } = useStarPopup();

  // Derive upload/import status from unified Zustand queue store (GH #41/#42)
  const isUploading = useImportQueueStore(selectIsUploading);

  // 4.2 — sync server reachability to watcher store so file discovery pauses when offline
  const setWatcherServerConnected = useImportQueueStore((s) => s.setWatcherServerConnected);
  useEffect(() => {
    setWatcherServerConnected(serverConnection.reachable);
  }, [serverConnection.reachable, setWatcherServerConnected]);

  const [startupFlowPending, setStartupFlowPending] = useState(false);
  const startupFlowPendingRef = useRef(false);

  const [hfPromptOpen, setHfPromptOpen] = useState(false);
  const [hfTokenDraft, setHfTokenDraft] = useState('');
  const [showHfTokenDraft, setShowHfTokenDraft] = useState(false);
  const hfResolverRef = useRef<
    ((result: { action: 'cancel' | 'skip' | 'provided'; token: string }) => void) | null
  >(null);

  const [modelOnboardingOpen, setModelOnboardingOpen] = useState(false);
  const [onboardingMainModelSelection, setOnboardingMainModelSelection] =
    useState(MAIN_RECOMMENDED_MODEL);
  const [onboardingLiveModelSelection, setOnboardingLiveModelSelection] =
    useState(LIVE_RECOMMENDED_MODEL);
  const modelOnboardingResolverRef = useRef<
    | ((result: {
        action: 'cancel' | 'continue';
        mainTranscriberModel: string;
        liveTranscriberModel: string;
      }) => void)
    | null
  >(null);

  const [dependencyInstallPromptOpen, setDependencyInstallPromptOpen] = useState(false);
  const [missingFamiliesForPrompt, setMissingFamiliesForPrompt] = useState<MissingFamily[]>([]);
  const dependencyInstallResolverRef = useRef<((install: boolean | null) => void) | null>(null);

  const [remoteProfilePromptOpen, setRemoteProfilePromptOpen] = useState(false);
  const remoteProfileResolverRef = useRef<
    ((result: { action: 'cancel' | 'continue'; profile: 'tailscale' | 'lan' }) => void) | null
  >(null);

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

  const resolveModelOnboarding = useCallback(
    (result: {
      action: 'cancel' | 'continue';
      mainTranscriberModel: string;
      liveTranscriberModel: string;
    }) => {
      setModelOnboardingOpen(false);
      const resolver = modelOnboardingResolverRef.current;
      modelOnboardingResolverRef.current = null;
      resolver?.(result);
    },
    [],
  );

  const requestModelOnboarding = useCallback(
    async (initialSelections: {
      mainSelection: string;
      liveSelection: string;
    }): Promise<{
      action: 'cancel' | 'continue';
      mainTranscriberModel: string;
      liveTranscriberModel: string;
    }> => {
      return new Promise((resolve) => {
        modelOnboardingResolverRef.current = resolve;
        setOnboardingMainModelSelection(initialSelections.mainSelection);
        setOnboardingLiveModelSelection(initialSelections.liveSelection);
        setModelOnboardingOpen(true);
      });
    },
    [],
  );

  const resolveDependencyInstallPrompt = useCallback((install: boolean | null) => {
    setDependencyInstallPromptOpen(false);
    setMissingFamiliesForPrompt([]);
    const resolver = dependencyInstallResolverRef.current;
    dependencyInstallResolverRef.current = null;
    resolver?.(install);
  }, []);

  const requestDependencyInstallPrompt = useCallback(
    async (missingFamilies: MissingFamily[]): Promise<boolean | null> => {
      return new Promise((resolve) => {
        dependencyInstallResolverRef.current = resolve;
        setMissingFamiliesForPrompt(missingFamilies);
        setDependencyInstallPromptOpen(true);
      });
    },
    [],
  );

  const resolveRemoteProfilePrompt = useCallback(
    (result: { action: 'cancel' | 'continue'; profile: 'tailscale' | 'lan' }) => {
      setRemoteProfilePromptOpen(false);
      const resolver = remoteProfileResolverRef.current;
      remoteProfileResolverRef.current = null;
      resolver?.(result);
    },
    [],
  );

  const requestRemoteProfilePrompt = useCallback(async (): Promise<{
    action: 'cancel' | 'continue';
    profile: 'tailscale' | 'lan';
  }> => {
    return new Promise((resolve) => {
      remoteProfileResolverRef.current = resolve;
      setRemoteProfilePromptOpen(true);
    });
  }, []);

  useEffect(() => {
    return () => {
      if (hfResolverRef.current) {
        hfResolverRef.current({ action: 'cancel', token: '' });
        hfResolverRef.current = null;
      }
      if (modelOnboardingResolverRef.current) {
        modelOnboardingResolverRef.current({
          action: 'cancel',
          mainTranscriberModel: DISABLED_MODEL_SENTINEL,
          liveTranscriberModel: DISABLED_MODEL_SENTINEL,
        });
        modelOnboardingResolverRef.current = null;
      }
      if (dependencyInstallResolverRef.current) {
        dependencyInstallResolverRef.current(null);
        dependencyInstallResolverRef.current = null;
      }
      if (remoteProfileResolverRef.current) {
        remoteProfileResolverRef.current({ action: 'cancel', profile: 'tailscale' });
        remoteProfileResolverRef.current = null;
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
        const shouldRunOnboarding = !docker.container.exists;
        const modelOnboardingCompleted =
          (await getConfig<boolean>('app.modelSelectionOnboardingCompleted')) === true;
        const shouldRunModelOnboarding = !modelOnboardingCompleted;
        const dockerApi = (window as any).electronAPI?.docker;

        const readComposeEnvValue = async (key: string): Promise<string> => {
          const value = (await dockerApi?.readComposeEnvValue(key).catch(() => null)) as
            | string
            | null
            | undefined;
          return (value ?? '').trim();
        };

        const finalizeModelValue = async (
          candidateValue: string | undefined,
          composeKey: 'MAIN_TRANSCRIBER_MODEL' | 'LIVE_TRANSCRIBER_MODEL',
          fallback: string,
        ): Promise<string> => {
          const candidate = (candidateValue ?? '').trim();
          if (candidate === DISABLED_MODEL_SENTINEL) return DISABLED_MODEL_SENTINEL;
          if (candidate) return candidate;

          const composeValue = await readComposeEnvValue(composeKey);
          if (composeValue === DISABLED_MODEL_SENTINEL) return DISABLED_MODEL_SENTINEL;
          if (composeValue) return composeValue;
          return fallback;
        };

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

        let selectedMainModel = (models?.mainTranscriberModel ?? '').trim();
        let selectedLiveModel = (models?.liveTranscriberModel ?? '').trim();

        if (shouldRunModelOnboarding) {
          const storedMainSelection =
            (await getConfig<string>('server.mainModelSelection')) ?? MAIN_RECOMMENDED_MODEL;
          const storedLiveSelection =
            (await getConfig<string>('server.liveModelSelection')) ?? LIVE_RECOMMENDED_MODEL;
          const onboardingMainSelection = mapBackendModelToUiSelection(storedMainSelection);
          const onboardingLiveSelection = mapBackendModelToUiSelection(storedLiveSelection);
          const mainSelectionForOnboarding = ONBOARDING_MAIN_MODEL_OPTIONS.includes(
            onboardingMainSelection as (typeof ONBOARDING_MAIN_MODEL_OPTIONS)[number],
          )
            ? onboardingMainSelection
            : MAIN_RECOMMENDED_MODEL;
          const liveSelectionForOnboarding = ONBOARDING_LIVE_MODEL_OPTIONS.includes(
            onboardingLiveSelection as (typeof ONBOARDING_LIVE_MODEL_OPTIONS)[number],
          )
            ? onboardingLiveSelection
            : LIVE_RECOMMENDED_MODEL;

          const onboardingResult = await requestModelOnboarding({
            mainSelection: mainSelectionForOnboarding,
            liveSelection: liveSelectionForOnboarding,
          });

          if (onboardingResult.action === 'cancel') return;

          selectedMainModel = onboardingResult.mainTranscriberModel;
          selectedLiveModel = onboardingResult.liveTranscriberModel;

          await Promise.all([
            setConfig('server.mainModelSelection', mapBackendModelToUiSelection(selectedMainModel)),
            setConfig('server.mainCustomModel', ''),
            setConfig('server.liveModelSelection', mapBackendModelToUiSelection(selectedLiveModel)),
            setConfig('server.liveCustomModel', ''),
            setConfig('app.modelSelectionOnboardingCompleted', true),
          ]);
        } else if (!selectedMainModel || !selectedLiveModel) {
          const [
            storedMainSelectionRaw,
            storedMainCustomRaw,
            storedLiveSelectionRaw,
            storedLiveCustomRaw,
          ] = await Promise.all([
            getConfig<string>('server.mainModelSelection'),
            getConfig<string>('server.mainCustomModel'),
            getConfig<string>('server.liveModelSelection'),
            getConfig<string>('server.liveCustomModel'),
          ]);

          const envMainModel = await readComposeEnvValue('MAIN_TRANSCRIBER_MODEL');
          const envLiveModel = await readComposeEnvValue('LIVE_TRANSCRIBER_MODEL');

          const storedMainSelection =
            typeof storedMainSelectionRaw === 'string' && storedMainSelectionRaw.trim()
              ? storedMainSelectionRaw.trim()
              : mapBackendModelToUiSelection(envMainModel || MAIN_RECOMMENDED_MODEL);
          const storedLiveSelection =
            typeof storedLiveSelectionRaw === 'string' && storedLiveSelectionRaw.trim()
              ? storedLiveSelectionRaw.trim()
              : mapBackendModelToUiSelection(envLiveModel || LIVE_RECOMMENDED_MODEL);

          const storedMainCustom =
            typeof storedMainCustomRaw === 'string' ? storedMainCustomRaw : '';
          const storedLiveCustom =
            typeof storedLiveCustomRaw === 'string' ? storedLiveCustomRaw : '';

          const resolvedMainModel = resolveMainModelSelectionValue(
            storedMainSelection,
            storedMainCustom,
            envMainModel || MAIN_RECOMMENDED_MODEL,
          );
          const resolvedLiveModel = resolveLiveModelSelectionValue(
            storedLiveSelection,
            storedLiveCustom,
            resolvedMainModel,
            envLiveModel || LIVE_RECOMMENDED_MODEL,
          );

          selectedMainModel = toBackendModelEnvValue(resolvedMainModel);
          selectedLiveModel = toBackendModelEnvValue(resolvedLiveModel);
        }

        selectedMainModel = await finalizeModelValue(
          selectedMainModel,
          'MAIN_TRANSCRIBER_MODEL',
          MAIN_RECOMMENDED_MODEL,
        );
        selectedLiveModel = await finalizeModelValue(
          selectedLiveModel,
          'LIVE_TRANSCRIBER_MODEL',
          LIVE_RECOMMENDED_MODEL,
        );

        const [
          composeInstallWhisper,
          composeInstallNemo,
          composeInstallVibeVoiceAsr,
          bootstrapStatus,
        ] = await Promise.all([
          readComposeEnvValue('INSTALL_WHISPER'),
          readComposeEnvValue('INSTALL_NEMO'),
          readComposeEnvValue('INSTALL_VIBEVOICE_ASR'),
          getOptionalDependencyBootstrapStatus(),
        ]);

        const missingFamilies = computeMissingModelFamilies({
          mainModel: selectedMainModel,
          liveModel: selectedLiveModel,
          composeInstallWhisperEnabled: isComposeEnvFlagEnabled(composeInstallWhisper),
          composeInstallNemoEnabled: isComposeEnvFlagEnabled(composeInstallNemo),
          composeInstallVibeVoiceAsrEnabled: isComposeEnvFlagEnabled(composeInstallVibeVoiceAsr),
          bootstrapStatus,
        });

        let installFlagPatch = {};
        if (missingFamilies.length > 0) {
          const dependencyInstallResult = await requestDependencyInstallPrompt(
            missingFamilies as MissingFamily[],
          );
          if (dependencyInstallResult !== true) return;
          installFlagPatch = toInstallFlagPatch(missingFamilies);
        }

        const storedTokenRaw = await getConfig<string>('server.hfToken');
        let hfToken = typeof storedTokenRaw === 'string' ? storedTokenRaw.trim() : '';
        let hfDecision = normalizeHfDecision(await getConfig('server.hfTokenDecision'));

        if (shouldRunOnboarding) {
          if (hfToken.length > 0) {
            if (hfDecision !== 'provided') {
              hfDecision = 'provided';
              await setConfig('server.hfTokenDecision', hfDecision);
            }
          } else {
            const envToken = await readComposeEnvValue('HUGGINGFACE_TOKEN');
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
        }

        // --- Remote profile chooser (GH #43) ---
        if (mode === 'remote') {
          const certsExist = dockerApi?.checkTailscaleCertsExist
            ? await dockerApi.checkTailscaleCertsExist().catch((err: unknown) => {
                console.warn(
                  '[App] checkTailscaleCertsExist failed, showing profile chooser:',
                  err,
                );
                return false;
              })
            : false;
          const currentProfile = await getConfig<'tailscale' | 'lan'>('connection.remoteProfile');
          if (currentProfile !== 'lan' && !certsExist) {
            const profileResult = await requestRemoteProfilePrompt();
            if (profileResult.action === 'cancel') return;
            await setConfig('connection.remoteProfile', profileResult.profile);
          }
        }

        await docker.startContainer(
          mode,
          runtimeProfile,
          undefined,
          imageTag,
          hfToken || undefined,
          {
            ...(shouldRunOnboarding ? { hfTokenDecision: hfDecision } : {}),
            ...installFlagPatch,
            mainTranscriberModel: selectedMainModel,
            liveTranscriberModel: selectedLiveModel,
            ...(models?.diarizationModel ? { diarizationModel: models.diarizationModel } : {}),
          },
        );
      } finally {
        startupFlowPendingRef.current = false;
        setStartupFlowPending(false);
      }
    },
    [
      docker,
      requestHfPrompt,
      requestModelOnboarding,
      requestDependencyInstallPrompt,
      requestRemoteProfilePrompt,
    ],
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
              sessionTab={sessionTab}
              onChangeSessionTab={setSessionTab}
            />
          </ErrorBoundary>
        );
      case View.NOTEBOOK:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <NotebookView activeTab={notebookTab} />
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
      case View.MODEL_MANAGER:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <ModelManagerView />
          </ErrorBoundary>
        );
      case View.LOGS:
        return (
          <ErrorBoundary FallbackComponent={ErrorFallback} resetKeys={[currentView]}>
            <LogsView logsTab={logsTab} />
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
              sessionTab={sessionTab}
              onChangeSessionTab={setSessionTab}
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
        notebookTab={notebookTab}
        onChangeNotebookTab={setNotebookTab}
        sessionTab={sessionTab}
        onChangeSessionTab={setSessionTab}
        logsTab={logsTab}
        onChangeLogsTab={setLogsTab}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenAbout={() => setIsAboutOpen(true)}
        onOpenBugReport={() => setIsBugReportOpen(true)}
        containerRunning={docker.container.running}
        containerExists={docker.container.exists}
        containerHealth={docker.container.health}
        clientRunning={clientRunning}
        gpuError={serverConnection.details?.gpu_error}
      />

      {/* Main Content Area */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {/* Top Gradient Fade for aesthetic scrolling */}
        <div className="pointer-events-none absolute top-0 right-0 left-0 z-10 h-8 bg-linear-to-b from-slate-900/10 to-transparent"></div>

        {/* Queue paused banner — visible across all views */}
        <QueuePausedBanner />

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
      <BugReportModal isOpen={isBugReportOpen} onClose={() => setIsBugReportOpen(false)} />
      <StarPopupModal isOpen={showStarPopup} onDismiss={() => void dismissStarPopup()} />

      {modelOnboardingOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() =>
              resolveModelOnboarding({
                action: 'cancel',
                mainTranscriberModel: DISABLED_MODEL_SENTINEL,
                liveTranscriberModel: DISABLED_MODEL_SENTINEL,
              })
            }
          />
          <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">Choose Models Before Setup</h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-4 text-sm text-slate-300">
                <p>
                  Select the model for each slot first. Dependency installation only starts after
                  you continue.
                </p>
                <div className="space-y-2">
                  <label className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
                    Main Transcriber
                  </label>
                  <CustomSelect
                    value={onboardingMainModelSelection}
                    onChange={setOnboardingMainModelSelection}
                    options={[...ONBOARDING_MAIN_MODEL_OPTIONS]}
                    accentColor="magenta"
                    className="focus:ring-accent-magenta h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
                    Live Mode Model
                  </label>
                  <CustomSelect
                    value={onboardingLiveModelSelection}
                    onChange={setOnboardingLiveModelSelection}
                    options={[...ONBOARDING_LIVE_MODEL_OPTIONS]}
                    className="focus:ring-accent-cyan h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white transition-shadow outline-none focus:ring-1"
                  />
                </div>
                <p className="text-xs text-slate-400">
                  Recommended defaults: <span className="text-white">parakeet</span> for Main and{' '}
                  <span className="text-white">faster-whisper-medium</span> for Live.
                </p>
              </div>
            </div>
            <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button
                variant="ghost"
                onClick={() =>
                  resolveModelOnboarding({
                    action: 'cancel',
                    mainTranscriberModel: DISABLED_MODEL_SENTINEL,
                    liveTranscriberModel: DISABLED_MODEL_SENTINEL,
                  })
                }
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() =>
                  resolveModelOnboarding({
                    action: 'continue',
                    mainTranscriberModel: toBackendModelEnvValue(onboardingMainModelSelection),
                    liveTranscriberModel: toBackendModelEnvValue(onboardingLiveModelSelection),
                  })
                }
              >
                Continue
              </Button>
            </div>
          </div>
        </div>
      )}

      {dependencyInstallPromptOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() => resolveDependencyInstallPrompt(null)}
          />
          <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">Additional Dependencies Required</h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-3 text-sm text-slate-300">
                <p>
                  The selected models need extra dependency families before the server can start.
                </p>
                <ul className="list-disc space-y-1 pl-5 text-slate-200">
                  {missingFamiliesForPrompt.map((family) => (
                    <li key={family}>{familyDisplayName(family)}</li>
                  ))}
                </ul>
                <p className="text-slate-400">
                  Install these dependencies now to continue startup.
                </p>
              </div>
            </div>
            <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button variant="ghost" onClick={() => resolveDependencyInstallPrompt(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => resolveDependencyInstallPrompt(true)}>
                Install
              </Button>
            </div>
          </div>
        </div>
      )}

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

      {remoteProfilePromptOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
            onClick={() => resolveRemoteProfilePrompt({ action: 'cancel', profile: 'tailscale' })}
          />
          <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
            <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
              <h2 className="text-lg font-semibold text-white">Remote Connection Profile</h2>
            </div>
            <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
              <div className="space-y-4 text-sm text-slate-300">
                <p>How will remote clients connect to this server?</p>
                <div className="space-y-3">
                  <button
                    className="w-full rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/20 hover:bg-white/10"
                    onClick={() =>
                      resolveRemoteProfilePrompt({ action: 'continue', profile: 'lan' })
                    }
                  >
                    <div className="font-medium text-white">LAN (local network)</div>
                    <div className="mt-1 text-xs text-slate-400">
                      Both machines on the same network. A self-signed TLS certificate is generated
                      automatically.
                    </div>
                  </button>
                  <button
                    className="w-full rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/20 hover:bg-white/10"
                    onClick={() =>
                      resolveRemoteProfilePrompt({ action: 'continue', profile: 'tailscale' })
                    }
                  >
                    <div className="font-medium text-white">Tailscale</div>
                    <div className="mt-1 text-xs text-slate-400">
                      Cross-network access via Tailscale. Requires Tailscale certificates (see
                      README for setup).
                    </div>
                  </button>
                </div>
                <p className="text-xs text-slate-500">
                  You can change this later in Settings &rarr; Client &rarr; Remote Profile.
                </p>
              </div>
            </div>
            <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
              <Button
                variant="ghost"
                onClick={() =>
                  resolveRemoteProfilePrompt({ action: 'cancel', profile: 'tailscale' })
                }
              >
                Cancel
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
    <ErrorBoundary FallbackComponent={ErrorFallback}>
      <DownloadNotifications />
    </ErrorBoundary>
    <Toaster position="bottom-right" theme="dark" richColors />
    <ReactQueryDevtools initialIsOpen={false} />
  </QueryClientProvider>
);

export default App;
