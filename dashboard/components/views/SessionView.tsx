import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import {
  Mic,
  Radio,
  Square,
  RefreshCw,
  Languages,
  Copy,
  Volume2,
  VolumeX,
  Maximize2,
  Activity,
  Server,
  Laptop,
  Loader2,
  X,
  Download,
  Plus,
  Minus,
  ExternalLink,
  Minimize2,
  AlertTriangle,
  Zap,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { StatusLight } from '../ui/StatusLight';
import { AudioVisualizer } from '../AudioVisualizer';
import { CustomSelect } from '../ui/CustomSelect';
import { FullscreenVisualizer } from './FullscreenVisualizer';
import { PopOutWindow } from '../PopOutWindow';
import { useQueryClient } from '@tanstack/react-query';
import { useLanguages } from '../../src/hooks/useLanguages';
import { writeToClipboard } from '../../src/hooks/useClipboard';
import { useTranscription } from '../../src/hooks/useTranscription';
import type { LiveModeState } from '../../src/hooks/useLiveMode';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { useTraySync } from '../../src/hooks/useTraySync';
import type { ServerConnectionInfo } from '../../src/hooks/useServerStatus';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { apiClient } from '../../src/api/client';
import { getAuthToken, getConfig, setConfig } from '../../src/config/store';
import { logClientEvent } from '../../src/services/clientDebugLog';
import {
  supportsTranslation,
  filterLanguagesForModel,
  isCanaryModel,
  isWhisperModel,
  pickDefaultLanguage,
  supportsAutoDetect,
  CANARY_TRANSLATION_TARGETS,
} from '../../src/services/modelCapabilities';
import { isModelDisabled } from '../../src/services/modelSelection';
import { SessionTab } from '../../types';
import { SessionImportTab } from './SessionImportTab';
import { useImportQueueStore } from '../../src/stores/importQueueStore';
import { toast } from 'sonner';
import { isRuntimeProfile, type RuntimeProfile } from '../../src/types/runtime';

interface SessionViewProps {
  serverConnection: ServerConnectionInfo;
  clientRunning: boolean;
  setClientRunning: (running: boolean) => void;
  onStartServer: (
    mode: 'local' | 'remote',
    runtimeProfile: RuntimeProfile,
    imageTag?: string,
    models?: {
      mainTranscriberModel?: string;
      liveTranscriberModel?: string;
      diarizationModel?: string;
      whispercppModel?: string;
    },
  ) => Promise<void>;
  startupFlowPending: boolean;
  isUploading?: boolean;
  live: LiveModeState;
  sessionTab: SessionTab;
  onChangeSessionTab: (tab: SessionTab) => void;
}

export const SessionView: React.FC<SessionViewProps> = ({
  serverConnection,
  clientRunning,
  setClientRunning,
  onStartServer,
  startupFlowPending,
  isUploading,
  live,
  sessionTab,
  onChangeSessionTab,
}) => {
  // Global State
  const [isFullscreenVisualizerOpen, setIsFullscreenVisualizerOpen] = useState(false);
  const [isLivePoppedOut, setIsLivePoppedOut] = useState(false);
  const [visualizerAmplitudeScale, setVisualizerAmplitudeScale] = useState(1.0);

  // Capture gain — boosts quiet system audio sources via Web Audio GainNode.
  // Persisted per-sink in config store. Also drives live mode gain.
  const [captureGain, setCaptureGain] = useState(1.0);
  // Diagnostic: effective monitor source volume after loopback creation (Linux)
  const [monitorVolumePct, setMonitorVolumePct] = useState<number | null>(null);

  // Runtime profile (read from persisted config)
  const [runtimeProfile, setRuntimeProfile] = useState<RuntimeProfile>('cpu');
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('server.runtimeProfile')
        .then((val: unknown) => {
          if (isRuntimeProfile(val)) setRuntimeProfile(val);
        })
        .catch(() => {});
    }
  }, []);

  // Server mode badge (local vs remote) — derived from TLS_ENABLED compose env
  const [serverMode, setServerMode] = useState<'local' | 'remote' | null>(null);

  // Client connection mode badge (local vs remote) — from connection.useRemote config
  const [clientMode, setClientMode] = useState<'local' | 'remote' | null>(null);
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.config) return;
    api.config
      .get('connection.useRemote')
      .then((val: unknown) => {
        if (val === true) setClientMode('remote');
        else if (val === false) setClientMode('local');
      })
      .catch(() => {});
  }, []);

  const queryClient = useQueryClient();

  // Admin status (needed early for model-aware language list)
  const admin = useAdminStatus();
  // Prefer admin status (auth-gated) for model name; fall back to the
  // unauthenticated /api/status payload so remote clients without an
  // auth token can still derive the active model.
  const activeModel =
    admin.status?.config?.main_transcriber?.model ??
    admin.status?.config?.transcription?.model ??
    serverConnection.details?.models?.transcription?.selected_model ??
    null;
  const activeLiveModel =
    admin.status?.config?.live_transcriber?.model ??
    admin.status?.config?.live_transcription?.model ??
    activeModel;

  // Real language list from server — re-fetches when model backend changes
  const { languages, loading: languagesLoading } = useLanguages(activeModel);
  const allLanguageOptions = useMemo(() => {
    // useLanguages returns sorted entries (English first, then alphabetical)
    // with Auto Detect prepended. Ensure no duplicates.
    const filtered = languages.filter((l) => l.code !== 'auto').map((l) => l.name);
    return ['Auto Detect', ...filtered];
  }, [languages]);

  // Transcription hooks
  const transcription = useTranscription();

  // Active analyser: live mode takes priority when active, then one-shot
  const activeAnalyser = live.analyser ?? transcription.analyser;

  // Audio device enumeration
  const [micDevices, setMicDevices] = useState<string[]>([]);
  const [micDeviceIds, setMicDeviceIds] = useState<Record<string, string>>({});

  // Linux system audio: PulseAudio/PipeWire sink list
  const isLinux = typeof navigator !== 'undefined' && navigator.platform.startsWith('Linux');
  const [sysDevices, setSysDevices] = useState<string[]>([]);
  const [sysDevice, setSysDevice] = useState('Default Output');
  // Maps sink description → internal PulseAudio sink name
  const [sinkNameMap, setSinkNameMap] = useState<Record<string, string>>({});

  // Audio Configuration State
  const [audioSource, setAudioSource] = useState<'mic' | 'system'>('mic');
  const [micDevice, setMicDevice] = useState('Default Microphone');
  const persistedSelectionsRef = useRef<{
    audioSource?: 'mic' | 'system';
    micDevice?: string;
    sysDevice?: string;
    mainLanguage?: string;
    liveLanguage?: string;
  }>({});

  const pickPreferredOption = useCallback(
    (options: string[], currentValue: string, rememberedValue?: string) => {
      if (options.includes(currentValue)) return currentValue;
      if (rememberedValue && options.includes(rememberedValue)) return rememberedValue;
      return options[0];
    },
    [],
  );

  const enumerateDevices = useCallback(async () => {
    try {
      // Request permission first (needed to get labels)
      await navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then((s) => s.getTracks().forEach((t) => t.stop()));
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter((d) => d.kind === 'audioinput' && d.label);
      const inputLabels = audioInputs.map((d) => d.label);
      const idMap: Record<string, string> = {};
      audioInputs.forEach((d) => {
        idMap[d.label] = d.deviceId;
      });
      const micOptions = inputLabels.length > 0 ? inputLabels : ['Default Microphone'];
      setMicDevices(micOptions);
      setMicDeviceIds(idMap);
      const nextMicDevice = pickPreferredOption(
        micOptions,
        micDevice,
        persistedSelectionsRef.current.micDevice,
      );
      if (nextMicDevice !== micDevice) setMicDevice(nextMicDevice);
    } catch {
      setMicDevices(['Default Microphone']);
    }
  }, [micDevice, pickPreferredOption]);

  useEffect(() => {
    enumerateDevices();
  }, [enumerateDevices]);

  // Linux: fetch PulseAudio/PipeWire sinks for system audio capture
  const fetchSinks = useCallback(async () => {
    if (!isLinux) return;
    try {
      const sinks = await window.electronAPI?.audio?.listSinks?.();
      if (!sinks || sinks.length === 0) {
        setSysDevices(['No sinks found']);
        return;
      }
      const descriptions = sinks.map((s) => s.description);
      const map: Record<string, string> = {};
      sinks.forEach((s) => {
        map[s.description] = s.name;
      });
      setSysDevices(descriptions);
      setSinkNameMap(map);
      const next = pickPreferredOption(
        descriptions,
        sysDevice,
        persistedSelectionsRef.current.sysDevice,
      );
      if (next !== sysDevice) setSysDevice(next);
      // Restore persisted capture gain for the active sink
      const activeSinkName = map[next] ?? map[sysDevice];
      if (activeSinkName) {
        const saved = await getConfig<number>(`session.sinkGain.${activeSinkName}`);
        if (typeof saved === 'number' && Number.isFinite(saved)) {
          setCaptureGain(saved);
        }
      }
    } catch {
      setSysDevices(['No sinks found']);
    }
  }, [isLinux, sysDevice, pickPreferredOption]);

  useEffect(() => {
    if (audioSource === 'system' && isLinux) {
      fetchSinks();
    }
  }, [audioSource, isLinux, fetchSinks]);

  // Control Center State — real Docker container status
  const docker = useDockerContext();
  const isBareMetal = runtimeProfile === 'metal';
  const serverRunning = isBareMetal ? serverConnection.reachable : docker.container.running;

  // serverMode effect — must live after docker/serverRunning are declared
  useEffect(() => {
    if (!serverRunning) {
      setServerMode(null);
      return;
    }
    const dockerApi = (window as any).electronAPI?.docker;
    if (!dockerApi?.readComposeEnvValue) return;
    dockerApi
      .readComposeEnvValue('TLS_ENABLED')
      .then((val: unknown) => {
        setServerMode(val === 'true' ? 'remote' : 'local');
      })
      .catch(() => {});
  }, [serverRunning]);
  // Client connection state — tracked at App level via props
  const isAsrModelsLoaded =
    admin.status?.models_loaded ??
    Boolean(
      (admin.status?.models as { transcription?: { loaded?: boolean } } | undefined)?.transcription
        ?.loaded,
    );
  const showUnloadModelsState = !serverRunning || isAsrModelsLoaded;
  const [modelsOperationPending, setModelsOperationPending] = useState(false);
  const [modelsOperationType, setModelsOperationType] = useState<'loading' | 'unloading' | null>(
    null,
  );
  const modelsLoadCleanupRef = useRef<(() => void) | null>(null);
  useEffect(
    () => () => {
      modelsLoadCleanupRef.current?.();
    },
    [],
  );

  // Model capabilities (activeModel / activeLiveModel derived above near useLanguages)
  const canTranslate = supportsTranslation(activeModel);
  const canTranslateLive = supportsTranslation(activeLiveModel);
  const mainModelDisabled = isModelDisabled(activeModel);
  const liveModelDisabled = isModelDisabled(activeLiveModel);
  const liveModeWhisperOnlyCompatible = !liveModelDisabled && isWhisperModel(activeLiveModel);
  const liveModeUnsupportedMessage = activeLiveModel
    ? `Live Mode is not compatible with "${activeLiveModel}" — only faster-whisper models are supported in v1. Set a faster-whisper model as the Live Mode model in Server settings.`
    : 'Live Mode only supports faster-whisper models in v1. Change the Live Mode model in Server settings.';
  const liveModeDisabledReason = (() => {
    if (!clientRunning) return 'Server is not running';
    if (!serverConnection.ready) return 'Server is not ready';
    if (liveModelDisabled) return 'No live model selected — configure one in Server settings';
    if (!liveModeWhisperOnlyCompatible)
      return `"${activeLiveModel}" is not a faster-whisper model — Live Mode requires a faster-whisper model`;
    return '';
  })();

  // Filter language options per model — Parakeet models only support 25 languages
  const mainLanguageOptions = useMemo(
    () => filterLanguagesForModel(allLanguageOptions, activeModel),
    [allLanguageOptions, activeModel],
  );
  const liveLanguageOptions = useMemo(
    () => filterLanguagesForModel(allLanguageOptions, activeLiveModel),
    [allLanguageOptions, activeLiveModel],
  );

  // Main Transcription State
  const [mainLanguage, setMainLanguage] = useState('Auto Detect');
  const [mainTranslate, setMainTranslate] = useState(false);
  // Bidirectional translation target (used when Canary + source=English)
  const [mainBidiTarget, setMainBidiTarget] = useState('Off');

  // Output formatting
  const [hideTimestamps, setHideTimestamps] = useState(false);

  // Live Mode State
  const isLive = live.status !== 'idle' && live.status !== 'error';
  const [liveLanguage, setLiveLanguage] = useState('English');
  const [liveTranslate, setLiveTranslate] = useState(false);
  // Bidirectional translation target (used when Canary + source=English)
  const [liveBidiTarget, setLiveBidiTarget] = useState('Off');

  // Canary bidirectional mode: when Canary model + source=English, show target dropdown
  const isCanaryMainBidi = isCanaryModel(activeModel) && mainLanguage === 'English';
  const isCanaryLiveBidi = isCanaryModel(activeLiveModel) && liveLanguage === 'English';

  useEffect(() => {
    let active = true;
    (async () => {
      const [
        savedAudioSource,
        savedMicDevice,
        savedSystemDevice,
        savedMainLanguage,
        savedLiveLanguage,
        savedHideTimestamps,
      ] = await Promise.all([
        getConfig<'mic' | 'system'>('session.audioSource'),
        getConfig<string>('session.micDevice'),
        getConfig<string>('session.systemDevice'),
        getConfig<string>('session.mainLanguage'),
        getConfig<string>('session.liveLanguage'),
        getConfig<boolean>('output.hideTimestamps'),
      ]);
      if (!active) return;

      if (savedAudioSource === 'mic' || savedAudioSource === 'system') {
        persistedSelectionsRef.current.audioSource = savedAudioSource;
        setAudioSource(savedAudioSource);
      }
      if (savedMicDevice) {
        persistedSelectionsRef.current.micDevice = savedMicDevice;
        setMicDevice(savedMicDevice);
      }
      if (savedSystemDevice) {
        persistedSelectionsRef.current.sysDevice = savedSystemDevice;
        setSysDevice(savedSystemDevice);
      }
      if (savedMainLanguage) {
        persistedSelectionsRef.current.mainLanguage = savedMainLanguage;
        setMainLanguage(savedMainLanguage);
      }
      if (savedLiveLanguage) {
        persistedSelectionsRef.current.liveLanguage = savedLiveLanguage;
        setLiveLanguage(savedLiveLanguage);
      }
      if (savedHideTimestamps != null) setHideTimestamps(savedHideTimestamps);
    })().catch(() => {});

    return () => {
      active = false;
    };
  }, []);

  const handleAudioSourceChange = useCallback((source: 'mic' | 'system') => {
    setAudioSource(source);
    persistedSelectionsRef.current.audioSource = source;
    void setConfig('session.audioSource', source).catch(() => {});
  }, []);

  const handleMicDeviceChange = useCallback((device: string) => {
    setMicDevice(device);
    persistedSelectionsRef.current.micDevice = device;
    void setConfig('session.micDevice', device).catch(() => {});
  }, []);

  const handleSystemDeviceChange = useCallback(
    (device: string) => {
      setSysDevice(device);
      persistedSelectionsRef.current.sysDevice = device;
      void setConfig('session.systemDevice', device).catch(() => {});
      // Restore persisted gain for the newly-selected sink
      const sinkName = sinkNameMap[device];
      if (sinkName) {
        void getConfig<number>(`session.sinkGain.${sinkName}`).then((saved) => {
          const g = typeof saved === 'number' && Number.isFinite(saved) ? saved : 1.0;
          setCaptureGain(g);
          transcription.setGain(g);
          live.setGain(g);
        });
      }
    },
    [sinkNameMap, transcription, live],
  );

  /** Update capture gain, apply to active captures, and persist per-sink. */
  const handleCaptureGainChange = useCallback(
    (value: number) => {
      const clamped = Math.max(0.25, Math.min(5, value));
      setCaptureGain(clamped);
      transcription.setGain(clamped);
      live.setGain(clamped);
      // Persist for the current sink
      const sinkName = sinkNameMap[sysDevice];
      if (sinkName) {
        void setConfig(`session.sinkGain.${sinkName}`, clamped).catch(() => {});
      }
    },
    [sinkNameMap, sysDevice, transcription, live],
  );

  const handleMainLanguageChange = useCallback((language: string) => {
    setMainLanguage(language);
    persistedSelectionsRef.current.mainLanguage = language;
    void setConfig('session.mainLanguage', language).catch(() => {});
  }, []);

  const handleLiveLanguageChange = useCallback((language: string) => {
    setLiveLanguage(language);
    persistedSelectionsRef.current.liveLanguage = language;
    void setConfig('session.liveLanguage', language).catch(() => {});
  }, []);

  // Reset translate toggles when model changes to one that doesn't support it
  useEffect(() => {
    if (!canTranslate) setMainTranslate(false);
  }, [canTranslate]);

  useEffect(() => {
    if (!canTranslateLive) setLiveTranslate(false);
  }, [canTranslateLive]);

  useEffect(() => {
    if (languagesLoading) return;
    // When the current selection is no longer valid for the active model,
    // prefer "English" so Canary-style models (which don't support
    // Auto Detect) land on a sensible default. Persist the correction so a
    // stale selection doesn't survive reload.
    if (!mainLanguageOptions.includes(mainLanguage)) {
      const next = pickDefaultLanguage(mainLanguageOptions);
      setMainLanguage(next);
      persistedSelectionsRef.current.mainLanguage = next;
      void setConfig('session.mainLanguage', next).catch(() => {});
    }
    if (!liveLanguageOptions.includes(liveLanguage)) {
      const next = pickDefaultLanguage(liveLanguageOptions);
      setLiveLanguage(next);
      persistedSelectionsRef.current.liveLanguage = next;
      void setConfig('session.liveLanguage', next).catch(() => {});
    }
  }, [languagesLoading, mainLanguageOptions, liveLanguageOptions, mainLanguage, liveLanguage]);

  // Derive active client connection from explicit state + hook activity
  const clientConnected =
    clientRunning &&
    (serverConnection.reachable ||
      transcription.status === 'recording' ||
      transcription.status === 'processing' ||
      live.status === 'listening' ||
      live.status === 'processing' ||
      live.status === 'starting');

  // Client connection status label
  const clientStatusLabel = clientConnected
    ? 'Connected to Server'
    : clientRunning && !serverConnection.reachable
      ? serverConnection.error || 'Server Unreachable'
      : transcription.status === 'connecting' || live.status === 'connecting'
        ? 'Connecting...'
        : 'Disconnected';

  // Client start/stop handlers (mirrors v0.5.6 ClientControlMixin)
  const handleStartClientLocal = useCallback(async () => {
    await setConfig('connection.useRemote', false);
    await setConfig('connection.useHttps', false);
    await setConfig('connection.localHost', 'localhost');
    await apiClient.syncFromConfig();
    apiClient.setAuthToken((await getAuthToken()) ?? null);
    setClientMode('local');
    setClientRunning(true);
    logClientEvent('Client', `Configured local connection → ${apiClient.getBaseUrl()}`);
    serverConnection.refresh();
  }, [serverConnection]);

  // In Metal GPU mode the server always runs locally, so automatically start
  // the local client link as soon as the inference server becomes fully ready.
  // Using a ref to track the previous ready value means we only fire on the
  // rising edge (false → true), which prevents re-triggering when the user
  // manually stops the client while the server stays up.
  const prevServerReadyRef = useRef(false);
  useEffect(() => {
    const wasReady = prevServerReadyRef.current;
    prevServerReadyRef.current = serverConnection.ready;
    if (isBareMetal && serverConnection.ready && !wasReady && !clientRunning) {
      void handleStartClientLocal();
    }
  }, [isBareMetal, serverConnection.ready, clientRunning, handleStartClientLocal]);

  const handleStartClientRemote = useCallback(async () => {
    const remoteProfile =
      (await getConfig<'tailscale' | 'lan'>('connection.remoteProfile')) ?? 'tailscale';
    await setConfig('connection.useRemote', true);
    await setConfig('connection.useHttps', true);
    await apiClient.syncFromConfig();
    apiClient.setAuthToken((await getAuthToken()) ?? null);
    setClientMode('remote');
    setClientRunning(true);
    logClientEvent(
      'Client',
      `Configured remote connection (${remoteProfile === 'lan' ? 'LAN' : 'Tailscale'}) → ${apiClient.getBaseUrl()}`,
    );
    serverConnection.refresh();
  }, [serverConnection]);

  const handleStopClient = useCallback(() => {
    setClientRunning(false);
    logClientEvent('Client', 'Client link stopped', 'warning');
  }, []);

  const handleUnloadAllModels = useCallback(async () => {
    setModelsOperationPending(true);
    setModelsOperationType('unloading');
    try {
      await Promise.allSettled([apiClient.unloadModels(), apiClient.unloadLLMModel()]);
      logClientEvent('Client', 'Requested unload for all models', 'warning');
      admin.refresh();
      serverConnection.refresh();
    } finally {
      setModelsOperationPending(false);
      setModelsOperationType(null);
    }
  }, [admin, serverConnection]);

  const handleReloadModels = useCallback(() => {
    setModelsOperationPending(true);
    setModelsOperationType('loading');

    // Clean up any previous load stream
    if (modelsLoadCleanupRef.current) modelsLoadCleanupRef.current();

    const cleanup = apiClient.loadModelsStream({
      onProgress: (msg) => {
        logClientEvent('Client', `Model load: ${msg}`);
      },
      onComplete: () => {
        logClientEvent('Client', 'Models reloaded successfully');
        setModelsOperationPending(false);
        setModelsOperationType(null);
        admin.refresh();
        serverConnection.refresh();
        void queryClient.invalidateQueries({ queryKey: ['languages'] });
      },
      onError: (msg) => {
        logClientEvent('Client', `Model load failed: ${msg}`, 'error');
        setModelsOperationPending(false);
        setModelsOperationType(null);
      },
    });

    modelsLoadCleanupRef.current = cleanup;
  }, [admin, serverConnection, queryClient]);

  // System Health Check for Visual Effects
  const isSystemHealthy = serverRunning && clientConnected;

  // In remote or bare metal (MLX) mode there is no local Docker container; derive "container"
  // state from the remote server connection so tray controls remain functional.
  const isRemoteMode = clientMode === 'remote';
  const trayContainerRunning = isRemoteMode ? clientRunning : serverRunning;
  const trayContainerHealth =
    isRemoteMode || isBareMetal
      ? serverConnection.serverStatus === 'active'
        ? 'healthy'
        : serverConnection.serverStatus === 'error'
          ? 'unhealthy'
          : 'starting'
      : docker.container.health;

  // Sync tray icon state with application state
  useTraySync({
    serverStatus: clientRunning ? serverConnection.serverStatus : 'inactive',
    containerRunning: trayContainerRunning,
    containerHealth: trayContainerHealth,
    transcriptionStatus: transcription.status,
    liveStatus: live.status,
    muted: transcription.muted || live.muted,
    activeModel: activeModel ?? undefined,
    modelsLoaded: isAsrModelsLoaded,
    isLocalConnection: !isRemoteMode,
    isUploading,
    onStartRecording: () => transcription.start(),
    onStopRecording: () => {
      if (isLive) live.stop();
      else transcription.stop();
    },
    onCancelRecording: () => transcription.reset(),
    onToggleMute: () => {
      if (transcription.status === 'recording' || transcription.status === 'connecting') {
        transcription.toggleMute();
      } else {
        live.toggleMute();
      }
    },
    onTranscribeFile: (filePath: string) => {
      // Queue the file at the front — runs next after any in-progress job finishes
      useImportQueueStore.getState().addPriorityFiles([filePath], 'notebook-normal');
    },
    onStartLiveMode: () => handleLiveToggle(true),
    onStopLiveMode: () => live.stop(),
    onToggleLiveMute: () => live.toggleMute(),
    onToggleModels: () => {
      if (isAsrModelsLoaded) handleUnloadAllModels();
      else handleReloadModels();
    },
  });

  // Resolve language code from display name
  const resolveLanguage = useCallback(
    (name: string): string | undefined => {
      if (name === 'Auto Detect') return undefined;
      const match = languages.find((l) => l.name === name);
      return match?.code;
    },
    [languages],
  );

  // Helpers for main transcription controls
  const isRecording = transcription.status === 'recording';
  const isProcessing = transcription.status === 'processing';
  const isConnecting = transcription.status === 'connecting';
  const canStartRecording =
    transcription.status === 'idle' ||
    transcription.status === 'complete' ||
    transcription.status === 'error';

  const handleStartRecording = useCallback(() => {
    if (!canStartRecording || mainModelDisabled) return;
    // gh-102: refuse to start when the active model requires an explicit
    // source language but the dashboard cannot resolve one. Without this,
    // the WS `start` frame would omit `language` and the Canary backend
    // would surface the cryptic "received None" toast (gh-81 fail-loud
    // guard). Block here with a clear message instead.
    const resolvedLang = resolveLanguage(mainLanguage);
    if (resolvedLang === undefined && !supportsAutoDetect(activeModel)) {
      toast.error('Source language required', {
        description: languagesLoading
          ? 'Loading languages — please try again in a moment.'
          : mainLanguage
            ? `"${mainLanguage}" is not a valid source language for the active model. Pick a language from the Source Language dropdown.`
            : 'No source language is selected. Pick a language from the Source Language dropdown.',
      });
      return;
    }
    transcription.reset();
    const isSystemAudio = audioSource === 'system';
    const mainTranslateActive = isCanaryMainBidi ? mainBidiTarget !== 'Off' : mainTranslate;
    const mainTranslateTarget = isCanaryMainBidi ? (resolveLanguage(mainBidiTarget) ?? 'en') : 'en';

    void (async () => {
      let monitorLabel: string | undefined;
      if (isSystemAudio) {
        if (isLinux) {
          // Linux: create a virtual mic from the selected sink's monitor source
          const selectedSink = sinkNameMap[sysDevice];
          if (selectedSink) {
            const result = await window.electronAPI?.audio?.createMonitorLoopback(selectedSink);
            monitorLabel = 'TranscriptionSuite_Loopback';
            setMonitorVolumePct(result?.volumePct ?? null);
          }
        } else {
          // Windows / macOS: register getDisplayMedia loopback handler
          await window.electronAPI?.audio?.enableSystemAudioLoopback?.();
        }
      }
      transcription.start({
        language: resolvedLang,
        deviceId: isSystemAudio ? undefined : micDeviceIds[micDevice],
        translate: mainTranslateActive,
        translationTarget: mainTranslateTarget,
        systemAudio: isSystemAudio,
        monitorDeviceLabel: monitorLabel,
      });
      // Apply persisted capture gain after capture starts
      if (isSystemAudio) {
        transcription.setGain(captureGain);
      }
    })();
  }, [
    canStartRecording,
    transcription,
    mainLanguage,
    mainTranslate,
    mainBidiTarget,
    isCanaryMainBidi,
    audioSource,
    micDevice,
    micDeviceIds,
    resolveLanguage,
    mainModelDisabled,
    isLinux,
    sysDevice,
    sinkNameMap,
    captureGain,
    activeModel,
    languagesLoading,
  ]);

  const handleStopRecording = useCallback(() => {
    transcription.stop();
    if (isLinux) {
      window.electronAPI?.audio?.removeMonitorLoopback?.();
    } else {
      window.electronAPI?.audio?.disableSystemAudioLoopback?.();
    }
  }, [transcription, isLinux]);

  const cancellingRef = useRef(false);
  const handleCancelProcessing = useCallback(async () => {
    if (cancellingRef.current) return;
    cancellingRef.current = true;
    try {
      // During recording/connecting the server has no processing job yet —
      // the REST cancel would 404. Only call it during processing.
      if (transcription.status === 'processing') {
        await apiClient.cancelTranscription();
      }
    } catch (err) {
      console.error('Failed to cancel transcription:', err);
    } finally {
      if (isLinux) {
        window.electronAPI?.audio?.removeMonitorLoopback?.();
      } else {
        window.electronAPI?.audio?.disableSystemAudioLoopback?.();
      }
      transcription.reset();
      cancellingRef.current = false;
    }
  }, [transcription, isLinux]);

  // Copy transcription result to clipboard
  const handleCopyTranscription = useCallback(() => {
    if (!transcription.result?.text) return;
    writeToClipboard(transcription.result.text).catch(() => {});
  }, [transcription.result?.text]);

  // Download transcription as TXT file
  const handleDownloadTranscription = useCallback(() => {
    if (!transcription.result?.text) return;
    const blob = new Blob([transcription.result.text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `transcription-${new Date().toISOString().slice(0, 19).replace(/[:.]/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, [transcription.result?.text]);

  // Helpers for live mode controls
  const handleLiveToggle = useCallback(
    (checked: boolean) => {
      if (checked) {
        if (liveModelDisabled || !liveModeWhisperOnlyCompatible) return;
        // gh-102: same guard as handleStartRecording — refuse to start live
        // mode when the active live model needs an explicit source language
        // and the dashboard cannot resolve one. The current UI gates live
        // mode to Whisper-only models (which do support auto-detect), so
        // this is mostly defense-in-depth, but the guard keeps the contract
        // honest if that gate is ever loosened.
        const resolvedLiveLang = resolveLanguage(liveLanguage);
        if (resolvedLiveLang === undefined && !supportsAutoDetect(activeLiveModel)) {
          toast.error('Source language required', {
            description: languagesLoading
              ? 'Loading languages — please try again in a moment.'
              : liveLanguage
                ? `"${liveLanguage}" is not a valid source language for the active live model. Pick a language from the Live Source Language dropdown.`
                : 'No source language is selected. Pick a language from the Live Source Language dropdown.',
          });
          return;
        }
        const isSystemAudio = audioSource === 'system';
        const liveTranslateActive = isCanaryLiveBidi ? liveBidiTarget !== 'Off' : liveTranslate;
        const liveTranslateTarget = isCanaryLiveBidi
          ? (resolveLanguage(liveBidiTarget) ?? 'en')
          : 'en';
        void (async () => {
          const rawGracePeriod = await getConfig<number>('audio.gracePeriod');
          const gracePeriodSeconds =
            typeof rawGracePeriod === 'number' && Number.isFinite(rawGracePeriod)
              ? rawGracePeriod
              : 1.0;

          let monitorLabel: string | undefined;
          if (isSystemAudio) {
            if (isLinux) {
              const selectedSink = sinkNameMap[sysDevice];
              if (selectedSink) {
                const result = await window.electronAPI?.audio?.createMonitorLoopback(selectedSink);
                monitorLabel = 'TranscriptionSuite_Loopback';
                setMonitorVolumePct(result?.volumePct ?? null);
              }
            } else {
              await window.electronAPI?.audio?.enableSystemAudioLoopback?.();
            }
          }

          live.start({
            language: resolvedLiveLang,
            deviceId: isSystemAudio ? undefined : micDeviceIds[micDevice],
            translate: liveTranslateActive,
            translationTarget: liveTranslateTarget,
            gracePeriodSeconds,
            systemAudio: isSystemAudio,
            monitorDeviceLabel: monitorLabel,
          });
          // Apply persisted capture gain after capture starts
          if (isSystemAudio) {
            live.setGain(captureGain);
          }
        })();
      } else {
        live.stop();
        if (isLinux) {
          window.electronAPI?.audio?.removeMonitorLoopback?.();
        } else {
          window.electronAPI?.audio?.disableSystemAudioLoopback?.();
        }
      }
    },
    [
      live,
      liveLanguage,
      liveTranslate,
      liveBidiTarget,
      isCanaryLiveBidi,
      liveModeWhisperOnlyCompatible,
      audioSource,
      micDevice,
      micDeviceIds,
      resolveLanguage,
      liveModelDisabled,
      isLinux,
      sysDevice,
      sinkNameMap,
      captureGain,
      activeLiveModel,
      languagesLoading,
    ],
  );

  const prevClientConnectedRef = useRef(clientConnected);
  useEffect(() => {
    if (prevClientConnectedRef.current === clientConnected) {
      return;
    }
    prevClientConnectedRef.current = clientConnected;
    logClientEvent(
      'Client',
      clientConnected ? 'Client connection active' : 'Client connection inactive',
      clientConnected ? 'success' : 'warning',
    );
  }, [clientConnected]);

  // Auto-copy transcription to clipboard on completion + desktop notification
  const prevStatusRef = useRef(transcription.status);
  useEffect(() => {
    const wasProcessing = prevStatusRef.current === 'processing';
    prevStatusRef.current = transcription.status;
    if (wasProcessing && transcription.status === 'complete' && transcription.result?.text) {
      const text = transcription.result.text;

      // Single async chain: read both settings, then perform one clipboard operation.
      // This eliminates the race between independent writeToClipboard and pasteAtCursor calls.
      (async () => {
        const pasteEnabled =
          window.electronAPI?.clipboard?.pasteAtCursor &&
          ((await getConfig<boolean>('app.pasteAtCursor')) ?? false);
        const autoCopy = (await getConfig<boolean>('app.autoCopy')) ?? true;

        if (pasteEnabled) {
          // pasteAtCursor writes text to clipboard + simulates Ctrl+V.
          // preserveClipboard: false keeps the text in clipboard (autoCopy is implicit).
          await window
            .electronAPI!.clipboard.pasteAtCursor(text, { preserveClipboard: false })
            .catch((err) => {
              console.warn('Paste at cursor failed:', err);
            });
        } else if (autoCopy) {
          await writeToClipboard(text).catch(() => {});
        }
      })();

      // Desktop notification via Electron's async Notification module (IPC).
      // Falls back to in-app toast if the IPC channel is unavailable or the
      // OS notification fails (e.g. broken D-Bus proxy on Wayland).
      // Never uses the Web Notification API — its synchronous libnotify path
      // blocks the main process for 100+ seconds when D-Bus is unresponsive.
      const body = text.slice(0, 100) + (text.length > 100 ? '...' : '');
      window.electronAPI?.notifications
        ?.show({ title: 'Transcription Complete', body })
        .catch(() => false)
        .then((shown) => {
          if (!shown) toast.success('Transcription Complete', { description: body });
        });
    }
    if (wasProcessing && transcription.status === 'error' && transcription.error) {
      window.electronAPI?.notifications
        ?.show({ title: 'Transcription Failed', body: transcription.error })
        .catch(() => false)
        .then((shown) => {
          if (!shown) toast.error('Transcription Failed', { description: transcription.error });
        });
    }
  }, [transcription.status, transcription.result?.text, transcription.error]);

  // Recovery notification — fetch undelivered results from a previous session
  const [recoveryJobs, setRecoveryJobs] = useState<
    Array<{ job_id: string; completed_at: string; text_preview: string }>
  >([]);
  useEffect(() => {
    const token = apiClient.getAuthToken();
    fetch('/api/transcribe/recent', token ? { headers: { Authorization: `Bearer ${token}` } } : {})
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setRecoveryJobs(data);
      })
      .catch(() => {});
  }, []);

  // Scroll State
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const leftContentRef = useRef<HTMLDivElement>(null);
  const rightContentRef = useRef<HTMLDivElement>(null);

  // Live transcript auto-scroll
  const liveTranscriptRef = useRef<HTMLDivElement>(null);
  const liveAutoScrollRef = useRef(true);

  const [leftScrollState, setLeftScrollState] = useState({ top: false, bottom: false });
  const [rightScrollState, setRightScrollState] = useState({ top: false, bottom: false });
  const [leftColumnBaselineHeight, setLeftColumnBaselineHeight] = useState<number | null>(null);
  const [rightColumnBaselineHeight, setRightColumnBaselineHeight] = useState<number | null>(null);

  const calculateScrollState = useCallback((el: HTMLDivElement | null) => {
    if (!el) return { top: false, bottom: false };
    const { scrollTop, scrollHeight, clientHeight } = el;
    return {
      top: scrollTop > 0,
      bottom: Math.ceil(scrollTop + clientHeight) < scrollHeight,
    };
  }, []);

  const updateLeftScrollState = useCallback(() => {
    setLeftScrollState(calculateScrollState(leftScrollRef.current));
  }, [calculateScrollState]);

  const updateRightScrollState = useCallback(() => {
    setRightScrollState(calculateScrollState(rightScrollRef.current));
  }, [calculateScrollState]);

  const captureColumnBaselines = useCallback(() => {
    const nextLeftHeight = leftScrollRef.current?.clientHeight ?? null;
    const nextRightHeight = rightScrollRef.current?.clientHeight ?? null;
    if (nextLeftHeight) {
      setLeftColumnBaselineHeight((prev) => (prev === nextLeftHeight ? prev : nextLeftHeight));
    }
    if (nextRightHeight) {
      setRightColumnBaselineHeight((prev) => (prev === nextRightHeight ? prev : nextRightHeight));
    }
  }, []);

  const recalcScrollIndicators = useCallback(() => {
    captureColumnBaselines();
    updateLeftScrollState();
    updateRightScrollState();
  }, [captureColumnBaselines, updateLeftScrollState, updateRightScrollState]);

  // Bind listeners once and reset both columns to top on startup.
  useEffect(() => {
    const leftEl = leftScrollRef.current;
    const rightEl = rightScrollRef.current;

    if (leftEl) leftEl.addEventListener('scroll', updateLeftScrollState, { passive: true });
    if (rightEl) rightEl.addEventListener('scroll', updateRightScrollState, { passive: true });
    window.addEventListener('resize', recalcScrollIndicators);

    const raf = requestAnimationFrame(() => {
      if (leftEl) leftEl.scrollTop = 0;
      if (rightEl) rightEl.scrollTop = 0;
      recalcScrollIndicators();
    });

    return () => {
      cancelAnimationFrame(raf);
      if (leftEl) leftEl.removeEventListener('scroll', updateLeftScrollState);
      if (rightEl) rightEl.removeEventListener('scroll', updateRightScrollState);
      window.removeEventListener('resize', recalcScrollIndicators);
    };
  }, [updateLeftScrollState, updateRightScrollState, recalcScrollIndicators]);

  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return;
    const resizeObserver = new ResizeObserver(() => {
      recalcScrollIndicators();
    });
    const targets = [
      leftScrollRef.current,
      rightScrollRef.current,
      leftContentRef.current,
      rightContentRef.current,
    ].filter((el): el is HTMLDivElement => el !== null);
    targets.forEach((el) => resizeObserver.observe(el));
    return () => {
      resizeObserver.disconnect();
    };
  }, [recalcScrollIndicators]);

  // Recalculate indicators whenever layout-affecting view state changes.
  useEffect(() => {
    recalcScrollIndicators();
    const raf = requestAnimationFrame(recalcScrollIndicators);
    const timer = setTimeout(recalcScrollIndicators, 575);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
    };
  }, [recalcScrollIndicators]);

  // Live transcript: track manual scroll to pause auto-scroll
  useEffect(() => {
    const el = liveTranscriptRef.current;
    if (!el) return;
    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      // Consider "near bottom" if within 60px of the bottom
      liveAutoScrollRef.current = scrollHeight - scrollTop - clientHeight < 60;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Live transcript: auto-scroll to bottom when new content arrives
  useEffect(() => {
    const el = liveTranscriptRef.current;
    if (el && liveAutoScrollRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [live.sentences, live.partial]);

  const maskStyle: React.CSSProperties = {
    backgroundColor: '#0f172a',
    backgroundImage:
      'radial-gradient(at 0% 0%, hsla(253,16%,7%,1) 0, transparent 50%), radial-gradient(at 50% 0%, hsla(225,39%,30%,1) 0, transparent 50%), radial-gradient(at 100% 0%, hsla(339,49%,30%,1) 0, transparent 50%)',
    backgroundAttachment: 'fixed',
  };

  if (sessionTab === SessionTab.IMPORT) {
    return (
      <div className="custom-scrollbar h-full w-full overflow-y-auto">
        <div className="mx-auto max-w-7xl py-6 pr-3 pl-6">
          <div className="mb-6 flex flex-col space-y-2">
            <h1 className="text-3xl font-bold tracking-tight text-white">Session</h1>
          </div>
          <SessionImportTab />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col py-6 pr-3 pl-6">
      {/* 1. Header (Fixed) */}
      <div className="mb-6 flex flex-none flex-col space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Session</h1>
      </div>

      {/* Recovery Notifications */}
      {recoveryJobs.length > 0 && (
        <div className="mb-4 flex flex-none flex-col gap-2">
          {recoveryJobs.map((job) => {
            const relativeTime = (() => {
              try {
                const completed = new Date(job.completed_at);
                const diffMs = Date.now() - completed.getTime();
                const diffMins = Math.round(diffMs / 60000);
                if (diffMins < 1) return 'just now';
                if (diffMins < 60) return `${diffMins}m ago`;
                const diffHrs = Math.round(diffMins / 60);
                if (diffHrs < 24) return `${diffHrs}h ago`;
                return `${Math.round(diffHrs / 24)}d ago`;
              } catch {
                return '';
              }
            })();
            return (
              <div
                key={job.job_id}
                className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
              >
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
                <div className="min-w-0 flex-1">
                  <span className="font-medium">
                    Transcription from {relativeTime} is available.
                  </span>
                  {job.text_preview && (
                    <span className="ml-1 text-amber-300/70">
                      &ldquo;{job.text_preview}
                      {job.text_preview.length >= 100 ? '\u2026' : ''}&rdquo;
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    className="rounded px-2 py-1 text-xs font-semibold text-amber-300 hover:bg-amber-500/20"
                    onClick={() => {
                      const viewToken = apiClient.getAuthToken();
                      fetch(
                        `/api/transcribe/result/${job.job_id}`,
                        viewToken ? { headers: { Authorization: `Bearer ${viewToken}` } } : {},
                      )
                        .then(async (resp) => {
                          if (resp.status === 200) {
                            const data = await resp.json();
                            const r = data.result ?? {};
                            transcription.loadResult({
                              text: r.text ?? '',
                              words: r.words ?? [],
                              language: r.language,
                              duration: r.duration,
                            });
                            setRecoveryJobs((prev) => prev.filter((j) => j.job_id !== job.job_id));
                          }
                        })
                        .catch(() => {});
                    }}
                  >
                    View
                  </button>
                  <button
                    className="rounded px-2 py-1 text-xs font-semibold text-amber-300/60 hover:bg-amber-500/20 hover:text-amber-300"
                    onClick={() => {
                      const dismissToken = apiClient.getAuthToken();
                      fetch(`/api/transcribe/result/${job.job_id}/dismiss`, {
                        method: 'POST',
                        ...(dismissToken
                          ? { headers: { Authorization: `Bearer ${dismissToken}` } }
                          : {}),
                      }).catch(() => {});
                      setRecoveryJobs((prev) => prev.filter((j) => j.job_id !== job.job_id));
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 2. Main Content Area */}
      <div className="grid min-h-0 flex-1 grid-cols-1 items-stretch gap-6 lg:grid-cols-[minmax(480px,5fr)_minmax(300px,7fr)]">
        {/* Left Column: Controls (40%) */}
        <div className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl">
          {/* Left Top Scroll Indicator */}
          <div
            className={`pointer-events-none absolute top-0 right-3 left-0 z-20 h-6 overflow-hidden rounded-t-2xl transition-opacity duration-300 ${leftScrollState.top ? 'opacity-100' : 'opacity-0'}`}
          >
            <div
              className="h-full w-full bg-linear-to-b from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
          {/* Left Top Corner Mask */}
          <div
            className="pointer-events-none absolute top-0 right-3 z-20 h-4 w-4"
            style={{
              ...maskStyle,
              maskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)',
              WebkitMaskImage:
                'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)',
            }}
          />

          {/* Main Scrollable Area for Left Column */}
          <div
            ref={leftScrollRef}
            className="custom-scrollbar flex-1 overflow-y-auto pt-0 pr-3 pb-0"
          >
            <div
              ref={leftContentRef}
              className="space-y-6"
              style={
                leftColumnBaselineHeight
                  ? { minHeight: `${leftColumnBaselineHeight}px` }
                  : undefined
              }
            >
              {/* Unified Control Center */}
              <GlassCard
                title="Control Center"
                className={`from-glass-200 to-glass-100 relative flex-none bg-linear-to-b transition-all duration-500 ease-in-out ${isSystemHealthy ? 'border-accent-cyan/50! z-10 shadow-[0_20px_25px_-5px_rgba(0,0,0,0.3),0_8px_10px_-6px_rgba(0,0,0,0.3),inset_0_0_30px_rgba(34,211,238,0.15)]!' : ''}`}
              >
                <div className="space-y-5">
                  {/* Server Control */}
                  <div className="flex flex-col space-y-4 rounded-xl border border-white/5 bg-white/5 p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`bg-accent-magenta/10 text-accent-magenta rounded-lg p-2`}>
                          <Server size={20} />
                        </div>
                        <div className="text-sm font-semibold tracking-wide text-white">
                          Inference Server
                        </div>
                      </div>
                      <div className="flex items-center gap-2.5">
                        <span className="text-xs font-medium text-slate-400">
                          {isRemoteMode
                            ? serverConnection.reachable
                              ? serverConnection.ready
                                ? 'Remote Server Ready'
                                : 'Remote Server Loading\u2026'
                              : 'Remote Server Offline'
                            : isBareMetal
                              ? serverRunning
                                ? 'Native Process Running'
                                : 'Server Offline'
                              : serverRunning && docker.container.health === 'healthy'
                                ? 'Docker Container Running'
                                : serverRunning
                                  ? 'Container Starting\u2026'
                                  : docker.container.exists
                                    ? 'Container Stopped'
                                    : 'Container Missing'}
                        </span>
                        {isBareMetal && serverRunning && (
                          <span className="bg-accent-violet/15 text-accent-violet flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase">
                            <Zap size={10} />
                            metal
                          </span>
                        )}
                        {!isBareMetal && serverRunning && serverMode && (
                          <span
                            className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase ${serverMode === 'local' ? 'bg-accent-cyan/15 text-accent-cyan' : 'bg-accent-magenta/15 text-accent-magenta'}`}
                          >
                            {serverMode === 'local' ? <Laptop size={10} /> : <Radio size={10} />}
                            {serverMode}
                          </span>
                        )}
                        <StatusLight
                          status={
                            isRemoteMode
                              ? serverConnection.reachable
                                ? serverConnection.ready
                                  ? 'active'
                                  : 'warning'
                                : 'inactive'
                              : isBareMetal
                                ? serverRunning
                                  ? 'active'
                                  : 'inactive'
                                : serverRunning && docker.container.health === 'healthy'
                                  ? 'active'
                                  : docker.container.exists
                                    ? 'warning'
                                    : 'inactive'
                          }
                          className="h-2 w-2"
                        />
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {isBareMetal ? (
                        <div className="text-accent-violet/80 flex items-center gap-1.5 text-xs">
                          <Zap size={12} />
                          Managed by native process — start from Server view
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => onStartServer('local', runtimeProfile)}
                            disabled={serverRunning || docker.operating || startupFlowPending}
                            className="px-3 text-xs"
                          >
                            {docker.operating || startupFlowPending ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              'Start Local'
                            )}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => onStartServer('remote', runtimeProfile)}
                            disabled={serverRunning || docker.operating || startupFlowPending}
                            className="px-3 text-xs"
                          >
                            Start Remote
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => docker.stopContainer()}
                            disabled={!serverRunning || docker.operating}
                            className="px-3 text-xs"
                          >
                            Stop
                          </Button>
                        </div>
                      )}
                      <div className="ml-auto shrink-0">
                        <Button
                          variant={showUnloadModelsState ? 'danger' : 'secondary'}
                          size="sm"
                          onClick={isAsrModelsLoaded ? handleUnloadAllModels : handleReloadModels}
                          disabled={!serverConnection.reachable || modelsOperationPending}
                          className="px-3 text-xs"
                        >
                          {modelsOperationPending ? (
                            <>
                              <Loader2 size={14} className="mr-1 animate-spin" />
                              {modelsOperationType === 'loading' ? 'Loading...' : 'Unloading...'}
                            </>
                          ) : showUnloadModelsState ? (
                            'Unload Models'
                          ) : (
                            'Reload Models'
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>

                  {/* Client Control */}
                  <div className="flex flex-col space-y-4 rounded-xl border border-white/5 bg-white/5 p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`bg-accent-cyan/10 text-accent-cyan rounded-lg p-2`}>
                          <Activity size={20} />
                        </div>
                        <div className="text-sm font-semibold tracking-wide text-white">
                          Client Link
                        </div>
                      </div>
                      <div className="flex items-center gap-2.5">
                        <span className="text-xs font-medium text-slate-400">
                          {clientStatusLabel}
                        </span>
                        {clientRunning && clientMode && (
                          <span
                            className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase ${clientMode === 'local' ? 'bg-accent-cyan/15 text-accent-cyan' : 'bg-accent-magenta/15 text-accent-magenta'}`}
                          >
                            {clientMode === 'local' ? <Laptop size={10} /> : <Radio size={10} />}
                            {clientMode}
                          </span>
                        )}
                        <StatusLight
                          status={
                            clientRunning && !serverConnection.reachable
                              ? 'warning'
                              : clientRunning
                                ? 'active'
                                : 'inactive'
                          }
                          className="h-2 w-2"
                        />
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={handleStartClientLocal}
                        disabled={clientRunning}
                        className="px-3 text-xs"
                      >
                        Start Local
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={handleStartClientRemote}
                        disabled={clientRunning || isBareMetal}
                        title={
                          isBareMetal
                            ? 'Remote client link is not supported in Metal mode'
                            : undefined
                        }
                        className="px-3 text-xs"
                      >
                        Start Remote
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={handleStopClient}
                        disabled={!clientRunning}
                        className="px-3 text-xs"
                      >
                        Stop
                      </Button>
                    </div>
                  </div>
                </div>
              </GlassCard>

              {/* Main Transcription */}
              <GlassCard
                title="Main Transcription"
                className="flex-none"
                action={
                  <button
                    onClick={() => live.toggleMute()}
                    className={`flex h-7 w-7 items-center justify-center rounded-lg border transition-colors ${live.muted ? 'border-red-500/30 bg-red-500/20 text-red-400 hover:bg-red-500/30' : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'}`}
                    title={live.muted ? 'Unmute' : 'Mute'}
                  >
                    {live.muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                  </button>
                }
              >
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-6 p-1">
                    <div className="flex min-w-0 flex-1 flex-col">
                      <label className="mb-2 ml-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
                        Source Language
                      </label>
                      <div className="flex items-center gap-2">
                        <div className="bg-accent-magenta/10 text-accent-magenta border-accent-magenta/5 rounded-xl border p-2.5 shadow-inner">
                          <Languages size={18} />
                        </div>
                        <CustomSelect
                          value={mainLanguage}
                          onChange={handleMainLanguageChange}
                          options={mainLanguageOptions}
                          accentColor="magenta"
                          className="focus:ring-accent-magenta flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white transition-all outline-none hover:border-white/20 focus:ring-1"
                        />
                      </div>
                    </div>
                    <div className="mb-1 h-12 w-px self-end bg-white/10"></div>
                    <div
                      className="flex min-w-25 flex-col items-center"
                      title={canTranslate ? '' : 'Current model does not support translation'}
                    >
                      <label
                        className={`mt-1 mb-2 text-center text-[9px] font-bold tracking-widest whitespace-nowrap uppercase ${canTranslate ? 'text-slate-500' : 'text-slate-600 line-through'}`}
                      >
                        {isCanaryMainBidi ? 'Translate to' : 'Translate to English'}
                      </label>
                      <div className="flex h-11.5 items-center justify-center">
                        {isCanaryMainBidi ? (
                          <CustomSelect
                            value={mainBidiTarget}
                            onChange={setMainBidiTarget}
                            options={['Off', ...CANARY_TRANSLATION_TARGETS]}
                            accentColor="magenta"
                            className="focus:ring-accent-magenta h-full min-w-25 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                          />
                        ) : (
                          <AppleSwitch
                            checked={mainTranslate && canTranslate}
                            onChange={setMainTranslate}
                            size="sm"
                            disabled={!canTranslate}
                          />
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Record / Stop Button */}
                  <div className="flex flex-col gap-2">
                    {(serverRunning || isRemoteMode) && serverConnection.details?.gpu_error && (
                      <div className="flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                        <span>
                          {serverConnection.details.gpu_error_action ??
                            'GPU unavailable — restart your computer to reset the GPU driver, or switch to CPU mode in Settings > Server.'}
                        </span>
                      </div>
                    )}
                    {(serverRunning || isRemoteMode) &&
                      serverConnection.ready &&
                      mainModelDisabled && (
                        <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                          Main model not selected.
                        </div>
                      )}
                    {isRemoteMode && serverConnection.ready && !admin.status && !admin.loading && (
                      <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                        <span>
                          Auth token not configured — enter the server token in Settings to enable
                          recording.
                        </span>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      {canStartRecording ? (
                        <Button
                          variant="primary"
                          className="bg-accent-cyan/20 border-accent-cyan/40 text-accent-cyan hover:bg-accent-cyan/30 w-full"
                          icon={
                            isConnecting ? (
                              <Loader2 size={16} className="animate-spin" />
                            ) : (
                              <Mic size={16} />
                            )
                          }
                          onClick={handleStartRecording}
                          disabled={
                            isLive || !clientRunning || !serverConnection.ready || mainModelDisabled
                          }
                        >
                          {isConnecting ? 'Connecting...' : 'Start Recording'}
                        </Button>
                      ) : (
                        <>
                          <Button
                            variant="danger"
                            className="w-full"
                            icon={
                              isProcessing ? (
                                <Loader2 size={16} className="animate-spin" />
                              ) : (
                                <Square size={16} />
                              )
                            }
                            onClick={handleStopRecording}
                            disabled={isProcessing}
                          >
                            {isProcessing
                              ? transcription.processingProgress?.total
                                ? `Processing... ${transcription.processingProgress.current}/${transcription.processingProgress.total}`
                                : 'Processing...'
                              : 'Stop Recording'}
                          </Button>
                          {(isConnecting || isRecording || isProcessing) && (
                            <Button
                              variant="secondary"
                              className="shrink-0"
                              icon={<X size={16} />}
                              onClick={handleCancelProcessing}
                            >
                              Cancel
                            </Button>
                          )}
                        </>
                      )}
                      {transcription.vadActive && (
                        <span className="animate-pulse font-mono text-xs whitespace-nowrap text-green-400">
                          VAD Active
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Transcription Result */}
                  {transcription.result && (
                    <div className="space-y-2">
                      <div className="selectable-text custom-scrollbar max-h-32 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300">
                        {transcription.result.text}
                        {transcription.result.language && (
                          <div className="mt-2 text-xs text-slate-500">
                            Detected: {transcription.result.language} &middot;{' '}
                            {transcription.result.duration?.toFixed(1)}s
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<Copy size={14} />}
                          onClick={handleCopyTranscription}
                        >
                          Copy
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<Download size={14} />}
                          onClick={handleDownloadTranscription}
                        >
                          Download
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Errors */}
                  {transcription.error && (
                    <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                      {transcription.error}
                    </div>
                  )}
                </div>
              </GlassCard>

              {/* Audio Configuration */}
              <GlassCard title="Audio Configuration" className="flex-none">
                <div className="space-y-6">
                  <div>
                    <label className="mb-2 ml-1 block text-xs font-medium tracking-wider text-slate-400 uppercase">
                      Active Input Source
                    </label>
                    <div className="relative flex rounded-xl border border-white/5 bg-black/60 p-1 shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)]">
                      <div
                        className={`absolute top-1 bottom-1 z-0 w-[calc(50%-4px)] rounded-lg border-t border-white/10 bg-slate-700 shadow-[0_2px_8px_rgba(0,0,0,0.4)] transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] ${audioSource === 'system' ? 'translate-x-[calc(100%+4px)]' : 'translate-x-0'}`}
                      />
                      <button
                        onClick={() => handleAudioSourceChange('mic')}
                        className={`relative z-10 flex flex-1 items-center justify-center space-x-2.5 py-2.5 text-sm font-semibold transition-all duration-300 ${audioSource === 'mic' ? 'text-white' : 'text-slate-500 hover:text-slate-300'}`}
                      >
                        <Mic
                          size={18}
                          className={`transition-all duration-300 ${audioSource === 'mic' ? 'text-accent-cyan scale-110 drop-shadow-[0_0_8px_rgba(34,211,238,0.6)]' : ''}`}
                        />
                        <span>Microphone</span>
                      </button>
                      <button
                        onClick={() => handleAudioSourceChange('system')}
                        className={`relative z-10 flex flex-1 items-center justify-center space-x-2.5 py-2.5 text-sm font-semibold transition-all duration-300 ${audioSource === 'system' ? 'text-white' : 'text-slate-500 hover:text-slate-300'}`}
                      >
                        <Laptop
                          size={18}
                          className={`transition-all duration-300 ${audioSource === 'system' ? 'text-accent-cyan scale-110 drop-shadow-[0_0_8px_rgba(34,211,238,0.6)]' : ''}`}
                        />
                        <span>System Audio</span>
                      </button>
                    </div>
                  </div>
                  <div className="h-px w-full bg-white/5"></div>
                  <div className="space-y-4">
                    <div
                      className={`rounded-xl border p-3 transition-all duration-300 ${audioSource === 'mic' ? 'bg-accent-cyan/5 border-accent-cyan/20 shadow-[0_0_10px_rgba(34,211,238,0.05)]' : 'border-transparent bg-transparent hover:bg-white/5'}`}
                    >
                      <div className="mb-2 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Mic
                            size={14}
                            className={
                              audioSource === 'mic' ? 'text-accent-cyan' : 'text-slate-500'
                            }
                          />
                          <label
                            className={`text-xs font-medium ${audioSource === 'mic' ? 'text-white' : 'text-slate-400'}`}
                          >
                            Microphone Device
                          </label>
                        </div>
                        {audioSource === 'mic' && (
                          <span className="bg-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-black uppercase">
                            Live
                          </span>
                        )}
                      </div>
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="min-w-0 flex-1">
                          <CustomSelect
                            value={micDevice}
                            onChange={handleMicDeviceChange}
                            options={micDevices.length > 0 ? micDevices : ['Default Microphone']}
                            className="focus:ring-accent-cyan w-full min-w-0 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white transition-shadow outline-none hover:border-white/20 focus:ring-1"
                          />
                        </div>
                        <Button
                          variant="secondary"
                          size="icon"
                          className="shrink-0"
                          icon={<RefreshCw size={14} />}
                          onClick={enumerateDevices}
                        />
                      </div>
                    </div>
                    <div
                      className={`rounded-xl border p-3 transition-all duration-300 ${audioSource === 'system' ? 'bg-accent-cyan/5 border-accent-cyan/20 shadow-[0_0_10px_rgba(34,211,238,0.05)]' : 'border-transparent bg-transparent hover:bg-white/5'}`}
                    >
                      <div className="mb-2 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Laptop
                            size={14}
                            className={
                              audioSource === 'system' ? 'text-accent-cyan' : 'text-slate-500'
                            }
                          />
                          <label
                            className={`text-xs font-medium ${audioSource === 'system' ? 'text-white' : 'text-slate-400'}`}
                          >
                            System Audio
                          </label>
                        </div>
                        {audioSource === 'system' && (
                          <span className="bg-accent-cyan rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-black uppercase">
                            Live
                          </span>
                        )}
                      </div>
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="min-w-0 flex-1">
                          {isLinux ? (
                            <CustomSelect
                              value={sysDevice}
                              onChange={handleSystemDeviceChange}
                              options={sysDevices.length > 0 ? sysDevices : ['Default Output']}
                              className="focus:ring-accent-cyan w-full min-w-0 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white transition-shadow outline-none hover:border-white/20 focus:ring-1"
                            />
                          ) : (
                            <div className="w-full min-w-0 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/60 select-none">
                              All System Audio
                            </div>
                          )}
                        </div>
                        {isLinux && (
                          <Button
                            variant="secondary"
                            size="icon"
                            className="shrink-0"
                            icon={<RefreshCw size={14} />}
                            onClick={fetchSinks}
                          />
                        )}
                      </div>
                      {/* Capture gain slider — boost or attenuate system audio input */}
                      {audioSource === 'system' && (
                        <div className="mt-2.5">
                          <div className="mb-1 flex items-center justify-between">
                            <label className="text-[11px] font-medium text-slate-400">
                              Capture Gain
                            </label>
                            <div className="flex items-center gap-1.5">
                              {monitorVolumePct !== null && (
                                <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-500 tabular-nums">
                                  src {monitorVolumePct}%
                                </span>
                              )}
                              <span className="min-w-[3ch] text-right text-[11px] text-slate-300 tabular-nums">
                                {captureGain.toFixed(2)}x
                              </span>
                            </div>
                          </div>
                          <input
                            type="range"
                            min={0.25}
                            max={5}
                            step={0.25}
                            value={captureGain}
                            onChange={(e) => handleCaptureGainChange(parseFloat(e.target.value))}
                            className="ts-gain-slider h-1 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </GlassCard>
            </div>
          </div>

          {/* Left Bottom Scroll Indicator */}
          <div
            className={`pointer-events-none absolute right-3 bottom-0 left-0 z-20 h-6 overflow-hidden rounded-b-2xl transition-opacity duration-300 ${leftScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}
          >
            <div
              className="h-full w-full bg-linear-to-t from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
          {/* Left Bottom Corner Mask */}
          <div
            className="pointer-events-none absolute right-3 bottom-0 z-20 h-4 w-4"
            style={{
              ...maskStyle,
              maskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)',
              WebkitMaskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)',
            }}
          />
        </div>

        {/* Right Column: Visualizer & Live Mode (60%) */}
        <div className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl">
          {/* Right Top Scroll Indicator */}
          <div
            className={`pointer-events-none absolute top-0 right-3 left-0 z-20 h-6 overflow-hidden rounded-t-2xl transition-opacity duration-300 ${rightScrollState.top ? 'opacity-100' : 'opacity-0'}`}
          >
            <div
              className="h-full w-full bg-linear-to-b from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
          {/* Right Top Corner Mask */}
          <div
            className="pointer-events-none absolute top-0 right-3 z-20 h-4 w-4"
            style={{
              ...maskStyle,
              maskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)',
              WebkitMaskImage:
                'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)',
            }}
          />

          {/* Right Column Scroll Container */}
          <div
            ref={rightScrollRef}
            className="custom-scrollbar flex-1 overflow-y-auto pt-0 pr-3 pb-0"
          >
            <div
              ref={rightContentRef}
              className="flex min-h-full flex-col"
              style={
                rightColumnBaselineHeight
                  ? { minHeight: `${rightColumnBaselineHeight}px` }
                  : undefined
              }
            >
              {/* Visualizer Card */}
              <GlassCard className="relative z-10 mb-6 flex-none overflow-visible">
                <div className="mb-4 flex shrink-0 items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-accent-cyan/10 text-accent-cyan rounded-full p-2">
                      <Activity size={20} className={isLive ? 'animate-pulse' : ''} />
                    </div>
                    <div>
                      <h3 className="font-semibold text-white">Audio Visualizer</h3>
                      <p className="text-xs text-slate-400">
                        {activeAnalyser ? 'Live — listening' : 'Idle — awaiting input'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1 rounded-lg border border-white/5 bg-black/20 p-0.5">
                      <button
                        onClick={() =>
                          setVisualizerAmplitudeScale((s) => Math.max(0.25, +(s - 0.25).toFixed(2)))
                        }
                        className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                        title="Decrease sensitivity"
                      >
                        <Minus size={14} />
                      </button>
                      <button
                        onClick={() =>
                          setVisualizerAmplitudeScale((s) => Math.min(4, +(s + 0.25).toFixed(2)))
                        }
                        className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                        title="Increase sensitivity"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                    <button
                      onClick={() => setIsFullscreenVisualizerOpen(true)}
                      className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                      title="Fullscreen"
                    >
                      <Maximize2 size={14} />
                    </button>
                  </div>
                </div>
                <AudioVisualizer
                  analyserNode={activeAnalyser}
                  amplitudeScale={visualizerAmplitudeScale}
                  isActive={!!activeAnalyser}
                />
              </GlassCard>

              {/* Live Mode (Text + Controls) */}
              {isLivePoppedOut ? (
                <>
                  {/* Greyed-out placeholder while popped out */}
                  <GlassCard
                    className="flex min-h-[calc(100vh-30rem)] flex-1 flex-col opacity-40 transition-all duration-300"
                    title="Live Mode"
                    action={
                      <button
                        onClick={() => setIsLivePoppedOut(false)}
                        className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                        title="Return Live Mode to this window"
                      >
                        <Minimize2 size={14} />
                      </button>
                    }
                  >
                    <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-white/5 bg-black/20">
                      <div className="flex flex-col items-center space-y-3 text-center text-slate-500 select-none">
                        <ExternalLink size={48} strokeWidth={1} />
                        <p className="text-sm">Live Mode is in a separate window.</p>
                        <button
                          onClick={() => setIsLivePoppedOut(false)}
                          className="mt-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                        >
                          Return here
                        </button>
                      </div>
                    </div>
                  </GlassCard>
                  {/* Pop-out window with live content */}
                  <PopOutWindow
                    isOpen={isLivePoppedOut}
                    onClose={() => setIsLivePoppedOut(false)}
                    title="Live Mode — Transcription Suite"
                    width={520}
                    height={650}
                  >
                    <div className="flex h-full flex-col bg-[#0f172a] p-4">
                      {/* Pop-out header bar */}
                      <div className="mb-4 flex shrink-0 items-center justify-between">
                        <h2 className="text-sm font-semibold tracking-wide text-white/90">
                          Live Mode
                        </h2>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => live.toggleMute()}
                            className={`flex h-7 w-7 items-center justify-center rounded-lg border transition-colors ${live.muted ? 'border-red-500/30 bg-red-500/20 text-red-400 hover:bg-red-500/30' : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'}`}
                            title={live.muted ? 'Unmute' : 'Mute'}
                          >
                            {live.muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                          </button>
                          <button
                            onClick={() => setIsLivePoppedOut(false)}
                            className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                            title="Return to main window"
                          >
                            <Minimize2 size={14} />
                          </button>
                        </div>
                      </div>
                      {/* Controls Toolbar */}
                      <div className="custom-scrollbar no-scrollbar mb-4 flex shrink-0 flex-nowrap items-center gap-2 overflow-x-auto border-b border-white/5 p-1 pb-4">
                        <div className="flex h-8 shrink-0 items-center gap-2">
                          <span
                            className={`text-xs font-bold tracking-wider uppercase ${isLive ? 'text-green-400' : 'text-slate-500'}`}
                          >
                            {live.status === 'starting'
                              ? 'Loading...'
                              : isLive
                                ? 'Active'
                                : 'Offline'}
                          </span>
                          <span
                            title={
                              !isLive && liveModeDisabledReason ? liveModeDisabledReason : undefined
                            }
                          >
                            <AppleSwitch
                              checked={isLive}
                              onChange={handleLiveToggle}
                              size="sm"
                              disabled={
                                !isLive &&
                                (!clientRunning ||
                                  !serverConnection.ready ||
                                  liveModelDisabled ||
                                  !liveModeWhisperOnlyCompatible)
                              }
                            />
                          </span>
                        </div>
                        <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                        <div className="flex h-8 shrink-0 items-center gap-2">
                          <div className="bg-accent-magenta/10 text-accent-magenta border-accent-magenta/5 flex aspect-square h-full items-center justify-center rounded-lg border">
                            <Languages size={15} />
                          </div>
                          <CustomSelect
                            value={liveLanguage}
                            onChange={handleLiveLanguageChange}
                            options={liveLanguageOptions}
                            accentColor="magenta"
                            className="focus:ring-accent-magenta h-full min-w-32.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                          />
                        </div>
                        <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                        <div
                          className="flex h-8 shrink-0 items-center gap-2"
                          title={
                            canTranslateLive ? '' : 'Current model does not support translation'
                          }
                        >
                          <span
                            className={`text-[9px] font-bold tracking-widest whitespace-nowrap uppercase ${canTranslateLive ? 'text-slate-500' : 'text-slate-600 line-through'}`}
                          >
                            {isCanaryLiveBidi ? 'Translate to' : 'Translate to English'}
                          </span>
                          {isCanaryLiveBidi ? (
                            <CustomSelect
                              value={liveBidiTarget}
                              onChange={setLiveBidiTarget}
                              options={['Off', ...CANARY_TRANSLATION_TARGETS]}
                              accentColor="magenta"
                              className="focus:ring-accent-magenta h-full min-w-25 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                            />
                          ) : (
                            <AppleSwitch
                              checked={liveTranslate && canTranslateLive}
                              onChange={setLiveTranslate}
                              size="sm"
                              disabled={!canTranslateLive}
                            />
                          )}
                        </div>
                        <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Copy size={14} />}
                          onClick={() => {
                            writeToClipboard(live.getText());
                            live.clearHistory();
                          }}
                          className="ml-auto h-8 shrink-0 whitespace-nowrap"
                        >
                          Copy
                        </Button>
                      </div>
                      {/* Transcript Area */}
                      <div
                        ref={liveTranscriptRef}
                        className="custom-scrollbar selectable-text relative min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300 shadow-inner"
                      >
                        {(serverRunning || isRemoteMode) &&
                          serverConnection.ready &&
                          liveModelDisabled && (
                            <div className="mb-3 text-xs text-amber-300">
                              Live model not selected.
                            </div>
                          )}
                        {!liveModelDisabled && !liveModeWhisperOnlyCompatible && (
                          <div className="mb-3 text-xs text-red-400">
                            {liveModeUnsupportedMessage}
                          </div>
                        )}
                        {isLive || live.sentences.length > 0 || live.partial ? (
                          <>
                            {live.statusMessage && (
                              <div className="text-accent-cyan mb-3 flex animate-pulse items-center gap-2">
                                <Loader2 size={14} className="animate-spin" />
                                <span className="text-xs">{live.statusMessage}</span>
                              </div>
                            )}
                            {live.sentences.map((s, i) => (
                              <div key={i} className="mb-2">
                                {!hideTimestamps && (
                                  <span className="mr-2 text-slate-500 select-none">
                                    {new Date(s.timestamp).toLocaleTimeString('en-US', {
                                      hour12: false,
                                    })}
                                  </span>
                                )}
                                <span>{s.text}</span>
                              </div>
                            ))}
                            {live.partial && (
                              <div className="mb-2 opacity-60">
                                {!hideTimestamps && (
                                  <span className="mr-2 text-slate-500 select-none">
                                    {new Date().toLocaleTimeString('en-US', { hour12: false })}
                                  </span>
                                )}
                                <span className="italic">{live.partial}</span>
                                <span className="bg-accent-cyan ml-0.5 inline-block h-4 w-1.5 animate-pulse align-text-bottom"></span>
                              </div>
                            )}
                            {live.sentences.length === 0 &&
                              !live.partial &&
                              !live.statusMessage && (
                                <div className="absolute inset-4 flex flex-col items-center justify-center space-y-3 text-slate-600 opacity-60 select-none">
                                  <Activity size={32} strokeWidth={1} className="animate-pulse" />
                                  <p>Listening... speak to see transcription.</p>
                                </div>
                              )}
                            {live.error && (
                              <div className="mt-2 text-xs text-red-400">{live.error}</div>
                            )}
                          </>
                        ) : (
                          <div className="absolute inset-4 flex items-center justify-center">
                            <div className="flex flex-col items-center space-y-3 text-center text-slate-600 opacity-60 select-none">
                              <Radio size={48} strokeWidth={1} />
                              <p>Live mode is off. Toggle the switch to start.</p>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </PopOutWindow>
                </>
              ) : (
                <GlassCard
                  className="flex min-h-[calc(100vh-30rem)] flex-1 flex-col transition-all duration-300"
                  title="Live Mode"
                  action={
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setIsLivePoppedOut(true)}
                        className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                        title="Pop out into separate window"
                      >
                        <ExternalLink size={14} />
                      </button>
                      <button
                        onClick={() => live.toggleMute()}
                        className={`flex h-7 w-7 items-center justify-center rounded-lg border transition-colors ${live.muted ? 'border-red-500/30 bg-red-500/20 text-red-400 hover:bg-red-500/30' : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'}`}
                        title={live.muted ? 'Unmute' : 'Mute'}
                      >
                        {live.muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                      </button>
                    </div>
                  }
                >
                  {/* Live Mode Controls Toolbar */}
                  <div className="custom-scrollbar no-scrollbar mb-4 flex flex-none flex-nowrap items-center gap-2 overflow-x-auto border-b border-white/5 p-1 pb-4">
                    <div className="flex h-8 shrink-0 items-center gap-2">
                      <span
                        className={`text-xs font-bold tracking-wider uppercase ${isLive ? 'text-green-400' : 'text-slate-500'}`}
                      >
                        {live.status === 'starting' ? 'Loading...' : isLive ? 'Active' : 'Offline'}
                      </span>
                      <span
                        title={
                          !isLive && liveModeDisabledReason ? liveModeDisabledReason : undefined
                        }
                      >
                        <AppleSwitch
                          checked={isLive}
                          onChange={handleLiveToggle}
                          size="sm"
                          disabled={
                            !isLive &&
                            (!clientRunning ||
                              !serverConnection.ready ||
                              liveModelDisabled ||
                              !liveModeWhisperOnlyCompatible)
                          }
                        />
                      </span>
                    </div>
                    <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                    <div className="flex h-8 shrink-0 items-center gap-2">
                      <div className="bg-accent-magenta/10 text-accent-magenta border-accent-magenta/5 flex aspect-square h-full items-center justify-center rounded-lg border">
                        <Languages size={15} />
                      </div>
                      <CustomSelect
                        value={liveLanguage}
                        onChange={handleLiveLanguageChange}
                        options={liveLanguageOptions}
                        accentColor="magenta"
                        className="focus:ring-accent-magenta h-full min-w-32.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                      />
                    </div>
                    <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                    <div
                      className="flex h-8 shrink-0 items-center gap-2"
                      title={canTranslateLive ? '' : 'Current model does not support translation'}
                    >
                      <span
                        className={`text-[9px] font-bold tracking-widest whitespace-nowrap uppercase ${canTranslateLive ? 'text-slate-500' : 'text-slate-600 line-through'}`}
                      >
                        {isCanaryLiveBidi ? 'Translate to' : 'Translate to English'}
                      </span>
                      {isCanaryLiveBidi ? (
                        <CustomSelect
                          value={liveBidiTarget}
                          onChange={setLiveBidiTarget}
                          options={['Off', ...CANARY_TRANSLATION_TARGETS]}
                          accentColor="magenta"
                          className="focus:ring-accent-magenta h-full min-w-25 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                        />
                      ) : (
                        <AppleSwitch
                          checked={liveTranslate && canTranslateLive}
                          onChange={setLiveTranslate}
                          size="sm"
                          disabled={!canTranslateLive}
                        />
                      )}
                    </div>
                    <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Copy size={14} />}
                      onClick={() => {
                        writeToClipboard(live.getText());
                        live.clearHistory();
                      }}
                      className="ml-auto h-8 shrink-0 whitespace-nowrap"
                    >
                      Copy
                    </Button>
                  </div>

                  {/* Transcript Area */}
                  <div
                    ref={liveTranscriptRef}
                    className="custom-scrollbar selectable-text relative min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300 shadow-inner"
                  >
                    {(serverRunning || isRemoteMode) &&
                      serverConnection.ready &&
                      liveModelDisabled && (
                        <div className="mb-3 text-xs text-amber-300">Live model not selected.</div>
                      )}
                    {!liveModelDisabled && !liveModeWhisperOnlyCompatible && (
                      <div className="mb-3 text-xs text-red-400">{liveModeUnsupportedMessage}</div>
                    )}
                    {isLive || live.sentences.length > 0 || live.partial ? (
                      <>
                        {live.statusMessage && (
                          <div className="text-accent-cyan mb-3 flex animate-pulse items-center gap-2">
                            <Loader2 size={14} className="animate-spin" />
                            <span className="text-xs">{live.statusMessage}</span>
                          </div>
                        )}
                        {live.sentences.map((s, i) => (
                          <div key={i} className="mb-2">
                            {!hideTimestamps && (
                              <span className="mr-2 text-slate-500 select-none">
                                {new Date(s.timestamp).toLocaleTimeString('en-US', {
                                  hour12: false,
                                })}
                              </span>
                            )}
                            <span>{s.text}</span>
                          </div>
                        ))}
                        {live.partial && (
                          <div className="mb-2 opacity-60">
                            {!hideTimestamps && (
                              <span className="mr-2 text-slate-500 select-none">
                                {new Date().toLocaleTimeString('en-US', { hour12: false })}
                              </span>
                            )}
                            <span className="italic">{live.partial}</span>
                            <span className="bg-accent-cyan ml-0.5 inline-block h-4 w-1.5 animate-pulse align-text-bottom"></span>
                          </div>
                        )}
                        {live.sentences.length === 0 && !live.partial && !live.statusMessage && (
                          <div className="absolute inset-4 flex flex-col items-center justify-center space-y-3 text-slate-600 opacity-60 select-none">
                            <Activity size={32} strokeWidth={1} className="animate-pulse" />
                            <p>Listening... speak to see transcription.</p>
                          </div>
                        )}
                        {live.error && (
                          <div className="mt-2 text-xs text-red-400">{live.error}</div>
                        )}
                      </>
                    ) : (
                      <div className="absolute inset-4 flex items-center justify-center">
                        <div className="flex flex-col items-center space-y-3 text-center text-slate-600 opacity-60 select-none">
                          <Radio size={48} strokeWidth={1} />
                          <p>Live mode is off. Toggle the switch to start.</p>
                        </div>
                      </div>
                    )}
                  </div>
                </GlassCard>
              )}
            </div>
          </div>

          {/* Right Bottom Scroll Indicator */}
          <div
            className={`pointer-events-none absolute right-3 bottom-0 left-0 z-20 h-6 overflow-hidden rounded-b-2xl transition-opacity duration-300 ${rightScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}
          >
            <div
              className="h-full w-full bg-linear-to-t from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
          {/* Right Bottom Corner Mask */}
          <div
            className="pointer-events-none absolute right-3 bottom-0 z-20 h-4 w-4"
            style={{
              ...maskStyle,
              maskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)',
              WebkitMaskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)',
            }}
          />
        </div>
      </div>

      {/* Fullscreen Visualizer Modal */}
      <FullscreenVisualizer
        isOpen={isFullscreenVisualizerOpen}
        onClose={() => setIsFullscreenVisualizerOpen(false)}
        analyserNode={activeAnalyser}
      />
    </div>
  );
};
