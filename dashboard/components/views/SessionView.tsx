
import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Mic, Radio, Square, RefreshCw, Languages, Copy, Volume2, VolumeX, Maximize2, Terminal, Activity, Server, Trash, Laptop, Loader2, X, Download } from 'lucide-react';
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
import { useDocker } from '../../src/hooks/useDocker';
import { useTraySync } from '../../src/hooks/useTraySync';
import { useServerStatus } from '../../src/hooks/useServerStatus';
import { apiClient } from '../../src/api/client';
import { setConfig } from '../../src/config/store';

export const SessionView: React.FC = () => {
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
      api.config.get('server.runtimeProfile').then((val: unknown) => {
        if (val === 'gpu' || val === 'cpu') setRuntimeProfile(val);
      }).catch(() => {});
    }
  }, []);

  // Real language list from server
  const { languages } = useLanguages();
  const languageOptions = useMemo(() => ['Auto Detect', ...languages.map(l => l.name)], [languages]);

  // Transcription hooks
  const transcription = useTranscription();
  const live = useLiveMode();

  // Active analyser: live mode takes priority when active, then one-shot
  const activeAnalyser = live.analyser ?? transcription.analyser;

  // Audio device enumeration
  const [micDevices, setMicDevices] = useState<string[]>([]);
  const [sysDevices, setSysDevices] = useState<string[]>([]);
  const [micDeviceIds, setMicDeviceIds] = useState<Record<string, string>>({});

  // Desktop sources for system audio capture (Electron only)
  const [desktopSources, setDesktopSources] = useState<Array<{ id: string; name: string; thumbnail: string }>>([]);
  const [desktopSourceIds, setDesktopSourceIds] = useState<Record<string, string>>({});

  // Audio Configuration State
  const [audioSource, setAudioSource] = useState<'mic' | 'system'>('mic');
  const [micDevice, setMicDevice] = useState('Default Microphone');
  const [sysDevice, setSysDevice] = useState('Default Output');

  // Fetch desktop sources when system audio is selected (Electron only)
  const fetchDesktopSources = useCallback(async () => {
    if (!window.electronAPI?.audio?.getDesktopSources) return;
    try {
      const sources = await window.electronAPI.audio.getDesktopSources();
      setDesktopSources(sources);
      const idMap: Record<string, string> = {};
      sources.forEach(s => { idMap[s.name] = s.id; });
      setDesktopSourceIds(idMap);
      const sourceNames = sources.map(s => s.name);
      setSysDevices(sourceNames.length > 0 ? sourceNames : ['No sources available']);
      if (sourceNames.length > 0 && !sourceNames.includes(sysDevice)) {
        setSysDevice(sourceNames[0]);
      }
    } catch (err) {
      console.error('Failed to fetch desktop sources:', err);
      setSysDevices(['No sources available']);
    }
  }, [sysDevice]);

  // Refresh desktop sources when switching to system audio
  useEffect(() => {
    if (audioSource === 'system') {
      fetchDesktopSources();
    }
  }, [audioSource, fetchDesktopSources]);

  const enumerateDevices = useCallback(async () => {
    try {
      // Request permission first (needed to get labels)
      await navigator.mediaDevices.getUserMedia({ audio: true }).then(s => s.getTracks().forEach(t => t.stop()));
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(d => d.kind === 'audioinput' && d.label);
      const audioOutputs = devices.filter(d => d.kind === 'audiooutput' && d.label).map(d => d.label);
      const inputLabels = audioInputs.map(d => d.label);
      const idMap: Record<string, string> = {};
      audioInputs.forEach(d => { idMap[d.label] = d.deviceId; });
      setMicDevices(inputLabels.length > 0 ? inputLabels : ['Default Microphone']);
      setMicDeviceIds(idMap);
      setSysDevices(audioOutputs.length > 0 ? audioOutputs : ['Default Output']);
      if (inputLabels.length > 0 && !inputLabels.includes(micDevice)) setMicDevice(inputLabels[0]);
      if (audioOutputs.length > 0 && !audioOutputs.includes(sysDevice)) setSysDevice(audioOutputs[0]);
    } catch {
      setMicDevices(['Default Microphone']);
      setSysDevices(['Default Output']);
    }
  }, [micDevice, sysDevice]);

  useEffect(() => { enumerateDevices(); }, [enumerateDevices]);

  // Main Transcription State
  const [mainLanguage, setMainLanguage] = useState('Auto Detect');
  const [mainTranslate, setMainTranslate] = useState(false);

  // Live Mode State
  const isLive = live.status !== 'idle' && live.status !== 'error';
  const [liveLanguage, setLiveLanguage] = useState('Auto Detect');
  const [liveTranslate, setLiveTranslate] = useState(false);
  
  // Control Center State — real Docker container status
  const docker = useDocker();
  const serverRunning = docker.container.running;
  // Client connection state — tracks explicit connect/disconnect
  const [clientRunning, setClientRunning] = useState(false);
  const serverConnection = useServerStatus();
  // Derive active client connection from explicit state + hook activity
  const clientConnected = clientRunning && (
    serverConnection.reachable
    || transcription.status === 'recording' || transcription.status === 'processing'
    || live.status === 'listening' || live.status === 'processing' || live.status === 'starting'
  );

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
    serverConnection.refresh();
  }, [serverConnection]);

  const handleStartClientRemote = useCallback(async () => {
    await setConfig('connection.useRemote', true);
    await apiClient.syncFromConfig();
    setClientRunning(true);
    serverConnection.refresh();
  }, [serverConnection]);

  const handleStopClient = useCallback(() => {
    setClientRunning(false);
  }, []);

  // System Health Check for Visual Effects
  const isSystemHealthy = serverRunning && (clientConnected || transcription.status === 'idle');

  // Sync tray icon state with application state
  useTraySync({
    serverStatus: serverRunning ? 'active' : 'inactive',
    containerRunning: serverRunning,
    transcriptionStatus: transcription.status,
    liveStatus: live.status,
    muted: live.muted,
    onStartRecording: () => transcription.start(),
    onStopRecording: () => {
      if (isLive) live.stop();
      else transcription.stop();
    },
    onToggleMute: () => live.toggleMute(),
  });

  // Resolve language code from display name
  const resolveLanguage = useCallback((name: string): string | undefined => {
    if (name === 'Auto Detect') return undefined;
    const match = languages.find(l => l.name === name);
    return match?.code;
  }, [languages]);

  // Helpers for main transcription controls
  const isRecording = transcription.status === 'recording';
  const isProcessing = transcription.status === 'processing';
  const isConnecting = transcription.status === 'connecting';
  const canStartRecording = transcription.status === 'idle' || transcription.status === 'complete' || transcription.status === 'error';

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
  }, [canStartRecording, transcription, mainLanguage, mainTranslate, audioSource, micDevice, micDeviceIds, sysDevice, desktopSourceIds, resolveLanguage]);

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
  const handleLiveToggle = useCallback((checked: boolean) => {
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
  }, [live, liveLanguage, liveTranslate, audioSource, micDevice, micDeviceIds, sysDevice, desktopSourceIds, resolveLanguage]);

  // Build log entries from hook states
  const serverLogs = useMemo(() => {
    const logs: Array<{ timestamp: string; source: string; message: string; type: 'info' | 'success' | 'error' | 'warning' }> = [];
    const now = () => new Date().toLocaleTimeString('en-US', { hour12: false });
    if (serverRunning) {
      logs.push({ timestamp: now(), source: 'Docker', message: 'Container running', type: 'success' });
    }
    if (live.statusMessage) {
      logs.push({ timestamp: now(), source: 'Live', message: live.statusMessage, type: 'info' });
    }
    if (live.error) {
      logs.push({ timestamp: now(), source: 'Live', message: live.error, type: 'error' });
    }
    if (transcription.error) {
      logs.push({ timestamp: now(), source: 'Transcription', message: transcription.error, type: 'error' });
    }
    return logs;
  }, [serverRunning, live.statusMessage, live.error, transcription.error]);

  const clientLogs = useMemo(() => {
    const logs: Array<{ timestamp: string; source: string; message: string; type: 'info' | 'success' | 'error' | 'warning' }> = [];
    const now = () => new Date().toLocaleTimeString('en-US', { hour12: false });
    if (clientConnected) {
      logs.push({ timestamp: now(), source: 'Socket', message: 'WebSocket connected', type: 'success' });
    }
    if (transcription.status === 'recording') {
      logs.push({ timestamp: now(), source: 'Audio', message: 'Recording audio...', type: 'info' });
    }
    if (transcription.status === 'processing') {
      logs.push({ timestamp: now(), source: 'Engine', message: 'Processing transcription...', type: 'info' });
    }
    if (transcription.result) {
      logs.push({ timestamp: now(), source: 'Engine', message: `Transcription complete (${transcription.result.duration?.toFixed(1) ?? '?'}s audio)`, type: 'success' });
    }
    return logs;
  }, [clientConnected, transcription.status, transcription.result]);

  // Copy all logs to clipboard
  const handleCopyLogs = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const allLogs = [...serverLogs, ...clientLogs];
    const logText = allLogs.map(l => `[${l.timestamp}] [${l.source}] ${l.message}`).join('\n');
    navigator.clipboard.writeText(logText).catch(() => {});
  }, [serverLogs, clientLogs]);

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
          body: transcription.result.text.slice(0, 100) + (transcription.result.text.length > 100 ? '...' : ''),
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
  
  const [leftScrollState, setLeftScrollState] = useState({ top: false, bottom: false });
  const [rightScrollState, setRightScrollState] = useState({ top: false, bottom: false });

  // Handle Scroll Shadows
  useEffect(() => {
    const handleScroll = (ref: React.RefObject<HTMLDivElement>, setState: React.Dispatch<React.SetStateAction<{top: boolean, bottom: boolean}>>) => {
      if (ref.current) {
        const { scrollTop, scrollHeight, clientHeight } = ref.current;
        setState({
            top: scrollTop > 0,
            bottom: Math.ceil(scrollTop + clientHeight) < scrollHeight
        });
      }
    };

    const checkAll = () => {
        handleScroll(leftScrollRef, setLeftScrollState);
        handleScroll(rightScrollRef, setRightScrollState);
    };

    const leftEl = leftScrollRef.current;
    const rightEl = rightScrollRef.current;

    if (leftEl) leftEl.addEventListener('scroll', () => handleScroll(leftScrollRef, setLeftScrollState));
    if (rightEl) rightEl.addEventListener('scroll', () => handleScroll(rightScrollRef, setRightScrollState));
    
    // Initial check and resize listener
    checkAll();
    window.addEventListener('resize', checkAll);

    return () => {
      if (leftEl) leftEl.removeEventListener('scroll', () => handleScroll(leftScrollRef, setLeftScrollState));
      if (rightEl) rightEl.removeEventListener('scroll', () => handleScroll(rightScrollRef, setRightScrollState));
      window.removeEventListener('resize', checkAll);
    };
  }, []); // Run once on mount

  // Scroll Pinning Logic
  useEffect(() => {
    const scrollContainer = leftScrollRef.current;
    if (!scrollContainer) return;

    const duration = 600;
    const startTime = performance.now();
    let animationFrameId: number;

    const animateScroll = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
      if (elapsed < duration) {
        animationFrameId = requestAnimationFrame(animateScroll);
      }
    };

    animationFrameId = requestAnimationFrame(animateScroll);
    return () => cancelAnimationFrame(animationFrameId);
  }, [showLogs]);

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

  const maskStyle: React.CSSProperties = {
    backgroundColor: '#0f172a',
    backgroundImage: `radial-gradient(at 0% 0%, hsla(253,16%,7%,1) 0, transparent 50%), 
    radial-gradient(at 50% 0%, hsla(225,39%,30%,1) 0, transparent 50%), 
    radial-gradient(at 100% 0%, hsla(339,49%,30%,1) 0, transparent 50%)`,
    backgroundAttachment: 'fixed'
  };

  return (
    <div className="flex flex-col h-full max-w-7xl mx-auto w-full p-6">
      {/* 1. Header (Fixed) */}
      <div className="flex-none flex flex-col space-y-2 mb-6">
        <h1 className="text-3xl font-bold text-white tracking-tight">Session</h1>
      </div>

      {/* 2. Main Content Area */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
        
        {/* Left Column: Controls (40%) */}
        <div className="lg:col-span-5 flex flex-col min-h-0 relative rounded-2xl overflow-hidden">
             
             {/* Left Top Scroll Indicator */}
             <div className={`absolute top-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-t-2xl transition-opacity duration-300 ${leftScrollState.top ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-linear-to-b from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)' }}></div>
             </div>

             {/* Left Top Corner Mask */}
            <div className="absolute top-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)' }} />

             {/* Main Scrollable Area for Left Column */}
             <div ref={leftScrollRef} className="flex-1 overflow-y-auto pr-3 pt-0 pb-0 custom-scrollbar space-y-6">
                
                {/* Unified Control Center */}
                <GlassCard title="Control Center" className={`bg-linear-to-b from-glass-200 to-glass-100 flex-none transition-all duration-500 ease-in-out relative ${isSystemHealthy ? 'border-accent-cyan/50! shadow-[0_20px_25px_-5px_rgba(0,0,0,0.3),0_8px_10px_-6px_rgba(0,0,0,0.3),inset_0_0_30px_rgba(34,211,238,0.15)]! z-10' : ''}`}>
                    <div className="space-y-5">
                        {/* Server Control */}
                        <div className="flex flex-col p-4 bg-white/5 rounded-xl border border-white/5 space-y-4 shadow-sm">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg bg-accent-magenta/10 text-accent-magenta`}><Server size={20} /></div>
                                    <div className="text-sm font-semibold text-white tracking-wide">Inference Server</div>
                                </div>
                                <div className="flex items-center gap-2.5">
                                    <span className="text-xs font-medium text-slate-400">{serverRunning ? 'Docker Container Running' : 'Container Stopped'}</span>
                                    <StatusLight status={serverRunning ? 'active' : 'inactive'} className="w-2 h-2" animate={serverRunning} />
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Button variant="secondary" size="sm" onClick={() => docker.startContainer('local', runtimeProfile)} disabled={serverRunning || docker.operating} className="text-xs px-3">
                                    {docker.operating ? <Loader2 size={14} className="animate-spin" /> : 'Start Local'}
                                </Button>
                                <Button variant="secondary" size="sm" onClick={() => docker.startContainer('remote', runtimeProfile)} disabled={serverRunning || docker.operating} className="text-xs px-3">Start Remote</Button>
                                <Button variant="danger" size="sm" onClick={() => docker.stopContainer()} disabled={!serverRunning || docker.operating} className="text-xs px-3">Stop</Button>
                            </div>
                        </div>

                        {/* Client Control */}
                        <div className="flex flex-col p-4 bg-white/5 rounded-xl border border-white/5 space-y-4 shadow-sm">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg bg-accent-cyan/10 text-accent-cyan`}><Activity size={20} /></div>
                                    <div className="text-sm font-semibold text-white tracking-wide">Client Link</div>
                                </div>
                                <div className="flex items-center gap-2.5">
                                    <span className="text-xs font-medium text-slate-400">
                                      {clientStatusLabel}
                                    </span>
                                    <StatusLight status={clientConnected ? 'active' : clientRunning ? 'warning' : 'inactive'} className="w-2 h-2" animate={clientConnected} />
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Button variant="secondary" size="sm" onClick={handleStartClientLocal} disabled={clientRunning} className="text-xs px-3">Start Local</Button>
                                <Button variant="secondary" size="sm" onClick={handleStartClientRemote} disabled={clientRunning} className="text-xs px-3">Start Remote</Button>
                                <Button variant="danger" size="sm" onClick={handleStopClient} disabled={!clientRunning} className="text-xs px-3">Stop</Button>
                            </div>
                        </div>
                    </div>
                </GlassCard>

                {/* Audio Configuration */}
                <GlassCard title="Audio Configuration" className="flex-none">
                    <div className="space-y-6">
                        <div>
                             <label className="text-xs text-slate-400 ml-1 font-medium uppercase tracking-wider mb-2 block">Active Input Source</label>
                             <div className="bg-black/60 p-1 rounded-xl border border-white/5 relative flex shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)]">
                                <div className={`absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-lg shadow-[0_2px_8px_rgba(0,0,0,0.4)] transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] z-0 bg-slate-700 border-t border-white/10 ${audioSource === 'system' ? 'translate-x-[calc(100%+4px)]' : 'translate-x-0'}`} />
                                <button onClick={() => setAudioSource('mic')} className={`flex-1 relative z-10 flex items-center justify-center space-x-2.5 py-2.5 text-sm font-semibold transition-all duration-300 ${audioSource === 'mic' ? 'text-white' : 'text-slate-500 hover:text-slate-300'}`}>
                                    <Mic size={18} className={`transition-all duration-300 ${audioSource === 'mic' ? 'text-accent-cyan drop-shadow-[0_0_8px_rgba(34,211,238,0.6)] scale-110' : ''}`} />
                                    <span>Microphone</span>
                                </button>
                                <button onClick={() => setAudioSource('system')} className={`flex-1 relative z-10 flex items-center justify-center space-x-2.5 py-2.5 text-sm font-semibold transition-all duration-300 ${audioSource === 'system' ? 'text-white' : 'text-slate-500 hover:text-slate-300'}`}>
                                    <Laptop size={18} className={`transition-all duration-300 ${audioSource === 'system' ? 'text-accent-cyan drop-shadow-[0_0_8px_rgba(34,211,238,0.6)] scale-110' : ''}`} />
                                    <span>System Audio</span>
                                </button>
                            </div>
                        </div>
                        <div className="h-px bg-white/5 w-full"></div>
                        <div className="space-y-4">
                            <div className={`p-3 rounded-xl border transition-all duration-300 ${audioSource === 'mic' ? 'bg-accent-cyan/5 border-accent-cyan/20 shadow-[0_0_10px_rgba(34,211,238,0.05)]' : 'bg-transparent border-transparent hover:bg-white/5'}`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2"><Mic size={14} className={audioSource === 'mic' ? 'text-accent-cyan' : 'text-slate-500'} /><label className={`text-xs font-medium ${audioSource === 'mic' ? 'text-white' : 'text-slate-400'}`}>Microphone Device</label></div>
                                    {audioSource === 'mic' && <span className="text-[10px] bg-accent-cyan text-black px-1.5 py-0.5 rounded font-bold uppercase tracking-wide">Live</span>}
                                </div>
                                <div className="flex gap-2">
                                    <CustomSelect value={micDevice} onChange={setMicDevice} options={micDevices.length > 0 ? micDevices : ['Default Microphone']} className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none hover:border-white/20 transition-shadow" />
                                    <Button variant="secondary" size="icon" icon={<RefreshCw size={14} />} onClick={enumerateDevices} />
                                </div>
                            </div>
                            <div className={`p-3 rounded-xl border transition-all duration-300 ${audioSource === 'system' ? 'bg-accent-cyan/5 border-accent-cyan/20 shadow-[0_0_10px_rgba(34,211,238,0.05)]' : 'bg-transparent border-transparent hover:bg-white/5'}`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2"><Laptop size={14} className={audioSource === 'system' ? 'text-accent-cyan' : 'text-slate-500'} /><label className={`text-xs font-medium ${audioSource === 'system' ? 'text-white' : 'text-slate-400'}`}>System Device</label></div>
                                    {audioSource === 'system' && <span className="text-[10px] bg-accent-cyan text-black px-1.5 py-0.5 rounded font-bold uppercase tracking-wide">Live</span>}
                                </div>
                                <div className="flex gap-2">
                                    <CustomSelect value={sysDevice} onChange={setSysDevice} options={sysDevices.length > 0 ? sysDevices : ['Default Output']} className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none hover:border-white/20 transition-shadow" />
                                    <Button variant="secondary" size="icon" icon={<RefreshCw size={14} />} onClick={enumerateDevices} />
                                </div>
                            </div>
                        </div>
                    </div>
                </GlassCard>

                {/* Main Transcription */}
                <GlassCard title="Main Transcription" className="flex-none">
                    <div className="space-y-4">
                        <div className="flex items-center justify-between gap-6 p-1">
                            <div className="flex flex-col flex-1 min-w-0">
                                 <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2 ml-1">Source Language</label>
                                 <div className="flex items-center gap-2">
                                    <div className="p-2.5 rounded-xl bg-accent-magenta/10 text-accent-magenta shadow-inner border border-accent-magenta/5"><Languages size={18} /></div>
                                    <CustomSelect value={mainLanguage} onChange={setMainLanguage} options={languageOptions} accentColor="magenta" className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:ring-1 focus:ring-accent-magenta outline-none hover:border-white/20 transition-all" />
                                </div>
                            </div>
                            <div className="h-12 w-px bg-white/10 self-end mb-1"></div>
                            <div className="flex flex-col items-center min-w-25">
                                <label className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2 mt-1 text-center whitespace-nowrap">Translate to English</label>
                                <div className="h-11.5 flex items-center justify-center"><AppleSwitch checked={mainTranslate} onChange={setMainTranslate} size="sm" /></div>
                            </div>
                        </div>

                        {/* Record / Stop Button */}
                        <div className="flex items-center gap-3 pt-1">
                            {canStartRecording ? (
                                <Button
                                    variant="primary"
                                    className="flex-1 bg-accent-cyan/20 border-accent-cyan/40 text-accent-cyan hover:bg-accent-cyan/30"
                                    icon={isConnecting ? <Loader2 size={16} className="animate-spin" /> : <Mic size={16} />}
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
                                        icon={isProcessing ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
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
                                <span className="text-xs font-mono text-green-400 whitespace-nowrap animate-pulse">VAD Active</span>
                            )}
                        </div>

                        {/* Transcription Result */}
                        {transcription.result && (
                            <div className="space-y-2">
                                <div className="bg-black/20 rounded-xl border border-white/5 p-4 text-sm leading-relaxed text-slate-300 font-mono selectable-text max-h-32 overflow-y-auto custom-scrollbar">
                                    {transcription.result.text}
                                    {transcription.result.language && (
                                        <div className="mt-2 text-xs text-slate-500">
                                            Detected: {transcription.result.language} &middot; {transcription.result.duration?.toFixed(1)}s
                                        </div>
                                    )}
                                </div>
                                <div className="flex items-center gap-2">
                                    <Button variant="secondary" size="sm" icon={<Copy size={14} />} onClick={handleCopyTranscription}>Copy</Button>
                                    <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={handleDownloadTranscription}>Download</Button>
                                </div>
                            </div>
                        )}

                        {/* Errors */}
                        {transcription.error && (
                            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{transcription.error}</div>
                        )}
                    </div>
                </GlassCard>
                
                <div className="pt-2">
                    <div onClick={toggleLogs} className={`w-full flex items-center justify-between px-4 py-3 rounded-2xl border transition-all duration-200 cursor-pointer group select-none ${showLogs ? 'bg-accent-cyan/10 border-accent-cyan/30 text-accent-cyan shadow-[0_0_15px_rgba(34,211,238,0.15)]' : 'bg-linear-to-br from-glass-200 to-glass-100 backdrop-blur-xl border-glass-border text-slate-400 hover:text-white hover:brightness-110'}`}>
                        <div className="flex items-center gap-2"><Terminal size={18} /><span className="text-sm font-medium">System Logs</span></div>
                        <div className="flex items-center gap-3">
                             <div className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] overflow-hidden ${showLogs ? 'w-24 opacity-100' : 'w-0 opacity-0'}`}>
                                  <Button variant="secondary" size="sm" className="h-8 w-full whitespace-nowrap text-xs text-slate-300" onClick={handleCopyLogs} icon={<Copy size={14} />}>Copy All</Button>
                             </div>
                            <div className="text-xs uppercase tracking-wider font-bold">{showLogs ? 'Hide' : 'Show'}</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Left Bottom Scroll Indicator */}
            <div className={`absolute bottom-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-b-2xl transition-opacity duration-300 ${leftScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-linear-to-t from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to top, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)' }}></div>
            </div>
            <div className="absolute bottom-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)' }} />
        </div>

        {/* Right Column: Visualizer & Live Mode (60%) */}
        <div className="lg:col-span-7 flex flex-col min-h-0 relative rounded-2xl overflow-hidden">
            
            {/* Right Top Scroll Indicator */}
             <div className={`absolute top-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-t-2xl transition-opacity duration-300 ${rightScrollState.top ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-linear-to-b from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)' }}></div>
             </div>
             <div className="absolute top-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)' }} />

            {/* Right Column Scroll Container */}
            <div ref={rightScrollRef} className="flex-1 flex flex-col overflow-y-auto pr-3 pt-0 pb-0 custom-scrollbar">
                
                {/* Visualizer Card */}
                <GlassCard className="relative overflow-visible z-10 flex-none mb-6">
                    <div className="flex items-center justify-between mb-4 shrink-0">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-full bg-accent-cyan/10 text-accent-cyan"><Activity size={20} className={isLive ? "animate-pulse" : ""} /></div>
                            <div>
                                <h3 className="font-semibold text-white">Soundwave Monitor</h3>
                                <p className="text-xs text-slate-400">Frequency Analysis</p>
                            </div>
                        </div>
                    </div>
                    <div className="relative group">
                        <AudioVisualizer analyserNode={activeAnalyser} />
                        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Button variant="secondary" size="icon" className="h-8 w-8 bg-black/50 backdrop-blur-sm" icon={<Maximize2 size={14}/>} onClick={() => setIsFullscreenVisualizerOpen(true)} />
                        </div>
                    </div>
                </GlassCard>

                {/* Live Mode (Text + Controls) */}
                <GlassCard className="flex-1 min-h-[calc(100vh-30rem)] flex flex-col transition-all duration-300" title="Live Mode" action={<Button variant="ghost" size="sm" icon={<Copy size={14} />} onClick={() => navigator.clipboard.writeText(live.getText())}>Copy</Button>}>
                    
                    {/* Live Mode Controls Toolbar */}
                    <div className="flex items-center gap-2 p-1 pb-4 mb-4 border-b border-white/5 overflow-x-auto flex-nowrap custom-scrollbar no-scrollbar flex-none">
                        <div className="flex items-center gap-2 h-8 shrink-0">
                                <span className={`text-xs font-bold uppercase tracking-wider ${isLive ? 'text-green-400' : 'text-slate-500'}`}>
                                    {live.status === 'starting' ? 'Loading...' : isLive ? 'Active' : 'Offline'}
                                </span>
                                <AppleSwitch checked={isLive} onChange={handleLiveToggle} size="sm" />
                        </div>
                        <Button variant={live.muted ? 'danger' : 'secondary'} size="sm" icon={live.muted ? <VolumeX size={14}/> : <Volume2 size={14}/>} onClick={() => live.toggleMute()} disabled={!isLive} className={`h-8 shrink-0 whitespace-nowrap ${live.muted ? "bg-red-500/20 text-red-400 border-red-500/30" : "text-slate-300"}`}>{live.muted ? 'Muted' : 'Audio On'}</Button>
                        <div className="h-5 w-px bg-white/10 mx-0.5 shrink-0"></div>
                        <div className="flex items-center gap-2 h-8 shrink-0">
                            <div className="h-full aspect-square flex items-center justify-center rounded-lg bg-accent-magenta/10 text-accent-magenta border border-accent-magenta/5"><Languages size={15} /></div>
                            <CustomSelect value={liveLanguage} onChange={setLiveLanguage} options={languageOptions} accentColor="magenta" className="bg-white/5 border border-white/10 rounded-lg px-3 py-1 text-sm text-slate-300 focus:ring-1 focus:ring-accent-magenta outline-none h-full min-w-32.5" />
                        </div>
                        <div className="h-5 w-px bg-white/10 mx-0.5 shrink-0"></div>
                        <div className="flex items-center gap-2 h-8 shrink-0">
                            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest whitespace-nowrap">Translate to English</span>
                            <AppleSwitch checked={liveTranslate} onChange={setLiveTranslate} size="sm" />
                        </div>
                    </div>

                    {/* Transcript Area */}
                    <div className="flex-1 bg-black/20 rounded-xl border border-white/5 p-4 overflow-y-auto font-mono text-sm leading-relaxed text-slate-300 shadow-inner custom-scrollbar relative min-h-0 selectable-text">
                        {isLive ? (
                            <>
                                {live.statusMessage && (
                                    <div className="flex items-center gap-2 text-accent-cyan mb-3 animate-pulse">
                                        <Loader2 size={14} className="animate-spin" />
                                        <span className="text-xs">{live.statusMessage}</span>
                                    </div>
                                )}
                                {live.sentences.map((s, i) => (
                                    <div key={i} className="mb-2">
                                        <span className="text-slate-500 select-none mr-2">{new Date(s.timestamp).toLocaleTimeString('en-US', { hour12: false })}</span>
                                        <span>{s.text}</span>
                                    </div>
                                ))}
                                {live.partial && (
                                    <div className="mb-2 opacity-60">
                                        <span className="text-slate-500 select-none mr-2">{new Date().toLocaleTimeString('en-US', { hour12: false })}</span>
                                        <span className="italic">{live.partial}</span>
                                        <span className="inline-block w-1.5 h-4 bg-accent-cyan ml-0.5 animate-pulse align-text-bottom"></span>
                                    </div>
                                )}
                                {live.sentences.length === 0 && !live.partial && !live.statusMessage && (
                                    <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-3 opacity-60 select-none">
                                        <Activity size={32} strokeWidth={1} className="animate-pulse" />
                                        <p>Listening... speak to see transcription.</p>
                                    </div>
                                )}
                                {live.error && (
                                    <div className="text-xs text-red-400 mt-2">{live.error}</div>
                                )}
                            </>
                        ) : (
                            <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-3 opacity-60 select-none">
                                <Radio size={48} strokeWidth={1} />
                                <p>Live mode is off. Toggle the switch to start.</p>
                            </div>
                        )}
                    </div>
                </GlassCard>
            </div>

            {/* Right Bottom Scroll Indicator */}
            <div className={`absolute bottom-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-b-2xl transition-opacity duration-300 ${rightScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-linear-to-t from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to top, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)' }}></div>
            </div>
            <div className="absolute bottom-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)' }} />
        </div>
      </div>
      
      {/* 3. Bottom Drawer: Logs */}
      {logsRendered && (
         <div className={`flex-none grid grid-cols-1 lg:grid-cols-2 gap-6 overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${logsVisible ? 'h-72 pt-4 pb-1 opacity-100 translate-y-0 border-t border-white/10' : 'h-0 py-0 opacity-0 translate-y-4 border-t-0 border-transparent'}`}>
             <LogTerminal title="Server Output (Docker)" logs={serverLogs} color="magenta" className="h-full" />
             <LogTerminal title="Client Debug (Socket)" logs={clientLogs} color="cyan" className="h-full" />
         </div>
      )}

      {/* Fullscreen Visualizer Modal */}
      <FullscreenVisualizer isOpen={isFullscreenVisualizerOpen} onClose={() => setIsFullscreenVisualizerOpen(false)} analyserNode={activeAnalyser} />

    </div>
  );
};
