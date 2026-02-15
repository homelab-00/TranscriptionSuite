
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Mic, Radio, Settings2, RefreshCw, Languages, Copy, Volume2, VolumeX, Maximize2, Terminal, Activity, Server, Trash, Laptop, Power, ArrowRightLeft } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { StatusLight } from '../ui/StatusLight';
import { AudioVisualizer } from '../AudioVisualizer';
import { LogTerminal } from '../ui/LogTerminal';
import { CustomSelect } from '../ui/CustomSelect';
import { FullscreenVisualizer } from './FullscreenVisualizer';
import { useLanguages } from '../../src/hooks/useLanguages';

export const SessionView: React.FC = () => {
  // Global State
  const [showLogs, setShowLogs] = useState(false);
  const [logsRendered, setLogsRendered] = useState(false);
  const [logsVisible, setLogsVisible] = useState(false);
  const [isFullscreenVisualizerOpen, setIsFullscreenVisualizerOpen] = useState(false);

  // Real language list from server
  const { languages } = useLanguages();
  const languageOptions = languages.map(l => l.name);

  // Audio device enumeration
  const [micDevices, setMicDevices] = useState<string[]>([]);
  const [sysDevices, setSysDevices] = useState<string[]>([]);

  // Audio Configuration State
  const [audioSource, setAudioSource] = useState<'mic' | 'system'>('mic');
  const [micDevice, setMicDevice] = useState('Default Microphone');
  const [sysDevice, setSysDevice] = useState('Default Output');

  const enumerateDevices = useCallback(async () => {
    try {
      // Request permission first (needed to get labels)
      await navigator.mediaDevices.getUserMedia({ audio: true }).then(s => s.getTracks().forEach(t => t.stop()));
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(d => d.kind === 'audioinput' && d.label).map(d => d.label);
      const audioOutputs = devices.filter(d => d.kind === 'audiooutput' && d.label).map(d => d.label);
      setMicDevices(audioInputs.length > 0 ? audioInputs : ['Default Microphone']);
      setSysDevices(audioOutputs.length > 0 ? audioOutputs : ['Default Output']);
      if (audioInputs.length > 0 && !audioInputs.includes(micDevice)) setMicDevice(audioInputs[0]);
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
  const [isLive, setIsLive] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [liveLanguage, setLiveLanguage] = useState('Auto Detect');
  const [liveTranslate, setLiveTranslate] = useState(false);
  
  // Control Center State
  const [serverRunning, setServerRunning] = useState(true);
  const [clientConnected, setClientConnected] = useState(true);

  // System Health Check for Visual Effects
  const isSystemHealthy = serverRunning && clientConnected;

  // Scroll State
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  
  const [leftScrollState, setLeftScrollState] = useState({ top: false, bottom: false });
  const [rightScrollState, setRightScrollState] = useState({ top: false, bottom: false });

  // Mock Logs
  const serverLogs = [
    { timestamp: '12:41:27', source: 'System', message: 'Initializing TranscriptionSuite v2.0...', type: 'info' as const },
    { timestamp: '12:41:27', source: 'Docker', message: "Container 'whisper-backend' found.", type: 'success' as const },
    { timestamp: '12:41:27', source: 'Docker', message: 'Status: Running (Port 9000)', type: 'success' as const },
  ];

  const clientLogs = [
    { timestamp: '12:41:29', source: 'Client', message: 'Attempting handshake with localhost:9000...', type: 'info' as const },
    { timestamp: '12:41:29', source: 'Socket', message: 'Connection established (ID: 8821)', type: 'success' as const },
  ];

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
                 <div className="w-full h-full backdrop-blur-sm bg-gradient-to-b from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)' }}></div>
             </div>

             {/* Left Top Corner Mask */}
            <div className="absolute top-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at bottom left, transparent 1rem, black 1rem)' }} />

             {/* Main Scrollable Area for Left Column */}
             <div ref={leftScrollRef} className="flex-1 overflow-y-auto pr-3 pt-0 pb-0 custom-scrollbar space-y-6">
                
                {/* Unified Control Center */}
                <GlassCard title="Control Center" className={`bg-gradient-to-b from-glass-200 to-glass-100 flex-none transition-all duration-500 ease-in-out relative ${isSystemHealthy ? '!border-accent-cyan/50 !shadow-[0_20px_25px_-5px_rgba(0,0,0,0.3),_0_8px_10px_-6px_rgba(0,0,0,0.3),_inset_0_0_30px_rgba(34,211,238,0.15)] z-10' : ''}`}>
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
                                <Button variant="secondary" size="sm" onClick={() => setServerRunning(true)} className="text-xs px-3">Start Local</Button>
                                <Button variant="secondary" size="sm" onClick={() => setServerRunning(true)} className="text-xs px-3">Start Remote</Button>
                                <Button variant="danger" size="sm" onClick={() => setServerRunning(false)} className="text-xs px-3">Stop</Button>
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
                                    <span className="text-xs font-medium text-slate-400">{clientConnected ? 'Connected to Socket' : 'Disconnected'}</span>
                                    <StatusLight status={clientConnected ? 'active' : 'inactive'} className="w-2 h-2" animate={clientConnected} />
                                </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <Button variant="secondary" size="sm" onClick={() => setClientConnected(true)} className="text-xs px-3">Start Local</Button>
                                <Button variant="secondary" size="sm" onClick={() => setClientConnected(true)} className="text-xs px-3">Start Remote</Button>
                                <Button variant="danger" size="sm" onClick={() => setClientConnected(false)} className="text-xs px-3">Stop</Button>
                                <Button variant="secondary" size="sm" className="text-xs px-3 ml-auto text-slate-400 hover:text-white" icon={<Trash size={12}/>}>Unload Models</Button>
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
                    <div className="flex items-center justify-between gap-6 p-1">
                        <div className="flex flex-col flex-1 min-w-0">
                             <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2 ml-1">Source Language</label>
                             <div className="flex items-center gap-2">
                                <div className="p-2.5 rounded-xl bg-accent-magenta/10 text-accent-magenta shadow-inner border border-accent-magenta/5"><Languages size={18} /></div>
                                <CustomSelect value={mainLanguage} onChange={setMainLanguage} options={languageOptions} accentColor="magenta" className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:ring-1 focus:ring-accent-magenta outline-none hover:border-white/20 transition-all" />
                            </div>
                        </div>
                        <div className="h-12 w-px bg-white/10 self-end mb-1"></div>
                        <div className="flex flex-col items-center min-w-[100px]">
                            <label className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2 mt-1 text-center whitespace-nowrap">Translate to English</label>
                            <div className="h-[46px] flex items-center justify-center"><AppleSwitch checked={mainTranslate} onChange={setMainTranslate} size="sm" /></div>
                        </div>
                    </div>
                </GlassCard>
                
                <div className="pt-2">
                    <div onClick={toggleLogs} className={`w-full flex items-center justify-between px-4 py-3 rounded-2xl border transition-all duration-200 cursor-pointer group select-none ${showLogs ? 'bg-accent-cyan/10 border-accent-cyan/30 text-accent-cyan shadow-[0_0_15px_rgba(34,211,238,0.15)]' : 'bg-gradient-to-br from-glass-200 to-glass-100 backdrop-blur-xl border-glass-border text-slate-400 hover:text-white hover:brightness-110'}`}>
                        <div className="flex items-center gap-2"><Terminal size={18} /><span className="text-sm font-medium">System Logs</span></div>
                        <div className="flex items-center gap-3">
                             <div className={`transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] overflow-hidden ${showLogs ? 'w-24 opacity-100' : 'w-0 opacity-0'}`}>
                                  <Button variant="secondary" size="sm" className="h-8 w-full whitespace-nowrap text-xs text-slate-300" onClick={(e) => e.stopPropagation()} icon={<Copy size={14} />}>Copy All</Button>
                             </div>
                            <div className="text-xs uppercase tracking-wider font-bold">{showLogs ? 'Hide' : 'Show'}</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Left Bottom Scroll Indicator */}
            <div className={`absolute bottom-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-b-2xl transition-opacity duration-300 ${leftScrollState.bottom ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-gradient-to-t from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to top, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)' }}></div>
            </div>
            <div className="absolute bottom-0 right-3 w-4 h-4 z-20 pointer-events-none" style={{ ...maskStyle, maskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)', WebkitMaskImage: 'radial-gradient(circle at top left, transparent 1rem, black 1rem)' }} />
        </div>

        {/* Right Column: Visualizer & Live Mode (60%) */}
        <div className="lg:col-span-7 flex flex-col min-h-0 relative rounded-2xl overflow-hidden">
            
            {/* Right Top Scroll Indicator */}
             <div className={`absolute top-0 left-0 right-3 h-6 pointer-events-none z-20 overflow-hidden rounded-t-2xl transition-opacity duration-300 ${rightScrollState.top ? 'opacity-100' : 'opacity-0'}`}>
                 <div className="w-full h-full backdrop-blur-sm bg-gradient-to-b from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)' }}></div>
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
                        <AudioVisualizer />
                        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Button variant="secondary" size="icon" className="h-8 w-8 bg-black/50 backdrop-blur-sm" icon={<Maximize2 size={14}/>} onClick={() => setIsFullscreenVisualizerOpen(true)} />
                        </div>
                    </div>
                </GlassCard>

                {/* Live Mode (Text + Controls) */}
                <GlassCard className="flex-1 min-h-[calc(100vh-30rem)] flex flex-col transition-all duration-300" title="Live Mode" action={<Button variant="ghost" size="sm" icon={<Copy size={14} />}>Copy</Button>}>
                    
                    {/* Live Mode Controls Toolbar */}
                    <div className="flex items-center gap-2 p-1 pb-4 mb-4 border-b border-white/5 overflow-x-auto flex-nowrap custom-scrollbar no-scrollbar flex-none">
                        <div className="flex items-center gap-2 h-8 shrink-0">
                                <span className={`text-xs font-bold uppercase tracking-wider ${isLive ? 'text-green-400' : 'text-slate-500'}`}>{isLive ? 'Active' : 'Offline'}</span>
                                <AppleSwitch checked={isLive} onChange={setIsLive} size="sm" />
                        </div>
                        <Button variant={isMuted ? 'danger' : 'secondary'} size="sm" icon={isMuted ? <VolumeX size={14}/> : <Volume2 size={14}/>} onClick={() => setIsMuted(!isMuted)} className={`h-8 shrink-0 whitespace-nowrap ${isMuted ? "bg-red-500/20 text-red-400 border-red-500/30" : "text-slate-300"}`}>{isMuted ? 'Muted' : 'Audio On'}</Button>
                        <div className="h-5 w-px bg-white/10 mx-0.5 shrink-0"></div>
                        <div className="flex items-center gap-2 h-8 shrink-0">
                            <div className="h-full aspect-square flex items-center justify-center rounded-lg bg-accent-magenta/10 text-accent-magenta border border-accent-magenta/5"><Languages size={15} /></div>
                            <CustomSelect value={liveLanguage} onChange={setLiveLanguage} options={languageOptions} accentColor="magenta" className="bg-white/5 border border-white/10 rounded-lg px-3 py-1 text-sm text-slate-300 focus:ring-1 focus:ring-accent-magenta outline-none h-full min-w-[130px]" />
                        </div>
                        <div className="h-5 w-px bg-white/10 mx-0.5 shrink-0"></div>
                        <div className="flex items-center gap-2 h-8 shrink-0">
                            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest whitespace-nowrap">Translate to English</span>
                            <AppleSwitch checked={liveTranslate} onChange={setLiveTranslate} size="sm" />
                        </div>
                    </div>

                    {/* Transcript Area - Added selectable-text class */}
                    <div className="flex-1 bg-black/20 rounded-xl border border-white/5 p-4 overflow-y-auto font-mono text-sm leading-relaxed text-slate-300 shadow-inner custom-scrollbar relative min-h-0 selectable-text">
                        {isLive ? (
                            <>
                                <span className="text-slate-500 select-none mr-2">12:01:45</span>
                                <span className="text-accent-cyan">Speaker 1:</span> Welcome to the Transcription Suite demo. 
                                <br/><br/>
                                <span className="text-slate-500 select-none mr-2">12:01:52</span>
                                <span className="text-accent-magenta">System:</span> Start speaking to see live transcription appear here in real-time.
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
                 <div className="w-full h-full backdrop-blur-sm bg-gradient-to-t from-white/10 to-transparent" style={{ maskImage: 'linear-gradient(to top, black 50%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to top, black 50%, transparent 100%)' }}></div>
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
      <FullscreenVisualizer isOpen={isFullscreenVisualizerOpen} onClose={() => setIsFullscreenVisualizerOpen(false)} />

    </div>
  );
};
