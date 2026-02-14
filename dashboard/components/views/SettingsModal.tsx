
import React, { useState, useEffect } from 'react';
import { X, Search, ChevronDown, FileText, RefreshCw, AlertTriangle, Save, Database, Server, Laptop, AppWindow, Eye, EyeOff } from 'lucide-react';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const tabs = ['App', 'Client', 'Server', 'Notebook'];

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState('App');
  const [serverSearch, setServerSearch] = useState('');
  const [showAuthToken, setShowAuthToken] = useState(false);

  // Animation State
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  // Mock State for Settings
  const [appSettings, setAppSettings] = useState({
    autoCopy: false,
    showNotifications: true,
    stopServerOnQuit: true,
  });

  const [clientSettings, setClientSettings] = useState({
    gracePeriod: 0.5,
    constrainSpeakers: false,
    numSpeakers: 2,
    autoAddNotebook: true,
    localHost: 'http://localhost',
    remoteHost: '',
    useRemote: false,
    authToken: 'sk-1234567890abcdef',
    port: 9000,
    useHttps: false,
  });

  // Server Configuration Mock Data
  const serverConfig = [
    {
      category: 'Model Defaults',
      description: 'Default parameters for the Whisper inference engine.',
      settings: [
        { key: 'beam_size', value: '5', type: 'int', description: 'Number of beams in beam search' },
        { key: 'best_of', value: '5', type: 'int', description: 'Number of candidates when sampling' },
        { key: 'patience', value: '1.0', type: 'float', description: 'Beam search patience factor' },
      ]
    },
    {
      category: 'VAD Parameters',
      description: 'Voice Activity Detection settings.',
      settings: [
        { key: 'vad_onset', value: '0.5', type: 'float', description: 'Speech start threshold' },
        { key: 'vad_offset', value: '0.363', type: 'float', description: 'Speech end threshold' },
        { key: 'min_silence_duration_ms', value: '1000', type: 'int', description: 'Minimum silence to split segments' },
      ]
    },
    {
      category: 'Compute Settings',
      description: 'Hardware acceleration and thread management.',
      settings: [
        { key: 'device', value: 'cuda', type: 'string', description: 'Compute device (cuda/cpu)' },
        { key: 'compute_type', value: 'float16', type: 'string', description: 'Quantization type' },
        { key: 'num_workers', value: '4', type: 'int', description: 'DataLoader workers' },
      ]
    }
  ];

  // Animation Lifecycle
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;
    if (isOpen) {
      setIsRendered(true);
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          setIsVisible(true);
        });
      });
    } else {
      setIsVisible(false);
      timer = setTimeout(() => setIsRendered(false), 300);
    }
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(rafId);
    };
  }, [isOpen]);

  if (!isRendered) return null;

  const renderAppTab = () => (
    <div className="space-y-6">
      <Section title="Clipboard">
        <AppleSwitch 
          checked={appSettings.autoCopy} 
          onChange={(v) => setAppSettings(prev => ({ ...prev, autoCopy: v }))} 
          label="Automatically copy transcription to clipboard" 
        />
      </Section>
      <Section title="Notifications">
        <AppleSwitch 
          checked={appSettings.showNotifications} 
          onChange={(v) => setAppSettings(prev => ({ ...prev, showNotifications: v }))} 
          label="Show desktop notifications" 
        />
      </Section>
      <Section title="Docker Server">
        <AppleSwitch 
          checked={appSettings.stopServerOnQuit} 
          onChange={(v) => setAppSettings(prev => ({ ...prev, stopServerOnQuit: v }))} 
          label="Stop server when quitting dashboard" 
        />
      </Section>
    </div>
  );

  const renderClientTab = () => (
    <div className="space-y-6">
      <Section title="Audio">
        <div className="space-y-4">
            <div className="bg-white/5 p-3 rounded-lg border border-white/5 text-xs text-slate-400 font-mono">
                Sample Rate: <span className="text-accent-cyan">16000 Hz</span> (Fixed for Whisper)
            </div>
            <div>
                <label className="text-sm text-slate-300 font-medium block mb-2">Live Mode Grace Period (seconds)</label>
                <input 
                    type="number" 
                    step="0.1" 
                    value={clientSettings.gracePeriod} 
                    onChange={(e) => setClientSettings(prev => ({ ...prev, gracePeriod: parseFloat(e.target.value) }))}
                    className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-cyan/50" 
                />
                <p className="text-xs text-slate-500 mt-1">Buffer time before committing a segment.</p>
            </div>
        </div>
      </Section>

      <Section title="Diarization">
        <AppleSwitch 
            checked={clientSettings.constrainSpeakers} 
            onChange={(v) => setClientSettings(prev => ({ ...prev, constrainSpeakers: v }))}
            label="Constrain to expected number of speakers"
        />
        <div className={`mt-3 transition-opacity duration-200 ${clientSettings.constrainSpeakers ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
            <label className="text-sm text-slate-300 font-medium block mb-2">Number of Speakers</label>
            <input 
                type="number" 
                min="1" 
                max="10"
                value={clientSettings.numSpeakers}
                onChange={(e) => setClientSettings(prev => ({ ...prev, numSpeakers: parseInt(e.target.value) }))}
                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-cyan/50" 
            />
        </div>
      </Section>

      <Section title="Audio Notebook">
        <AppleSwitch 
            checked={clientSettings.autoAddNotebook}
            onChange={(v) => setClientSettings(prev => ({ ...prev, autoAddNotebook: v }))}
            label="Auto-add recordings to Audio Notebook"
        />
      </Section>

      <Section title="Connection">
         <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1.5">Local Host</label>
                    <input 
                        type="text" 
                        value={clientSettings.localHost}
                        onChange={(e) => setClientSettings(prev => ({ ...prev, localHost: e.target.value }))}
                        className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-cyan/50"
                    />
                </div>
                 <div className={!clientSettings.useRemote ? 'opacity-50' : ''}>
                    <label className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1.5">Remote Host</label>
                    <input 
                        type="text" 
                        placeholder="e.g. my-server.tail123.ts.net"
                        value={clientSettings.remoteHost}
                        onChange={(e) => setClientSettings(prev => ({ ...prev, remoteHost: e.target.value }))}
                        disabled={!clientSettings.useRemote}
                        className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-cyan/50"
                    />
                </div>
            </div>
            
            <AppleSwitch 
                checked={clientSettings.useRemote}
                onChange={(v) => setClientSettings(prev => ({ ...prev, useRemote: v }))}
                label="Use remote server instead of local"
            />

            <div className="h-px bg-white/5 my-2"></div>

            <div>
                <label className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1.5">Auth Token</label>
                <div className="relative">
                    <input 
                        type={showAuthToken ? "text" : "password"} 
                        value={clientSettings.authToken}
                        onChange={(e) => setClientSettings(prev => ({ ...prev, authToken: e.target.value }))}
                        className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-accent-cyan/50 pr-10"
                    />
                    <button 
                        onClick={() => setShowAuthToken(!showAuthToken)}
                        className="absolute right-2 top-2 p-1 text-slate-500 hover:text-white transition-colors"
                    >
                        {showAuthToken ? <EyeOff size={14}/> : <Eye size={14}/>}
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4 items-end">
                <div>
                    <label className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1.5">Port</label>
                    <input 
                        type="number" 
                        value={clientSettings.port}
                        onChange={(e) => setClientSettings(prev => ({ ...prev, port: parseInt(e.target.value) }))}
                        className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent-cyan/50"
                    />
                </div>
                 <div className="pb-1">
                     <AppleSwitch 
                        checked={clientSettings.useHttps}
                        onChange={(v) => setClientSettings(prev => ({ ...prev, useHttps: v }))}
                        label="Use HTTPS"
                    />
                 </div>
            </div>
         </div>
      </Section>
    </div>
  );

  const renderServerTab = () => (
    <div className="space-y-6">
       <div className="bg-white/5 rounded-xl p-4 border border-white/10">
            <p className="text-sm text-slate-400 mb-4">
                Server settings are stored in <span className="font-mono text-accent-cyan bg-accent-cyan/10 px-1 rounded">config.yaml</span>. 
                Changes here will require a restart.
            </p>
            <div className="relative">
                <Search className="absolute left-3 top-2.5 text-slate-500" size={16} />
                <input 
                    type="text" 
                    placeholder="Search server settings..."
                    value={serverSearch}
                    onChange={(e) => setServerSearch(e.target.value)}
                    className="w-full bg-black/30 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-accent-magenta transition-all"
                />
            </div>
       </div>

       <div className="space-y-4">
            {serverConfig.map((section) => (
                <CollapsibleSection key={section.category} title={section.category} description={section.description}>
                    <div className="space-y-3 pt-2">
                        {section.settings.filter(s => s.key.toLowerCase().includes(serverSearch.toLowerCase())).map((setting) => (
                            <div key={setting.key} className="flex items-center justify-between group py-1">
                                <div>
                                    <div className="text-sm font-medium text-slate-300 group-hover:text-white transition-colors">{setting.key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</div>
                                    <div className="text-xs text-slate-500">{setting.description}</div>
                                </div>
                                <div className="w-32">
                                    <input 
                                        type="text" 
                                        defaultValue={setting.value}
                                        className="w-full bg-black/20 border border-white/10 rounded px-2 py-1 text-xs text-white font-mono text-right focus:outline-none focus:border-accent-magenta/50 focus:bg-white/5 transition-all"
                                    />
                                </div>
                            </div>
                        ))}
                        {section.settings.filter(s => s.key.toLowerCase().includes(serverSearch.toLowerCase())).length === 0 && (
                            <div className="text-center py-2 text-xs text-slate-600 italic">No matches in this section</div>
                        )}
                    </div>
                </CollapsibleSection>
            ))}
       </div>

       <Section title="Config File">
            <div className="flex items-center justify-between">
                <div>
                    <label className="text-xs text-slate-500 font-medium uppercase tracking-wider block mb-1">File Location</label>
                    <div className="font-mono text-xs text-slate-300 bg-black/30 px-2 py-1 rounded border border-white/5 select-all">
                        /etc/transcription-suite/config.yaml
                    </div>
                </div>
                <Button variant="secondary" size="sm" icon={<FileText size={14}/>}>Open in Editor</Button>
            </div>
       </Section>
    </div>
  );

  const renderNotebookTab = () => (
    <div className="space-y-6">
        <Section title="Database Backup">
            <p className="text-xs text-slate-400 mb-4">Manage local SQLite database backups.</p>
            <div className="bg-black/30 border border-white/10 rounded-lg overflow-hidden mb-4">
                 {[
                     { name: 'backup_2026-01-14.db', date: 'Jan 14, 2026 18:00', size: '4.2 MB' },
                     { name: 'backup_2026-01-13.db', date: 'Jan 13, 2026 09:30', size: '4.1 MB' },
                     { name: 'backup_auto_weekly.db', date: 'Jan 10, 2026 00:00', size: '3.9 MB' },
                 ].map((backup, i) => (
                     <div key={i} className="flex items-center justify-between px-4 py-3 border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors cursor-pointer group">
                        <div className="flex items-center gap-3">
                            <Database size={16} className="text-slate-500 group-hover:text-accent-cyan" />
                            <div>
                                <div className="text-sm text-slate-300 font-medium">{backup.name}</div>
                                <div className="text-xs text-slate-500">{backup.date}</div>
                            </div>
                        </div>
                        <span className="text-xs font-mono text-slate-500">{backup.size}</span>
                     </div>
                 ))}
            </div>
            <div className="flex gap-3">
                <Button variant="primary" size="sm" icon={<Save size={14}/>}>Create Backup</Button>
                <Button variant="secondary" size="sm" icon={<RefreshCw size={14}/>}>Refresh</Button>
            </div>
        </Section>

        <Section title="Database Restore">
            <div className="flex items-start gap-3 p-4 bg-orange-500/10 border border-orange-500/20 rounded-lg mb-4">
                <AlertTriangle size={20} className="text-orange-500 shrink-0" />
                <div className="text-xs text-orange-200">
                    <strong className="block mb-1 font-bold text-orange-400">Warning: Irreversible Action</strong>
                    Restoring a backup will overwrite the current database. All changes made since the backup will be lost. The application will restart automatically.
                </div>
            </div>
            <Button variant="danger" className="w-full">Restore Selected Backup</Button>
        </Section>
    </div>
  );

  const getIconForTab = (tab: string) => {
      switch(tab) {
          case 'App': return <AppWindow size={16} />;
          case 'Client': return <Laptop size={16} />;
          case 'Server': return <Server size={16} />;
          case 'Notebook': return <Database size={16} />;
          default: return null;
      }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div 
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />
      
      {/* Modal Window */}
      <div 
        className={`
            relative w-full max-w-3xl bg-glass-surface backdrop-blur-xl border border-glass-border rounded-2xl shadow-2xl overflow-hidden flex flex-col 
            h-[85vh] 
            transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]
            ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-full opacity-0'}
        `}
      >
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-white/5 flex-none select-none">
            <h2 className="text-lg font-semibold text-white">Settings</h2>
            <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
                <X size={20} />
            </button>
        </div>

        {/* Tabs */}
        <div className="flex px-6 pt-4 space-x-1 border-b border-white/5 overflow-x-auto flex-none select-none">
            {tabs.map(tab => (
                <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                        activeTab === tab 
                        ? 'border-accent-cyan text-white' 
                        : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-white/5 rounded-t-lg'
                    }`}
                >
                    {getIconForTab(tab)}
                    {tab}
                </button>
            ))}
        </div>

        {/* Content Area - Entire area is selectable as requested */}
        <div className="p-6 overflow-y-auto custom-scrollbar flex-1 bg-black/20 selectable-text">
            <div 
                key={activeTab} 
                className="animate-in fade-in slide-in-from-right-8 duration-300 fill-mode-forwards"
            >
                {activeTab === 'App' && renderAppTab()}
                {activeTab === 'Client' && renderClientTab()}
                {activeTab === 'Server' && renderServerTab()}
                {activeTab === 'Notebook' && renderNotebookTab()}
            </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 bg-white/5 flex justify-end gap-3 flex-none select-none">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary">Save Changes</Button>
        </div>

      </div>
    </div>
  );
};

// Sub-components
const Section: React.FC<{title: string; children: React.ReactNode}> = ({title, children}) => (
    <div className="bg-white/5 rounded-xl p-5 border border-white/10 shadow-sm">
        <h3 className="text-xs font-bold text-slate-400 mb-4 uppercase tracking-wider flex items-center gap-2 select-none">
            {title}
            <div className="h-px bg-white/10 flex-1"></div>
        </h3>
        <div className="space-y-4">
            {children}
        </div>
    </div>
);

const CollapsibleSection: React.FC<{title: string; description?: string; children: React.ReactNode}> = ({ title, description, children }) => {
    const [isOpen, setIsOpen] = useState(false);
    return (
        <div className="bg-white/5 rounded-xl border border-white/10 overflow-hidden transition-all duration-200">
            <button 
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-white/5 transition-colors select-none"
            >
                <div>
                    <h3 className={`text-sm font-semibold transition-colors ${isOpen ? 'text-accent-magenta' : 'text-slate-200'}`}>{title}</h3>
                    {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
                </div>
                <div className={`p-1 rounded-full text-slate-400 transition-transform duration-200 ${isOpen ? 'rotate-180 bg-white/10 text-white' : ''}`}>
                    <ChevronDown size={16} />
                </div>
            </button>
            <div className={`transition-all duration-300 ease-in-out overflow-hidden ${isOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}>
                <div className="p-4 pt-0 border-t border-white/5">
                    {children}
                </div>
            </div>
        </div>
    );
};
