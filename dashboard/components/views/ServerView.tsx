import React, { useState, useCallback } from 'react';
import { Box, Cpu, HardDrive, Download, Loader2, RefreshCw } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { CustomSelect } from '../ui/CustomSelect';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import { useDocker } from '../../src/hooks/useDocker';
import { apiClient } from '../../src/api/client';

export const ServerView: React.FC = () => {
  const { status: adminStatus } = useAdminStatus();
  const docker = useDocker();

  // Model selection state
  const [transcriber, setTranscriber] = useState('');
  const [liveModel, setLiveModel] = useState('');
  const [modelsLoading, setModelsLoading] = useState(false);

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

  // Image selection state
  const imageOptions = docker.images.length > 0
    ? docker.images.map(i => i.fullName)
    : ['transcription-suite:latest'];
  const [selectedImage, setSelectedImage] = useState(imageOptions[0]);
  const selectedTag = selectedImage.split(':').pop() || 'latest';

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
         
         {/* 1. Image Card */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className={`absolute -left-[17px] top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${docker.images.length > 0 ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
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
                       <Button variant="secondary" className="w-full h-10" onClick={() => docker.pullImage(selectedTag)} disabled={docker.operating}>
                         {docker.operating ? <><Loader2 size={14} className="animate-spin mr-2" /> Pulling...</> : 'Fetch Fresh Image'}
                       </Button>
                       <Button variant="danger" className="w-full h-10" onClick={() => docker.removeImage(selectedTag)} disabled={docker.operating || docker.images.length === 0}>Remove Image</Button>
                  </div>
              </div>
              {docker.operationError && (
                <div className="mt-3 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{docker.operationError}</div>
              )}
           </GlassCard>
         </div>

         {/* 2. Container Card (Config & Controls) */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className={`absolute -left-[17px] top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${isRunning ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
              <Box size={16} />
           </div>
           <GlassCard 
             title="2. Instance Settings"
             className={`transition-all duration-500 ease-in-out ${isRunning ? 'border-accent-cyan/30 shadow-[0_0_15px_rgba(34,211,238,0.15)]' : ''}`}
           >
               <div className="space-y-6">
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
                                <Button variant="secondary" className="h-9 px-4" onClick={() => docker.startContainer('local')} disabled={docker.operating || isRunning}>
                                  {docker.operating ? <Loader2 size={14} className="animate-spin" /> : 'Start Local'}
                                </Button>
                                <Button variant="secondary" className="h-9 px-4" onClick={() => docker.startContainer('remote')} disabled={docker.operating || isRunning}>Start Remote</Button>
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
           <div className="absolute -left-[17px] top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
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
           <div className="absolute -left-[17px] top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
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