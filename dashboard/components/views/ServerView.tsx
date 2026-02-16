import React, { useState, useCallback, useEffect } from 'react';
import { Box, Cpu, HardDrive, Download, Loader2, RefreshCw, Gpu, CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp, RotateCcw } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { CustomSelect } from '../ui/CustomSelect';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useDocker } from '../../src/hooks/useDocker';
import { apiClient } from '../../src/api/client';
import { getConfig } from '../../src/config/store';

type RuntimeProfile = 'gpu' | 'cpu';

export const ServerView: React.FC = () => {
  const { status: adminStatus } = useAdminStatus();
  const docker = useDocker();

  // Model selection state
  const [transcriber, setTranscriber] = useState('');
  const [liveModel, setLiveModel] = useState('');
  const [modelsLoading, setModelsLoading] = useState(false);

  // Runtime profile (persisted in electron-store)
  const [runtimeProfile, setRuntimeProfile] = useState<RuntimeProfile>('gpu');

  // Load persisted runtime profile on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config.get('server.runtimeProfile').then((val: unknown) => {
        if (val === 'gpu' || val === 'cpu') setRuntimeProfile(val);
      }).catch(() => {});
    }
  }, []);

  // Persist runtime profile changes
  const handleRuntimeProfileChange = useCallback((profile: RuntimeProfile) => {
    setRuntimeProfile(profile);
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config.set('server.runtimeProfile', profile);
    }
  }, []);

  // Derive status from Docker hook
  const containerStatus = docker.container;
  const isRunning = containerStatus.running;
  const statusLabel = containerStatus.exists
    ? containerStatus.status.charAt(0).toUpperCase() + containerStatus.status.slice(1)
    : 'Not Found';

  // Derive model names from admin status
  const realModel = adminStatus?.config?.transcription?.model ?? 'large-v3';
  const realLiveModel = adminStatus?.config?.live_transcription?.model ?? 'tiny';
  const activeTranscriber = transcriber || realModel;
  const activeLiveModel = liveModel || realLiveModel;

  // Image selection state — "Most Recent (auto)" always picks the newest available tag
  const MOST_RECENT = 'Most Recent (auto)';
  const imageOptions = docker.images.length > 0
    ? [MOST_RECENT, ...docker.images.map(i => i.fullName)]
    : ['ghcr.io/homelab-00/transcriptionsuite-server:latest'];
  const [selectedImage, setSelectedImage] = useState(imageOptions[0]);
  const resolvedImage = selectedImage === MOST_RECENT && docker.images.length > 0
    ? docker.images[0].fullName
    : selectedImage;
  const selectedTagForActions = resolvedImage.split(':').pop() || 'latest';
  const selectedTagForStart = docker.images.length > 0 ? selectedTagForActions : undefined;

  // Start container with HF token from config
  const handleStartContainer = useCallback(async (mode: 'local' | 'remote') => {
    const hfToken = await getConfig<string>('server.hfToken') || undefined;
    await docker.startContainer(mode, runtimeProfile, undefined, selectedTagForStart, hfToken);
  }, [docker, runtimeProfile, selectedTagForStart]);

  // ─── Setup Checklist ────────────────────────────────────────────────────────

  const [setupDismissed, setSetupDismissed] = useState(true); // hide until loaded
  const [setupExpanded, setSetupExpanded] = useState(true);
  const [gpuInfo, setGpuInfo] = useState<{ gpu: boolean; toolkit: boolean } | null>(null);

  // Load dismissed state and GPU info on mount
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      api.config.get('app.setupDismissed').then((val: unknown) => {
        setSetupDismissed(val === true);
      }).catch(() => setSetupDismissed(false));
    } else {
      setSetupDismissed(false);
    }
    if (api?.docker?.checkGpu) {
      api.docker.checkGpu().then((info: { gpu: boolean; toolkit: boolean }) => {
        setGpuInfo(info);
        // Auto-set runtime profile based on GPU detection (only if not already configured)
        api.config?.get('server.runtimeProfile').then((val: unknown) => {
          if (!val && info.gpu && info.toolkit) {
            handleRuntimeProfileChange('gpu');
          } else if (!val && !info.gpu) {
            handleRuntimeProfileChange('cpu');
          }
        }).catch(() => {});
      }).catch(() => setGpuInfo(null));
    }
  }, []);

  // Setup checks
  const setupChecks = [
    {
      label: 'Docker installed',
      ok: docker.available,
      hint: 'Install Docker Engine or Docker Desktop',
    },
    {
      label: 'Docker image pulled',
      ok: docker.images.length > 0,
      hint: 'Pull an image below to get started',
    },
    {
      label: 'NVIDIA GPU detected',
      ok: gpuInfo?.gpu ?? false,
      warn: gpuInfo !== null && !gpuInfo.gpu,
      hint: gpuInfo?.gpu ? (gpuInfo.toolkit ? 'nvidia-container-toolkit ready' : 'Run: sudo nvidia-ctk runtime configure --runtime=docker') : 'CPU mode will be used (slower)',
    },
  ];
  const allPassed = setupChecks.every(c => c.ok);
  const showChecklist = !setupDismissed || !allPassed;

  const handleDismissSetup = useCallback(() => {
    setSetupDismissed(true);
    const api = (window as any).electronAPI;
    api?.config?.set('app.setupDismissed', true);
  }, []);

  // Model load/unload handlers
  const handleLoadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      await apiClient.loadModels();
    } catch { /* errors shown via admin status */ }
    setModelsLoading(false);
  }, []);

  const handleUnloadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      await apiClient.unloadModels();
    } catch { /* ignore */ }
    setModelsLoading(false);
  }, []);

  return (
    <div className="w-full h-full overflow-y-auto custom-scrollbar">
      <div className="flex flex-col space-y-6 max-w-4xl mx-auto pb-10 p-6 pt-8">
         <div className="flex-none pt-2">
             <h1 className="text-3xl font-bold text-white tracking-tight mb-2">Server Configuration</h1>
             <p className="text-slate-400 -mt-1">Manage runtime resources and persistent storage.</p>
         </div>

         {/* Setup checklist — shown on first run or when prerequisites are missing */}
         {showChecklist && (
           <div className={`rounded-xl border transition-all duration-300 overflow-hidden ${allPassed ? 'border-green-500/20 bg-green-500/5' : 'border-accent-orange/20 bg-accent-orange/5'}`}>
             <button
               onClick={() => setSetupExpanded(!setupExpanded)}
               className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/5 transition-colors"
             >
               <div className="flex items-center gap-3">
                 {allPassed
                   ? <CheckCircle2 size={18} className="text-green-400" />
                   : <AlertTriangle size={18} className="text-accent-orange" />
                 }
                 <span className="text-sm font-semibold text-white">
                   {allPassed ? 'Setup Complete' : 'Setup Checklist'}
                 </span>
                 <span className="text-xs text-slate-500 font-mono">
                   {setupChecks.filter(c => c.ok).length}/{setupChecks.length} checks passed
                 </span>
               </div>
               <div className="flex items-center gap-2">
                 {!allPassed && (
                   <div
                     role="button"
                     tabIndex={0}
                     onClick={(e) => { e.stopPropagation(); docker.retryDetection(); }}
                     onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); docker.retryDetection(); } }}
                     className="text-xs text-slate-400 hover:text-accent-cyan transition-colors px-2 py-1 rounded hover:bg-white/10 flex items-center gap-1 cursor-pointer"
                     title="Re-check Docker, images, and GPU"
                   >
                     <RotateCcw size={12} />
                     Retry
                   </div>
                 )}
                 {allPassed && (
                   <div
                     role="button"
                     tabIndex={0}
                     onClick={(e) => { e.stopPropagation(); handleDismissSetup(); }}
                     onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); handleDismissSetup(); } }}
                     className="text-xs text-slate-400 hover:text-white transition-colors px-2 py-1 rounded hover:bg-white/10 cursor-pointer"
                   >
                     Dismiss
                   </div>
                 )}
                 {setupExpanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
               </div>
             </button>
             {setupExpanded && (
               <div className="px-5 pb-4 space-y-2.5">
                 {setupChecks.map((check, i) => (
                   <div key={i} className="flex items-center gap-3">
                     {check.ok
                       ? <CheckCircle2 size={15} className="text-green-400 shrink-0" />
                       : check.warn
                       ? <AlertTriangle size={15} className="text-accent-orange shrink-0" />
                       : <XCircle size={15} className="text-red-400 shrink-0" />
                     }
                     <span className={`text-sm ${check.ok ? 'text-slate-300' : 'text-white'}`}>{check.label}</span>
                     <span className="text-xs text-slate-500 ml-auto">{check.hint}</span>
                   </div>
                 ))}
               </div>
             )}
           </div>
         )}
         
         {/* 1. Image Card */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className={`absolute -left-4.25 top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${docker.images.length > 0 ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
              <Download size={14} />
           </div>
           <GlassCard 
              title="1. Docker Image" 
              className={`transition-all duration-500 ease-in-out ${docker.images.length > 0 ? 'border-accent-cyan/30 shadow-[0_0_15px_rgba(34,211,238,0.15)]' : ''}`}
           >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-4">
                      <div className="flex items-center space-x-3">
                          <StatusLight status={docker.images.length > 0 ? 'active' : 'inactive'} />
                          <span className={`font-mono text-sm transition-colors ${docker.images.length > 0 ? 'text-slate-300' : 'text-slate-500'}`}>
                              {docker.images.length > 0 ? `${docker.images.length} image${docker.images.length > 1 ? 's' : ''} available` : 'No images'}
                          </span>
                          
                          {docker.images.length > 0 && docker.images[0] && (
                            <div className="flex gap-2 transition-opacity duration-300">
                              <span className="text-xs bg-white/10 px-2 py-0.5 rounded text-slate-400">{docker.images[0].created.split(' ')[0]}</span>
                              <span className="text-xs bg-white/10 px-2 py-0.5 rounded text-slate-400">{docker.images[0].size}</span>
                            </div>
                          )}
                      </div>
                      <div>
                           <label className="text-xs text-slate-500 block mb-1 font-medium">Select Image Tag</label>
                           <CustomSelect 
                              value={selectedImage}
                              onChange={setSelectedImage}
                              options={imageOptions}
                              className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none transition-shadow"
                           />
                      </div>
                  </div>
                  <div className="flex flex-col justify-end space-y-2">
                       <Button variant="secondary" className="w-full h-10" onClick={() => docker.refreshImages()} disabled={docker.operating}>
                         <RefreshCw size={14} className="mr-2" />Scan Local Images
                       </Button>
                       <Button variant="secondary" className="w-full h-10" onClick={() => docker.pullImage(selectedTagForActions)} disabled={docker.operating}>
                         {docker.pulling ? <><Loader2 size={14} className="animate-spin mr-2" /> Pulling...</> : 'Fetch Fresh Image'}
                       </Button>
                       {docker.pulling && (
                         <Button variant="danger" className="w-full h-10" onClick={() => docker.cancelPull()}>
                           Cancel Pull
                         </Button>
                       )}
                       <Button variant="danger" className="w-full h-10" onClick={() => docker.removeImage(selectedTagForActions)} disabled={docker.operating || docker.images.length === 0}>Remove Image</Button>
                  </div>
              </div>
              {docker.operationError && (
                <div className="mt-3 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{docker.operationError}</div>
              )}
           </GlassCard>
         </div>

         {/* 2. Container Card (Config & Controls) */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className={`absolute -left-4.25 top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${isRunning ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
              <Box size={16} />
           </div>
           <GlassCard 
             title="2. Instance Settings"
             className={`transition-all duration-500 ease-in-out ${isRunning ? 'border-accent-cyan/30 shadow-[0_0_15px_rgba(34,211,238,0.15)]' : ''}`}
           >
               <div className="space-y-6">
                   {/* Runtime Profile Selector */}
                   <div className="flex items-center gap-4 pb-4 border-b border-white/5">
                        <label className="text-xs text-slate-500 font-medium uppercase tracking-wider whitespace-nowrap">Runtime</label>
                        <div className="flex gap-2">
                            <button
                                onClick={() => handleRuntimeProfileChange('gpu')}
                                disabled={isRunning}
                                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all border ${
                                    runtimeProfile === 'gpu'
                                        ? 'bg-accent-cyan/15 border-accent-cyan/40 text-accent-cyan shadow-[0_0_10px_rgba(34,211,238,0.15)]'
                                        : 'bg-white/5 border-white/10 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                                } ${isRunning ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                            >
                                <Gpu size={14} />
                                GPU (CUDA)
                            </button>
                            <button
                                onClick={() => handleRuntimeProfileChange('cpu')}
                                disabled={isRunning}
                                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all border ${
                                    runtimeProfile === 'cpu'
                                        ? 'bg-accent-orange/15 border-accent-orange/40 text-accent-orange shadow-[0_0_10px_rgba(255,145,0,0.15)]'
                                        : 'bg-white/5 border-white/10 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                                } ${isRunning ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                            >
                                <Cpu size={14} />
                                CPU Only
                            </button>
                        </div>
                        {runtimeProfile === 'cpu' && !isRunning && (
                            <span className="text-xs text-slate-500 italic">Slower transcription, no NVIDIA GPU required</span>
                        )}
                   </div>

                   <div className="flex flex-wrap items-center gap-5">
                        <div className="flex items-center space-x-3 pr-5 border-r border-white/10 h-6 shrink-0">
                          <StatusLight 
                            status={isRunning ? 'active' : containerStatus.exists ? 'warning' : 'inactive'} 
                            animate={isRunning} 
                          />
                          <span className={`font-mono text-sm transition-colors ${
                              isRunning ? 'text-slate-300' : 
                              containerStatus.exists ? 'text-accent-orange' : 'text-slate-500'
                          }`}>
                            {statusLabel}
                          </span>
                        </div>

                        <div className="flex-1 flex flex-wrap items-center justify-between gap-4 min-w-0">
                            <div className="flex gap-2">
                                <Button variant="secondary" className="h-9 px-4" onClick={() => handleStartContainer('local')} disabled={docker.operating || isRunning}>
                                  {docker.operating ? <Loader2 size={14} className="animate-spin" /> : 'Start Local'}
                                </Button>
                                <Button variant="secondary" className="h-9 px-4" onClick={() => handleStartContainer('remote')} disabled={docker.operating || isRunning}>Start Remote</Button>
                                <Button variant="danger" className="h-9 px-4" onClick={() => docker.stopContainer()} disabled={docker.operating || !isRunning}>Stop</Button>
                            </div>
                            <Button variant="danger" className="h-9 px-4" onClick={() => docker.removeContainer()} disabled={docker.operating || isRunning}>
                                Remove Container
                            </Button>
                        </div>
                   </div>
                   
                   {containerStatus.startedAt && isRunning && (
                     <div className="text-xs text-slate-500 font-mono">
                       Started: {new Date(containerStatus.startedAt).toLocaleString()}
                       {containerStatus.health && <span className="ml-3">Health: <span className={containerStatus.health === 'healthy' ? 'text-green-400' : 'text-accent-orange'}>{containerStatus.health}</span></span>}
                     </div>
                   )}
               </div>
           </GlassCard>
         </div>

         {/* 3. Models Card */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className="absolute -left-4.25 top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
              <Cpu size={14} />
           </div>
           <GlassCard title="3. AI Models Configuration">
              <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                          <label className="text-sm text-slate-300 font-medium">Main Transcriber</label>
                          <CustomSelect 
                              value={activeTranscriber}
                              onChange={setTranscriber}
                              options={[realModel, 'large-v3', 'large-v2', 'medium', 'medium.en', 'small', 'base', 'tiny'].filter((v, i, a) => a.indexOf(v) === i)}
                              accentColor="magenta"
                              className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-magenta outline-none transition-shadow"
                          />
                      </div>
                      <div className="space-y-2">
                          <label className="text-sm text-slate-300 font-medium">Live Mode Model</label>
                          <CustomSelect 
                              value={activeLiveModel}
                              onChange={setLiveModel}
                              options={[realLiveModel, 'tiny', 'base', 'small', 'medium'].filter((v, i, a) => a.indexOf(v) === i)}
                              className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none transition-shadow"
                          />
                      </div>
                  </div>
                  <div className="flex gap-2 pt-2 border-t border-white/5">
                      <Button variant="secondary" className="h-9 px-4" onClick={handleLoadModels} disabled={modelsLoading || !isRunning}>
                        {modelsLoading ? <><Loader2 size={14} className="animate-spin mr-2" /> Loading...</> : 'Load Models'}
                      </Button>
                      <Button variant="danger" className="h-9 px-4" onClick={handleUnloadModels} disabled={modelsLoading || !isRunning}>
                        Unload Models
                      </Button>
                      {adminStatus?.models_loaded !== undefined && (
                        <span className={`text-xs self-center ml-auto font-mono ${adminStatus.models_loaded ? 'text-green-400' : 'text-slate-500'}`}>
                          {adminStatus.models_loaded ? 'Models Loaded' : 'Models Not Loaded'}
                        </span>
                      )}
                  </div>
              </div>
           </GlassCard>
         </div>

          {/* 4. Volumes Card */}
          <div className="relative pl-8 border-l-2 border-white/10 pb-2 last:border-0 last:pb-0 shrink-0">
           <div className="absolute -left-4.25 top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
              <HardDrive size={14} />
           </div>
           <GlassCard title="4. Persistent Volumes" action={<Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={() => docker.refreshVolumes()}>Refresh</Button>}>
              <div className="space-y-4">
                  {docker.volumes.length > 0 ? docker.volumes.map((vol) => {
                      const colorMap: Record<string, string> = {
                        'transcriptionsuite-data': 'bg-blue-500',
                        'transcriptionsuite-models': 'bg-purple-500',
                        'transcriptionsuite-runtime': 'bg-orange-500',
                        'transcriptionsuite-uv-cache': 'bg-teal-500',
                      };
                      return (
                        <div key={vol.name} className="flex items-center justify-between text-sm py-1">
                            <div className="flex items-center gap-3">
                                <div className={`w-2 h-2 rounded-full ${colorMap[vol.name] || 'bg-slate-500'}`}></div>
                                <span className="text-slate-300">{vol.label}</span>
                            </div>
                            <div className="flex items-center gap-4">
                                <span className="font-mono text-slate-500">{vol.size || '—'}</span>
                                <span className={`text-xs ${vol.mountpoint ? 'text-green-400' : 'text-slate-500'}`}>
                                  {vol.mountpoint ? 'Mounted' : 'Not Found'}
                                </span>
                            </div>
                        </div>
                      );
                  }) : (
                    <div className="text-sm text-slate-500 text-center py-2">
                      {docker.available ? 'No volumes found' : 'Docker not available'}
                    </div>
                  )}
                  
                  {docker.volumes.length > 0 && (
                    <div className="pt-4 mt-4 border-t border-white/5 flex gap-2 overflow-x-auto pb-2">
                        {docker.volumes.map((vol) => (
                          <Button 
                            key={vol.name}
                            size="sm" 
                            variant="danger" 
                            className="text-xs whitespace-nowrap" 
                            onClick={() => docker.removeVolume(vol.name)}
                            disabled={docker.operating || isRunning}
                          >
                            Clear {vol.label.replace(' Volume', '')}
                          </Button>
                        ))}
                    </div>
                  )}
              </div>
           </GlassCard>
         </div>

      </div>
    </div>
  );
};
