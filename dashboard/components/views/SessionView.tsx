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
  Terminal,
  Activity,
  Server,
  Laptop,
  Loader2,
  X,
  Download,
} from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { StatusLight } from '../ui/StatusLight';
import { AudioVisualizer } from '../AudioVisualizer';
import { LogTerminal } from '../ui/LogTerminal';
import { CustomSelect } from '../ui/CustomSelect';
import { FullscreenVisualizer } from './FullscreenVisualizer';
import { useLanguages } from '../../src/hooks/useLanguages';
import { useTranscription } from '../../src/hooks/useTranscription';
import { useLiveMode } from '../../src/hooks/useLiveMode';
import { useDockerContext } from '../../src/hooks/DockerContext';
import { useTraySync } from '../../src/hooks/useTraySync';
import type { ServerConnectionInfo } from '../../src/hooks/useServerStatus';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useClientDebugLogs } from '../../src/hooks/useClientDebugLogs';
import { apiClient } from '../../src/api/client';
import { getConfig, setConfig } from '../../src/config/store';
import { logClientEvent } from '../../src/services/clientDebugLog';
import { supportsTranslation } from '../../src/services/modelCapabilities';

interface SessionViewProps {
  serverConnection: ServerConnectionInfo;
  clientRunning: boolean;
  setClientRunning: (running: boolean) => void;
}

export const SessionView: React.FC<SessionViewProps> = ({
  serverConnection,
  clientRunning,
  setClientRunning,
}) => {
  // Global State
  const [showLogs, setShowLogs] = useState(false);
  const [logsRendered, setLogsRendered] = useState(false);
  const [logsVisible, setLogsVisible] = useState(false);
  const [isFullscreenVisualizerOpen, setIsFullscreenVisualizerOpen] = useState(false);

  // Runtime profile (read from persisted config)
  const [runtimeProfile, setRuntimeProfile] = useState<'gpu' | 'cpu'>('gpu');
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config
        .get('server.runtimeProfile')
        .then((val: unknown) => {
          if (val === 'gpu' || val === 'cpu') setRuntimeProfile(val);
        })
        .catch(() => {});
    }
  }, []);

  // Real language list from server
  const { languages, loading: languagesLoading } = useLanguages();
  const languageOptions = useMemo(() => {
    // useLanguages already includes 'Auto Detect' — deduplicate by filtering it out before prepending
    const filtered = languages.filter((l) => l.code !== 'auto').map((l) => l.name);
    return ['Auto Detect', ...filtered];
  }, [languages]);

  // Transcription hooks
  const transcription = useTranscription();
  const live = useLiveMode();
  const { logs: clientLogs, logPath: clientLogPath } = useClientDebugLogs();

  // Active analyser: live mode takes priority when active, then one-shot
  const activeAnalyser = live.analyser ?? transcription.analyser;

  // Audio device enumeration
  const [micDevices, setMicDevices] = useState<string[]>([]);
  const [sysDevices, setSysDevices] = useState<string[]>([]);
  const [micDeviceIds, setMicDeviceIds] = useState<Record<string, string>>({});

  // Desktop sources for system audio capture (Electron only)
  const [desktopSources, setDesktopSources] = useState<
    Array<{ id: string; name: string; thumbnail: string }>
  >([]);
  const [desktopSourceIds, setDesktopSourceIds] = useState<Record<string, string>>({});

  // Audio Configuration State
  const [audioSource, setAudioSource] = useState<'mic' | 'system'>('mic');
  const [micDevice, setMicDevice] = useState('Default Microphone');
  const [sysDevice, setSysDevice] = useState('Default Output');
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

  // Fetch desktop sources when system audio is selected (Electron only)
  const fetchDesktopSources = useCallback(async () => {
    if (!window.electronAPI?.audio?.getDesktopSources) return;
    try {
      const sources = await window.electronAPI.audio.getDesktopSources();
      setDesktopSources(sources);
      const idMap: Record<string, string> = {};
      sources.forEach((s) => {
        idMap[s.name] = s.id;
      });
      setDesktopSourceIds(idMap);
      const sourceNames = sources.map((s) => s.name);
      const options = sourceNames.length > 0 ? sourceNames : ['No sources available'];
      setSysDevices(options);
      const nextSystemDevice = pickPreferredOption(
        options,
        sysDevice,
        persistedSelectionsRef.current.sysDevice,
      );
      if (nextSystemDevice !== sysDevice) setSysDevice(nextSystemDevice);
    } catch (err) {
      console.error('Failed to fetch desktop sources:', err);
      setSysDevices(['No sources available']);
    }
  }, [sysDevice, pickPreferredOption]);

  // Refresh desktop sources when switching to system audio
  useEffect(() => {
    if (audioSource === 'system') {
      fetchDesktopSources();
    }
  }, [audioSource, fetchDesktopSources]);

  const enumerateDevices = useCallback(async () => {
    try {
      // Request permission first (needed to get labels)
      await navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then((s) => s.getTracks().forEach((t) => t.stop()));
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter((d) => d.kind === 'audioinput' && d.label);
      const audioOutputs = devices
        .filter((d) => d.kind === 'audiooutput' && d.label)
        .map((d) => d.label);
      const inputLabels = audioInputs.map((d) => d.label);
      const idMap: Record<string, string> = {};
      audioInputs.forEach((d) => {
        idMap[d.label] = d.deviceId;
      });
      const micOptions = inputLabels.length > 0 ? inputLabels : ['Default Microphone'];
      const outputOptions = audioOutputs.length > 0 ? audioOutputs : ['Default Output'];
      setMicDevices(micOptions);
      setMicDeviceIds(idMap);
      setSysDevices(outputOptions);
      const nextMicDevice = pickPreferredOption(
        micOptions,
        micDevice,
        persistedSelectionsRef.current.micDevice,
      );
      const nextSystemDevice = pickPreferredOption(
        outputOptions,
        sysDevice,
        persistedSelectionsRef.current.sysDevice,
      );
      if (nextMicDevice !== micDevice) setMicDevice(nextMicDevice);
      if (nextSystemDevice !== sysDevice) setSysDevice(nextSystemDevice);
    } catch {
      setMicDevices(['Default Microphone']);
      setSysDevices(['Default Output']);
    }
  }, [micDevice, sysDevice, pickPreferredOption]);

  useEffect(() => {
    enumerateDevices();
  }, [enumerateDevices]);

  // Control Center State — real Docker container status
  const docker = useDockerContext();
  const serverRunning = docker.container.running;
  // Client connection state — tracked at App level via props
  const admin = useAdminStatus();
  const [modelsOperationPending, setModelsOperationPending] = useState(false);

  // Active model name (for capability checks & tray tooltip)
  const activeModel = admin.status?.config?.transcription?.model ?? null;
  const canTranslate = supportsTranslation(activeModel);

  // Main Transcription State
  const [mainLanguage, setMainLanguage] = useState('Auto Detect');
  const [mainTranslate, setMainTranslate] = useState(false);

  // Live Mode State
  const isLive = live.status !== 'idle' && live.status !== 'error';
  const [liveLanguage, setLiveLanguage] = useState('English');
  const [liveTranslate, setLiveTranslate] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      const [
        savedAudioSource,
        savedMicDevice,
        savedSystemDevice,
        savedMainLanguage,
        savedLiveLanguage,
      ] = await Promise.all([
        getConfig<'mic' | 'system'>('session.audioSource'),
        getConfig<string>('session.micDevice'),
        getConfig<string>('session.systemDevice'),
        getConfig<string>('session.mainLanguage'),
        getConfig<string>('session.liveLanguage'),
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

  const handleSystemDeviceChange = useCallback((device: string) => {
    setSysDevice(device);
    persistedSelectionsRef.current.sysDevice = device;
    void setConfig('session.systemDevice', device).catch(() => {});
  }, []);

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
    if (!canTranslate) {
      setMainTranslate(false);
      setLiveTranslate(false);
    }
  }, [canTranslate]);

  useEffect(() => {
    if (languagesLoading) return;
    if (!languageOptions.includes(mainLanguage)) {
      setMainLanguage('Auto Detect');
    }
    if (!languageOptions.includes(liveLanguage)) {
      setLiveLanguage('English');
    }
  }, [languagesLoading, languageOptions, mainLanguage, liveLanguage]);

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
      ? 'Server Unreachable'
      : transcription.status === 'connecting' || live.status === 'connecting'
        ? 'Connecting...'
        : 'Disconnected';

  // Client start/stop handlers (mirrors v0.5.6 ClientControlMixin)
  const handleStartClientLocal = useCallback(async () => {
    await setConfig('connection.useRemote', false);
    await setConfig('connection.useHttps', false);
    await setConfig('connection.localHost', 'localhost');
    await setConfig('connection.port', 8000);
    await apiClient.syncFromConfig();
    setClientRunning(true);
    logClientEvent('Client', 'Configured local connection (localhost:8000)');
    serverConnection.refresh();
  }, [serverConnection]);

  const handleStartClientRemote = useCallback(async () => {
    await setConfig('connection.useRemote', true);
    await apiClient.syncFromConfig();
    setClientRunning(true);
    logClientEvent('Client', 'Configured remote connection');
    serverConnection.refresh();
  }, [serverConnection]);

  const handleStopClient = useCallback(() => {
    setClientRunning(false);
    logClientEvent('Client', 'Client link stopped', 'warning');
  }, []);

  const handleUnloadAllModels = useCallback(async () => {
    setModelsOperationPending(true);
    try {
      await Promise.allSettled([apiClient.unloadModels(), apiClient.unloadLLMModel()]);
      logClientEvent('Client', 'Requested unload for all models', 'warning');
      admin.refresh();
      serverConnection.refresh();
    } finally {
      setModelsOperationPending(false);
    }
  }, [admin, serverConnection]);

  // System Health Check for Visual Effects
  const isSystemHealthy = serverRunning && clientConnected;

  // Sync tray icon state with application state
  useTraySync({
    serverStatus: serverRunning ? 'active' : 'inactive',
    containerRunning: serverRunning,
    transcriptionStatus: transcription.status,
    liveStatus: live.status,
    muted: live.muted,
    activeModel: activeModel ?? undefined,
    onStartRecording: () => transcription.start(),
    onStopRecording: () => {
      if (isLive) live.stop();
      else transcription.stop();
    },
    onToggleMute: () => live.toggleMute(),
    onTranscribeFile: async (filePath: string) => {
      try {
        const { name, buffer, mimeType } = await window.electronAPI!.app.readLocalFile(filePath);
        const file = new File([buffer], name, { type: mimeType });
        await apiClient.uploadAndTranscribe(file, { enable_diarization: true });
      } catch (err: any) {
        console.error('Tray transcribe file failed:', err);
      }
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
    if (!canStartRecording) return;
    transcription.reset();
    const isSystemAudio = audioSource === 'system';
    transcription.start({
      language: resolveLanguage(mainLanguage),
      deviceId: isSystemAudio ? undefined : micDeviceIds[micDevice],
      translate: mainTranslate,
      systemAudio: isSystemAudio,
      desktopSourceId: isSystemAudio ? desktopSourceIds[sysDevice] : undefined,
    });
  }, [
    canStartRecording,
    transcription,
    mainLanguage,
    mainTranslate,
    audioSource,
    micDevice,
    micDeviceIds,
    sysDevice,
    desktopSourceIds,
    resolveLanguage,
  ]);

  const handleStopRecording = useCallback(() => {
    transcription.stop();
  }, [transcription]);

  const handleCancelProcessing = useCallback(async () => {
    try {
      await apiClient.cancelTranscription();
      transcription.reset();
    } catch (err) {
      console.error('Failed to cancel transcription:', err);
    }
  }, [transcription]);

  // Copy transcription result to clipboard
  const handleCopyTranscription = useCallback(() => {
    if (!transcription.result?.text) return;
    navigator.clipboard.writeText(transcription.result.text).catch(() => {});
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
        const isSystemAudio = audioSource === 'system';
        live.start({
          language: resolveLanguage(liveLanguage),
          deviceId: isSystemAudio ? undefined : micDeviceIds[micDevice],
          translate: liveTranslate,
          systemAudio: isSystemAudio,
          desktopSourceId: isSystemAudio ? desktopSourceIds[sysDevice] : undefined,
        });
      } else {
        live.stop();
      }
    },
    [
      live,
      liveLanguage,
      liveTranslate,
      audioSource,
      micDevice,
      micDeviceIds,
      sysDevice,
      desktopSourceIds,
      resolveLanguage,
    ],
  );

  // Build server log entries from Docker stream + runtime errors.
  const serverLogs = useMemo(() => {
    const logs: Array<{
      timestamp: string;
      source: string;
      message: string;
      type: 'info' | 'success' | 'error' | 'warning';
    }> = [];
    const now = () => new Date().toLocaleTimeString('en-US', { hour12: false });

    const classifyDockerLine = (line: string): 'info' | 'success' | 'error' | 'warning' => {
      if (/(^|\b)(error|exception|traceback|fatal)(\b|$)/i.test(line)) return 'error';
      if (/(^|\b)(warn|warning)(\b|$)/i.test(line)) return 'warning';
      if (/(^|\b)(started|ready|listening|healthy)(\b|$)/i.test(line)) return 'success';
      return 'info';
    };

    const parseDockerLine = (line: string) => {
      const trimmed = line.trimEnd();
      const match = trimmed.match(
        /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+(.*)$/,
      );
      if (!match) {
        return {
          timestamp: now(),
          source: 'Docker',
          message: trimmed,
          type: classifyDockerLine(trimmed),
        };
      }
      const parsedDate = new Date(match[1]);
      const time = Number.isNaN(parsedDate.getTime())
        ? now()
        : parsedDate.toLocaleTimeString('en-US', { hour12: false });
      return {
        timestamp: time,
        source: 'Docker',
        message: match[2],
        type: classifyDockerLine(match[2]),
      };
    };

    for (const line of docker.logLines) {
      logs.push(parseDockerLine(line));
    }

    if (docker.container.running && logs.length === 0) {
      logs.push({
        timestamp: now(),
        source: 'Docker',
        message: 'Waiting for docker logs...',
        type: 'info',
      });
    }

    if (docker.operationError) {
      logs.push({
        timestamp: now(),
        source: 'Docker',
        message: docker.operationError,
        type: 'error',
      });
    }

    if (transcription.error) {
      logs.push({
        timestamp: now(),
        source: 'Transcription',
        message: transcription.error,
        type: 'error',
      });
    }
    if (live.error) {
      logs.push({ timestamp: now(), source: 'Live', message: live.error, type: 'error' });
    }
    return logs;
  }, [
    docker.logLines,
    docker.container.running,
    docker.operationError,
    transcription.error,
    live.error,
  ]);

  // Keep Docker logs streaming so the terminal updates in real time.
  useEffect(() => {
    if (!docker.container.exists) {
      docker.stopLogStream();
      return;
    }
    docker.startLogStream();
    return () => {
      docker.stopLogStream();
    };
  }, [
    docker.container.exists,
    docker.container.running,
    docker.startLogStream,
    docker.stopLogStream,
  ]);

  const announcedClientLogPathRef = useRef<string | null>(null);
  useEffect(() => {
    if (!clientLogPath || announcedClientLogPathRef.current === clientLogPath) {
      return;
    }
    announcedClientLogPathRef.current = clientLogPath;
    logClientEvent('Client', `Debug log file: ${clientLogPath}`);
  }, [clientLogPath]);

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

  // Copy all logs to clipboard
  const handleCopyLogs = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      const allLogs = [...serverLogs, ...clientLogs];
      const logText = allLogs.map((l) => `[${l.timestamp}] [${l.source}] ${l.message}`).join('\n');
      navigator.clipboard.writeText(logText).catch(() => {});
    },
    [serverLogs, clientLogs],
  );

  // Auto-copy transcription to clipboard on completion + desktop notification
  const prevStatusRef = useRef(transcription.status);
  useEffect(() => {
    const wasProcessing = prevStatusRef.current === 'processing';
    prevStatusRef.current = transcription.status;
    if (wasProcessing && transcription.status === 'complete' && transcription.result?.text) {
      // Auto-copy to clipboard
      navigator.clipboard.writeText(transcription.result.text).catch(() => {});
      // Desktop notification (if permission granted)
      if (Notification.permission === 'granted') {
        new Notification('Transcription Complete', {
          body:
            transcription.result.text.slice(0, 100) +
            (transcription.result.text.length > 100 ? '...' : ''),
          icon: '/logo.svg',
        });
      }
    }
    if (wasProcessing && transcription.status === 'error' && transcription.error) {
      if (Notification.permission === 'granted') {
        new Notification('Transcription Failed', {
          body: transcription.error,
          icon: '/logo.svg',
        });
      }
    }
  }, [transcription.status, transcription.result?.text, transcription.error]);

  // Request notification permission on mount
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  // Scroll State
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const leftContentRef = useRef<HTMLDivElement>(null);
  const rightContentRef = useRef<HTMLDivElement>(null);

  const [leftScrollState, setLeftScrollState] = useState({ top: false, bottom: false });
  const [rightScrollState, setRightScrollState] = useState({ top: false, bottom: false });
  const [leftIndicatorWidth, setLeftIndicatorWidth] = useState<number | null>(null);
  const [rightIndicatorWidth, setRightIndicatorWidth] = useState<number | null>(null);
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

  const calculateIndicatorWidth = useCallback(
    (scrollEl: HTMLDivElement | null, contentEl: HTMLDivElement | null) => {
      if (!scrollEl || !contentEl) return null;
      const contentStyles = window.getComputedStyle(contentEl);
      const rightPadding = Number.parseFloat(contentStyles.paddingRight) || 0;
      return Math.max(0, scrollEl.clientWidth - rightPadding);
    },
    [],
  );

  const updateLeftScrollState = useCallback(() => {
    setLeftScrollState(calculateScrollState(leftScrollRef.current));
  }, [calculateScrollState]);

  const updateRightScrollState = useCallback(() => {
    setRightScrollState(calculateScrollState(rightScrollRef.current));
  }, [calculateScrollState]);

  const updateIndicatorWidths = useCallback(() => {
    const nextLeftWidth = calculateIndicatorWidth(leftScrollRef.current, leftContentRef.current);
    const nextRightWidth = calculateIndicatorWidth(rightScrollRef.current, rightContentRef.current);
    setLeftIndicatorWidth((prev) => (prev === nextLeftWidth ? prev : nextLeftWidth));
    setRightIndicatorWidth((prev) => (prev === nextRightWidth ? prev : nextRightWidth));
  }, [calculateIndicatorWidth]);

  const captureColumnBaselines = useCallback(() => {
    if (showLogs) return;
    const nextLeftHeight = leftScrollRef.current?.clientHeight ?? null;
    const nextRightHeight = rightScrollRef.current?.clientHeight ?? null;
    if (nextLeftHeight) {
      setLeftColumnBaselineHeight((prev) => (prev === nextLeftHeight ? prev : nextLeftHeight));
    }
    if (nextRightHeight) {
      setRightColumnBaselineHeight((prev) => (prev === nextRightHeight ? prev : nextRightHeight));
    }
  }, [showLogs]);

  const recalcScrollIndicators = useCallback(() => {
    captureColumnBaselines();
    updateLeftScrollState();
    updateRightScrollState();
    updateIndicatorWidths();
  }, [captureColumnBaselines, updateLeftScrollState, updateRightScrollState, updateIndicatorWidths]);

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
  }, [showLogs, logsRendered, logsVisible, recalcScrollIndicators]);

  // Logs Animation Logic
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (showLogs) {
      setLogsRendered(true);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setLogsVisible(true);
        });
      });
    } else {
      setLogsVisible(false);
      timer = setTimeout(() => {
        setLogsRendered(false);
      }, 550);
    }
    return () => clearTimeout(timer);
  }, [showLogs]);

  const toggleLogs = () => {
    setShowLogs(!showLogs);
  };

  // Scroll both columns to the bottom whenever logs are toggled
  useEffect(() => {
    const leftEl = leftScrollRef.current;
    const rightEl = rightScrollRef.current;
    if (!leftEl && !rightEl) return;

    const duration = 600;
    const startTime = performance.now();
    let animationFrameId: number;

    const animateScroll = (currentTime: number) => {
      if (leftEl) leftEl.scrollTop = leftEl.scrollHeight;
      if (rightEl) rightEl.scrollTop = rightEl.scrollHeight;
      if (currentTime - startTime < duration) {
        animationFrameId = requestAnimationFrame(animateScroll);
      }
    };

    animationFrameId = requestAnimationFrame(animateScroll);
    return () => cancelAnimationFrame(animationFrameId);
  }, [showLogs]);

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col p-6">
      {/* 1. Header (Fixed) */}
      <div className="mb-6 flex flex-none flex-col space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Session</h1>
      </div>

      {/* 2. Main Content Area */}
      <div className="mb-6 grid min-h-0 flex-1 grid-cols-1 items-stretch gap-6 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] lg:grid-cols-12">
        {/* Left Column: Controls (40%) */}
        <div className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl lg:col-span-5">
          {/* Left Top Scroll Indicator */}
          <div
            className={`pointer-events-none absolute top-0 left-0 z-20 h-6 overflow-hidden transition-opacity duration-300 ${leftScrollState.top ? 'opacity-100' : 'opacity-0'}`}
            style={{ width: leftIndicatorWidth ?? '100%' }}
          >
            <div
              className="h-full w-full bg-linear-to-b from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
              }}
            ></div>
          </div>

          {/* Main Scrollable Area for Left Column */}
          <div ref={leftScrollRef} className="custom-scrollbar flex-1 overflow-y-auto">
            <div
              ref={leftContentRef}
              className="space-y-6 pt-0 pr-3 pb-0"
              style={
                leftColumnBaselineHeight ? { minHeight: `${leftColumnBaselineHeight}px` } : undefined
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
                          {serverRunning
                            ? 'Docker Container Running'
                            : docker.container.exists
                              ? 'Container Stopped'
                              : 'Container Missing'}
                        </span>
                        <StatusLight
                          status={
                            serverRunning
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
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => docker.startContainer('local', runtimeProfile)}
                          disabled={serverRunning || docker.operating}
                          className="px-3 text-xs"
                        >
                          {docker.operating ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            'Start Local'
                          )}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => docker.startContainer('remote', runtimeProfile)}
                          disabled={serverRunning || docker.operating}
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
                      <div className="ml-auto shrink-0">
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={handleUnloadAllModels}
                          disabled={!serverConnection.reachable || modelsOperationPending}
                          className="px-3 text-xs"
                        >
                          {modelsOperationPending ? (
                            <>
                              <Loader2 size={14} className="mr-1 animate-spin" />
                              Unloading...
                            </>
                          ) : (
                            'Unload Models'
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
                        <StatusLight
                          status={clientRunning ? 'active' : 'inactive'}
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
                        disabled={clientRunning}
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
                            System Device
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
                          <CustomSelect
                            value={sysDevice}
                            onChange={handleSystemDeviceChange}
                            options={sysDevices.length > 0 ? sysDevices : ['Default Output']}
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
                  </div>
                </div>
              </GlassCard>

              {/* Main Transcription */}
              <GlassCard title="Main Transcription" className="flex-none">
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
                          options={languageOptions}
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
                        Translate to English
                      </label>
                      <div className="flex h-11.5 items-center justify-center">
                        <AppleSwitch
                          checked={mainTranslate && canTranslate}
                          onChange={setMainTranslate}
                          size="sm"
                          disabled={!canTranslate}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Record / Stop Button */}
                  <div className="flex items-center gap-3 pt-1">
                    {canStartRecording ? (
                      <Button
                        variant="primary"
                        className="bg-accent-cyan/20 border-accent-cyan/40 text-accent-cyan hover:bg-accent-cyan/30 flex-1"
                        icon={
                          isConnecting ? (
                            <Loader2 size={16} className="animate-spin" />
                          ) : (
                            <Mic size={16} />
                          )
                        }
                        onClick={handleStartRecording}
                        disabled={isLive}
                      >
                        {isConnecting ? 'Connecting...' : 'Start Recording'}
                      </Button>
                    ) : (
                      <>
                        <Button
                          variant="danger"
                          className="flex-1"
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
                          {isProcessing ? 'Processing...' : 'Stop Recording'}
                        </Button>
                        {isProcessing && (
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

              <div className="pt-2">
                <div
                  onClick={toggleLogs}
                  className={`group flex w-full cursor-pointer items-center justify-between rounded-2xl border px-4 py-3 transition-all duration-200 select-none ${showLogs ? 'bg-accent-cyan/10 border-accent-cyan/30 text-accent-cyan shadow-[0_0_15px_rgba(34,211,238,0.15)]' : 'from-glass-200 to-glass-100 border-glass-border bg-linear-to-br text-slate-400 backdrop-blur-xl hover:text-white hover:brightness-110'}`}
                >
                  <div className="flex items-center gap-2">
                    <Terminal size={18} />
                    <span className="text-sm font-medium">System Logs</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div
                      className={`overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] ${showLogs ? 'w-24 opacity-100' : 'w-0 opacity-0'}`}
                    >
                      <Button
                        variant="secondary"
                        size="sm"
                        className="h-8 w-full text-xs whitespace-nowrap text-slate-300"
                        onClick={handleCopyLogs}
                        icon={<Copy size={14} />}
                      >
                        Copy All
                      </Button>
                    </div>
                    <div className="text-xs font-bold tracking-wider uppercase">
                      {showLogs ? 'Hide' : 'Show'}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Left Bottom Scroll Indicator */}
          <div
            className={`pointer-events-none absolute bottom-0 left-0 z-20 h-6 overflow-hidden transition-opacity duration-300 ${leftScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}
            style={{ width: leftIndicatorWidth ?? '100%' }}
          >
            <div
              className="h-full w-full bg-linear-to-t from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
        </div>

        {/* Right Column: Visualizer & Live Mode (60%) */}
        <div className="relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl lg:col-span-7">
          {/* Right Top Scroll Indicator */}
          <div
            className={`pointer-events-none absolute top-0 left-0 z-20 h-6 overflow-hidden transition-opacity duration-300 ${rightScrollState.top ? 'opacity-100' : 'opacity-0'}`}
            style={{ width: rightIndicatorWidth ?? '100%' }}
          >
            <div
              className="h-full w-full bg-linear-to-b from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
              }}
            ></div>
          </div>

          {/* Right Column Scroll Container */}
          <div ref={rightScrollRef} className="custom-scrollbar flex-1 overflow-y-auto">
            <div
              ref={rightContentRef}
              className="flex min-h-full flex-col pt-0 pr-3 pb-0"
              style={
                rightColumnBaselineHeight ? { minHeight: `${rightColumnBaselineHeight}px` } : undefined
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
                      <h3 className="font-semibold text-white">Soundwave Monitor</h3>
                      <p className="text-xs text-slate-400">Frequency Analysis</p>
                    </div>
                  </div>
                </div>
                <div className="group relative">
                  <AudioVisualizer analyserNode={activeAnalyser} />
                  <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100">
                    <Button
                      variant="secondary"
                      size="icon"
                      className="h-8 w-8 bg-black/50 backdrop-blur-sm"
                      icon={<Maximize2 size={14} />}
                      onClick={() => setIsFullscreenVisualizerOpen(true)}
                    />
                  </div>
                </div>
              </GlassCard>

              {/* Live Mode (Text + Controls) */}
              <GlassCard
                className="flex flex-1 flex-col transition-all duration-300"
                title="Live Mode"
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Copy size={14} />}
                    onClick={() => navigator.clipboard.writeText(live.getText())}
                  >
                    Copy
                  </Button>
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
                    <AppleSwitch checked={isLive} onChange={handleLiveToggle} size="sm" />
                  </div>
                  <Button
                    variant={live.muted ? 'danger' : 'secondary'}
                    size="sm"
                    icon={live.muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                    onClick={() => live.toggleMute()}
                    disabled={!isLive}
                    className={`h-8 shrink-0 whitespace-nowrap ${live.muted ? 'border-red-500/30 bg-red-500/20 text-red-400' : 'text-slate-300'}`}
                  >
                    {live.muted ? 'Muted' : 'Audio On'}
                  </Button>
                  <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                  <div className="flex h-8 shrink-0 items-center gap-2">
                    <div className="bg-accent-magenta/10 text-accent-magenta border-accent-magenta/5 flex aspect-square h-full items-center justify-center rounded-lg border">
                      <Languages size={15} />
                    </div>
                    <CustomSelect
                      value={liveLanguage}
                      onChange={handleLiveLanguageChange}
                      options={languageOptions}
                      accentColor="magenta"
                      className="focus:ring-accent-magenta h-full min-w-32.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-sm text-slate-300 outline-none focus:ring-1"
                    />
                  </div>
                  <div className="mx-0.5 h-5 w-px shrink-0 bg-white/10"></div>
                  <div
                    className="flex h-8 shrink-0 items-center gap-2"
                    title={canTranslate ? '' : 'Current model does not support translation'}
                  >
                    <span
                      className={`text-[9px] font-bold tracking-widest whitespace-nowrap uppercase ${canTranslate ? 'text-slate-500' : 'text-slate-600 line-through'}`}
                    >
                      Translate to English
                    </span>
                    <AppleSwitch
                      checked={liveTranslate && canTranslate}
                      onChange={setLiveTranslate}
                      size="sm"
                      disabled={!canTranslate}
                    />
                  </div>
                </div>

                {/* Transcript Area */}
                <div className="custom-scrollbar selectable-text relative min-h-40 flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/20 p-4 font-mono text-sm leading-relaxed text-slate-300 shadow-inner">
                  {isLive ? (
                    <>
                      {live.statusMessage && (
                        <div className="text-accent-cyan mb-3 flex animate-pulse items-center gap-2">
                          <Loader2 size={14} className="animate-spin" />
                          <span className="text-xs">{live.statusMessage}</span>
                        </div>
                      )}
                      {live.sentences.map((s, i) => (
                        <div key={i} className="mb-2">
                          <span className="mr-2 text-slate-500 select-none">
                            {new Date(s.timestamp).toLocaleTimeString('en-US', { hour12: false })}
                          </span>
                          <span>{s.text}</span>
                        </div>
                      ))}
                      {live.partial && (
                        <div className="mb-2 opacity-60">
                          <span className="mr-2 text-slate-500 select-none">
                            {new Date().toLocaleTimeString('en-US', { hour12: false })}
                          </span>
                          <span className="italic">{live.partial}</span>
                          <span className="bg-accent-cyan ml-0.5 inline-block h-4 w-1.5 animate-pulse align-text-bottom"></span>
                        </div>
                      )}
                      {live.sentences.length === 0 && !live.partial && !live.statusMessage && (
                        <div className="flex h-full flex-col items-center justify-center space-y-3 text-slate-600 opacity-60 select-none">
                          <Activity size={32} strokeWidth={1} className="animate-pulse" />
                          <p>Listening... speak to see transcription.</p>
                        </div>
                      )}
                      {live.error && <div className="mt-2 text-xs text-red-400">{live.error}</div>}
                    </>
                  ) : (
                    <div className="flex h-full flex-col items-center justify-center space-y-3 text-slate-600 opacity-60 select-none">
                      <Radio size={48} strokeWidth={1} />
                      <p>Live mode is off. Toggle the switch to start.</p>
                    </div>
                  )}
                </div>
              </GlassCard>
            </div>
          </div>

          {/* Right Bottom Scroll Indicator */}
          <div
            className={`pointer-events-none absolute bottom-0 left-0 z-20 h-6 overflow-hidden transition-opacity duration-300 ${rightScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}
            style={{ width: rightIndicatorWidth ?? '100%' }}
          >
            <div
              className="h-full w-full bg-linear-to-t from-white/10 to-transparent backdrop-blur-sm"
              style={{
                maskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)',
              }}
            ></div>
          </div>
        </div>
      </div>

      {/* 3. Bottom Drawer: Logs */}
      {logsRendered && (
        <div
          className={`grid flex-none grid-cols-1 gap-6 overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] lg:grid-cols-2 ${logsVisible ? 'h-72 translate-y-0 border-t border-white/10 pt-4 pb-1 opacity-100' : 'h-0 translate-y-4 border-t-0 border-transparent py-0 opacity-0'}`}
        >
          <LogTerminal
            title="Server Output (Docker)"
            logs={serverLogs}
            color="magenta"
            className="h-full"
          />
          <LogTerminal
            title="Client Debug (Socket)"
            logs={clientLogs}
            color="cyan"
            className="h-full"
          />
        </div>
      )}

      {/* Fullscreen Visualizer Modal */}
      <FullscreenVisualizer
        isOpen={isFullscreenVisualizerOpen}
        onClose={() => setIsFullscreenVisualizerOpen(false)}
        analyserNode={activeAnalyser}
      />
    </div>
  );
};
