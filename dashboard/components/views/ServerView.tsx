import React, { useState } from 'react';
import { Box, Cpu, HardDrive, Download, Terminal } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import { Button } from '../ui/Button';
import { StatusLight } from '../ui/StatusLight';
import { CustomSelect } from '../ui/CustomSelect';

export const ServerView: React.FC = () => {
  const [imageTag, setImageTag] = useState('transcription-suite:latest');
  const [transcriber, setTranscriber] = useState('large-v3');
  const [liveModel, setLiveModel] = useState('tiny (Low Latency)');
  
  // Dynamic State for Image
  const [imageStatus, setImageStatus] = useState<'active' | 'inactive'>('active');
  
  // State to manage the running status of the instance
  // Expanded to support 'stopped' (Orange) and 'removed' (Grey)
  const [status, setStatus] = useState<'active' | 'stopped' | 'removed'>('active');

  return (
    <div className="w-full h-full overflow-y-auto custom-scrollbar">
      <div className="flex flex-col space-y-6 max-w-4xl mx-auto pb-10 p-6 pt-8">
         <div className="flex-none pt-2">
             <h1 className="text-3xl font-bold text-white tracking-tight mb-2">Server Configuration</h1>
             <p className="text-slate-400 -mt-1">Manage runtime resources and persistent storage.</p>
         </div>
         
         {/* 1. Image Card */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           {/* Icon with Dynamic Accent */}
           <div className={`absolute -left-[17px] top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${imageStatus === 'active' ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
              <Download size={14} />
           </div>
           <GlassCard 
              title="1. Docker Image" 
              className={`transition-all duration-500 ease-in-out ${imageStatus === 'active' ? 'border-accent-cyan/30 shadow-[0_0_15px_rgba(34,211,238,0.15)]' : ''}`}
           >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-4">
                      <div className="flex items-center space-x-3">
                          <StatusLight status={imageStatus} />
                          <span className={`font-mono text-sm transition-colors ${imageStatus === 'active' ? 'text-slate-300' : 'text-slate-500'}`}>
                              {imageStatus === 'active' ? 'Available' : 'Unavailable'}
                          </span>
                          
                          {/* Metadata Badges - Fade out when inactive */}
                          <div className={`flex gap-2 transition-opacity duration-300 ${imageStatus === 'active' ? 'opacity-100' : 'opacity-0'}`}>
                            <span className="text-xs bg-white/10 px-2 py-0.5 rounded text-slate-400">2026-01-15</span>
                            <span className="text-xs bg-white/10 px-2 py-0.5 rounded text-slate-400">1.2 GB</span>
                          </div>
                      </div>
                      <div className={`transition-opacity duration-300 ${imageStatus === 'active' ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                           <label className="text-xs text-slate-500 block mb-1 font-medium">Select Image Tag</label>
                           <CustomSelect 
                              value={imageTag}
                              onChange={setImageTag}
                              options={['transcription-suite:latest', 'transcription-suite:v2.4.0']}
                              className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none transition-shadow"
                           />
                      </div>
                  </div>
                  <div className="flex flex-col justify-end space-y-2">
                       <Button variant="secondary" className="w-full h-10" onClick={() => setImageStatus('active')}>Fetch Fresh Image</Button>
                       <Button variant="danger" className="w-full h-10" onClick={() => setImageStatus('inactive')}>Remove Image</Button>
                  </div>
              </div>
           </GlassCard>
         </div>

         {/* 2. Container Card (Config & Controls) */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           {/* Icon with Dynamic Accent based on 'active' status */}
           <div className={`absolute -left-[17px] top-0 w-8 h-8 rounded-full border-4 border-slate-900 flex items-center justify-center z-10 transition-colors duration-300 ${status === 'active' ? 'bg-accent-cyan text-slate-900 shadow-[0_0_15px_rgba(34,211,238,0.5)]' : 'bg-slate-800 text-slate-300'}`}>
              <Box size={16} />
           </div>
           <GlassCard 
             title="2. Instance Settings"
             className={`transition-all duration-500 ease-in-out ${status === 'active' ? 'border-accent-cyan/30 shadow-[0_0_15px_rgba(34,211,238,0.15)]' : ''}`}
           >
               <div className="space-y-6">
                   {/* Instance Status & Controls Row */}
                   <div className="flex flex-wrap items-center gap-5">
                        {/* Status Light Section */}
                        <div className="flex items-center space-x-3 pr-5 border-r border-white/10 h-6 shrink-0">
                          <StatusLight 
                            status={status === 'active' ? 'active' : status === 'stopped' ? 'warning' : 'inactive'} 
                            animate={status === 'active'} 
                          />
                          <span className={`font-mono text-sm transition-colors ${
                              status === 'active' ? 'text-slate-300' : 
                              status === 'stopped' ? 'text-accent-orange' : 'text-slate-500'
                          }`}>
                            {status === 'active' ? 'Running' : status === 'stopped' ? 'Stopped' : 'Removed'}
                          </span>
                        </div>

                        {/* Controls Section - Remaining Buttons */}
                        <div className="flex-1 flex flex-wrap items-center justify-between gap-4 min-w-0">
                            <div className="flex gap-2">
                                <Button variant="secondary" className="h-9 px-4" onClick={() => setStatus('active')}>Start Local</Button>
                                <Button variant="secondary" className="h-9 px-4" onClick={() => setStatus('active')}>Start Remote</Button>
                                <Button variant="danger" className="h-9 px-4" onClick={() => setStatus('stopped')}>Stop</Button>
                            </div>
                            <Button variant="danger" className="h-9 px-4" onClick={() => setStatus('removed')}>
                                Remove Container
                            </Button>
                        </div>
                   </div>
                   
                   <div className={`space-y-1 transition-opacity duration-300 ${status === 'removed' ? 'opacity-50 pointer-events-none' : 'opacity-100'}`}>
                      <label className="text-xs text-slate-500 font-medium">Auth Token (for remote access)</label>
                      <div className="flex gap-2">
                          <input readOnly value="a1b2c3d4e5f6..." type="password" className="flex-1 h-9 bg-black/40 font-mono text-sm px-3 rounded-lg border border-white/10 text-slate-400 outline-none focus:border-white/20" />
                          <Button variant="secondary" size="sm" className="h-9">Copy</Button>
                      </div>
                   </div>
               </div>
           </GlassCard>
         </div>

         {/* 3. Models Card */}
         <div className="relative pl-8 border-l-2 border-white/10 pb-8 last:border-0 last:pb-0 shrink-0">
           <div className="absolute -left-[17px] top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
              <Cpu size={14} />
           </div>
           <GlassCard title="3. AI Models Configuration">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                      <label className="text-sm text-slate-300 font-medium">Main Transcriber</label>
                      <CustomSelect 
                          value={transcriber}
                          onChange={setTranscriber}
                          options={['large-v3', 'medium.en']}
                          accentColor="magenta"
                          className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-magenta outline-none transition-shadow"
                      />
                  </div>
                  <div className="space-y-2">
                      <label className="text-sm text-slate-300 font-medium">Live Mode Model</label>
                      <CustomSelect 
                          value={liveModel}
                          onChange={setLiveModel}
                          options={['tiny (Low Latency)', 'base']}
                          className="w-full h-10 bg-white/5 border border-white/10 rounded-lg px-3 text-sm text-white focus:ring-1 focus:ring-accent-cyan outline-none transition-shadow"
                      />
                  </div>
              </div>
           </GlassCard>
         </div>

          {/* 4. Volumes Card */}
          <div className="relative pl-8 border-l-2 border-white/10 pb-2 last:border-0 last:pb-0 shrink-0">
           <div className="absolute -left-[17px] top-0 w-8 h-8 rounded-full bg-slate-800 border-4 border-slate-900 flex items-center justify-center z-10 text-slate-300">
              <HardDrive size={14} />
           </div>
           <GlassCard title="4. Persistent Volumes">
              <div className="space-y-4">
                  {[
                      { label: 'Data Volume', size: '42.5 MB', color: 'bg-blue-500' },
                      { label: 'Models Volume', size: '3.1 GB', color: 'bg-purple-500' },
                      { label: 'Runtime Volume', size: '1.8 GB', color: 'bg-orange-500' },
                      { label: 'UV Cache Volume', size: '256 MB', color: 'bg-teal-500' }
                  ].map((vol) => (
                      <div key={vol.label} className="flex items-center justify-between text-sm py-1">
                          <div className="flex items-center gap-3">
                              <div className={`w-2 h-2 rounded-full ${vol.color}`}></div>
                              <span className="text-slate-300">{vol.label}</span>
                          </div>
                          <div className="flex items-center gap-4">
                              <span className="font-mono text-slate-500">{vol.size}</span>
                              <span className="text-green-400 text-xs">Mounted</span>
                          </div>
                      </div>
                  ))}
                  
                  <div className="pt-4 mt-4 border-t border-white/5 flex gap-2 overflow-x-auto pb-2">
                      <Button size="sm" variant="danger" className="text-xs whitespace-nowrap">Clear Data</Button>
                      <Button size="sm" variant="danger" className="text-xs whitespace-nowrap">Clear Models</Button>
                      <Button size="sm" variant="danger" className="text-xs whitespace-nowrap">Clear Runtime</Button>
                      <Button size="sm" variant="danger" className="text-xs whitespace-nowrap">Clear UV Cache</Button>
                  </div>
              </div>
           </GlassCard>
         </div>

      </div>
    </div>
  );
};