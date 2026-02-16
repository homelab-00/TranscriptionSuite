import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Search,
  ChevronDown,
  FileText,
  RefreshCw,
  AlertTriangle,
  Save,
  Database,
  Server,
  Laptop,
  AppWindow,
  Eye,
  EyeOff,
  Loader2,
  RotateCw,
  Plus,
  Trash2,
  Shield,
  Copy,
  Check,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { AppleSwitch } from '../ui/AppleSwitch';
import { CustomSelect } from '../ui/CustomSelect';
import { useBackups } from '../../src/hooks/useBackups';
import { apiClient } from '../../src/api/client';
import { useAdminStatus } from '../../src/hooks/useAdminStatus';
import type { AuthToken } from '../../src/api/types';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const tabs = ['App', 'Client', 'Server', 'Notebook'];

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState('App');
  const [serverSearch, setServerSearch] = useState('');
  const [showAuthToken, setShowAuthToken] = useState(false);
  const [tokenCopied, setTokenCopied] = useState(false);
  const [showHfToken, setShowHfToken] = useState(false);

  // Animation State
  const [isRendered, setIsRendered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  // Backups hook for Notebook tab
  const {
    backups,
    loading: backupsLoading,
    refresh: refreshBackups,
    createBackup,
    restoreBackup,
    operating,
    operationResult,
  } = useBackups();
  const [selectedBackup, setSelectedBackup] = useState<string | null>(null);

  // Admin status for Server tab (read-only config display)
  const { status: adminStatus, loading: adminLoading } = useAdminStatus(
    10000,
    isOpen && activeTab === 'Server',
  );

  // Edited server config values (key → value; only populated when user edits)
  const [serverConfigEdits, setServerConfigEdits] = useState<Record<string, string>>({});
  const [configDir, setConfigDir] = useState<string>('~/.config/TranscriptionSuite');

  // Token management state
  const [tokens, setTokens] = useState<AuthToken[]>([]);
  const [tokensLoading, setTokensLoading] = useState(false);
  const [showTokenPanel, setShowTokenPanel] = useState(false);
  const [newTokenName, setNewTokenName] = useState('');
  const [newTokenAdmin, setNewTokenAdmin] = useState(false);
  const [createdTokenPlaintext, setCreatedTokenPlaintext] = useState<string | null>(null);
  const [copiedTokenId, setCopiedTokenId] = useState<string | null>(null);

  // Derive server config sections from admin status
  const serverConfig = React.useMemo(() => {
    if (!adminStatus?.config) return [];
    const cfg = adminStatus.config as Record<string, unknown>;
    const sections: Array<{
      category: string;
      description: string;
      settings: Array<{ key: string; value: string; type: string; description: string }>;
    }> = [];

    const flatten = (
      obj: Record<string, unknown>,
      prefix = '',
    ): Array<{ key: string; value: string }> => {
      const entries: Array<{ key: string; value: string }> = [];
      for (const [k, v] of Object.entries(obj)) {
        const fullKey = prefix ? `${prefix}.${k}` : k;
        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
          entries.push(...flatten(v as Record<string, unknown>, fullKey));
        } else {
          entries.push({ key: fullKey, value: String(v ?? '') });
        }
      }
      return entries;
    };

    // Group by top-level key
    for (const [topKey, topVal] of Object.entries(cfg)) {
      if (topVal !== null && typeof topVal === 'object' && !Array.isArray(topVal)) {
        const settings = flatten(topVal as Record<string, unknown>).map((s) => ({
          ...s,
          type: typeof s.value === 'number' ? 'number' : 'string',
          description: '',
        }));
        if (settings.length > 0) {
          sections.push({
            category: topKey.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
            description: `${topKey} configuration`,
            settings,
          });
        }
      }
    }
    return sections;
  }, [adminStatus]);

  // Settings state
  const [appSettings, setAppSettings] = useState({
    autoCopy: false,
    showNotifications: true,
    stopServerOnQuit: true,
    startMinimized: false,
    updateChecksEnabled: false,
    updateCheckIntervalMode: '24h',
    updateCheckCustomHours: 24,
    runtimeProfile: 'gpu' as 'gpu' | 'cpu',
  });

  // Update check status (loaded from main process)
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [isCheckingUpdates, setIsCheckingUpdates] = useState(false);

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
    hfToken: '',
  });

  // Animation Lifecycle + Load Settings from Config Store
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let rafId: number;
    if (isOpen) {
      setIsRendered(true);
      setIsDirty(false);
      // Load settings from config store
      const api = (window as any).electronAPI;
      if (api?.config) {
        // Load config directory path
        api.app
          ?.getConfigDir?.()
          .then((dir: string) => {
            if (dir) setConfigDir(dir);
          })
          .catch(() => {});
        // Reset server config edits on open
        setServerConfigEdits({});
        api.config
          .getAll()
          .then((cfg: Record<string, unknown>) => {
            if (cfg) {
              setClientSettings((prev) => ({
                ...prev,
                localHost: (cfg['connection.localHost'] as string) ?? prev.localHost,
                remoteHost: (cfg['connection.remoteHost'] as string) ?? prev.remoteHost,
                useRemote: (cfg['connection.useRemote'] as boolean) ?? prev.useRemote,
                authToken: (cfg['connection.authToken'] as string) ?? prev.authToken,
                port: (cfg['connection.port'] as number) ?? prev.port,
                useHttps: (cfg['connection.useHttps'] as boolean) ?? prev.useHttps,
                gracePeriod: (cfg['audio.gracePeriod'] as number) ?? prev.gracePeriod,
                constrainSpeakers:
                  (cfg['diarization.constrainSpeakers'] as boolean) ?? prev.constrainSpeakers,
                numSpeakers: (cfg['diarization.numSpeakers'] as number) ?? prev.numSpeakers,
                autoAddNotebook: (cfg['notebook.autoAdd'] as boolean) ?? prev.autoAddNotebook,
                hfToken: (cfg['server.hfToken'] as string) ?? prev.hfToken,
              }));
              setAppSettings((prev) => ({
                ...prev,
                autoCopy: (cfg['app.autoCopy'] as boolean) ?? prev.autoCopy,
                showNotifications:
                  (cfg['app.showNotifications'] as boolean) ?? prev.showNotifications,
                stopServerOnQuit: (cfg['app.stopServerOnQuit'] as boolean) ?? prev.stopServerOnQuit,
                startMinimized: (cfg['app.startMinimized'] as boolean) ?? prev.startMinimized,
                updateChecksEnabled:
                  (cfg['app.updateChecksEnabled'] as boolean) ?? prev.updateChecksEnabled,
                updateCheckIntervalMode:
                  (cfg['app.updateCheckIntervalMode'] as string) ?? prev.updateCheckIntervalMode,
                updateCheckCustomHours:
                  (cfg['app.updateCheckCustomHours'] as number) ?? prev.updateCheckCustomHours,
                runtimeProfile:
                  (cfg['server.runtimeProfile'] as 'gpu' | 'cpu') ?? prev.runtimeProfile,
              }));
            }
          })
          .catch(() => {});
        // Load persisted update status
        api.updates
          ?.getStatus?.()
          .then((status: UpdateStatus | null) => {
            if (status) setUpdateStatus(status);
          })
          .catch(() => {});
      }
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

  const handleSave = useCallback(async () => {
    const api = (window as any).electronAPI;
    if (api?.config) {
      const entries: [string, unknown][] = [
        ['connection.localHost', clientSettings.localHost],
        ['connection.remoteHost', clientSettings.remoteHost],
        ['connection.useRemote', clientSettings.useRemote],
        ['connection.authToken', clientSettings.authToken],
        ['connection.port', clientSettings.port],
        ['connection.useHttps', clientSettings.useHttps],
        ['audio.gracePeriod', clientSettings.gracePeriod],
        ['diarization.constrainSpeakers', clientSettings.constrainSpeakers],
        ['diarization.numSpeakers', clientSettings.numSpeakers],
        ['notebook.autoAdd', clientSettings.autoAddNotebook],
        ['server.hfToken', clientSettings.hfToken],
        ['app.autoCopy', appSettings.autoCopy],
        ['app.showNotifications', appSettings.showNotifications],
        ['app.stopServerOnQuit', appSettings.stopServerOnQuit],
        ['app.startMinimized', appSettings.startMinimized],
        ['app.updateChecksEnabled', appSettings.updateChecksEnabled],
        ['app.updateCheckIntervalMode', appSettings.updateCheckIntervalMode],
        ['app.updateCheckCustomHours', appSettings.updateCheckCustomHours],
        ['server.runtimeProfile', appSettings.runtimeProfile],
      ];
      await Promise.all(entries.map(([k, v]) => api.config.set(k, v)));
    }

    // Sync API client with new config so connection target updates immediately
    await apiClient.syncFromConfig();
    if (clientSettings.authToken) {
      apiClient.setAuthToken(clientSettings.authToken);
    }

    setIsDirty(false);
    onClose();
  }, [clientSettings, appSettings, onClose]);

  if (!isRendered) return null;

  const renderAppTab = () => (
    <div className="space-y-6">
      <Section title="Clipboard">
        <AppleSwitch
          checked={appSettings.autoCopy}
          onChange={(v) => {
            setAppSettings((prev) => ({ ...prev, autoCopy: v }));
            setIsDirty(true);
          }}
          label="Automatically copy transcription to clipboard"
        />
      </Section>
      <Section title="Notifications">
        <AppleSwitch
          checked={appSettings.showNotifications}
          onChange={(v) => {
            setAppSettings((prev) => ({ ...prev, showNotifications: v }));
            setIsDirty(true);
          }}
          label="Show desktop notifications"
        />
      </Section>
      <Section title="Docker Server">
        <AppleSwitch
          checked={appSettings.stopServerOnQuit}
          onChange={(v) => {
            setAppSettings((prev) => ({ ...prev, stopServerOnQuit: v }));
            setIsDirty(true);
          }}
          label="Stop server when quitting dashboard"
        />
      </Section>
      <Section title="Runtime Mode">
        <div className="space-y-3">
          <p className="text-xs text-slate-400">
            Choose the hardware acceleration profile for the transcription server. GPU mode requires
            an NVIDIA GPU with CUDA support. CPU mode works on all platforms but is significantly
            slower.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => {
                setAppSettings((prev) => ({ ...prev, runtimeProfile: 'gpu' }));
                setIsDirty(true);
              }}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium transition-all ${
                appSettings.runtimeProfile === 'gpu'
                  ? 'bg-accent-cyan/15 border-accent-cyan/40 text-accent-cyan'
                  : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10'
              }`}
            >
              GPU (CUDA)
            </button>
            <button
              onClick={() => {
                setAppSettings((prev) => ({ ...prev, runtimeProfile: 'cpu' }));
                setIsDirty(true);
              }}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg border px-4 py-3 text-sm font-medium transition-all ${
                appSettings.runtimeProfile === 'cpu'
                  ? 'bg-accent-orange/15 border-accent-orange/40 text-accent-orange'
                  : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10'
              }`}
            >
              CPU Only
            </button>
          </div>
          <p className="text-xs text-slate-500 italic">
            {appSettings.runtimeProfile === 'cpu'
              ? 'CPU mode: No GPU required. Works on macOS, Linux, and Windows. Expect slower transcription speeds.'
              : 'GPU mode: Requires NVIDIA GPU with CUDA. Recommended for Linux and Windows with supported hardware.'}
          </p>
        </div>
      </Section>
      <Section title="Window">
        <AppleSwitch
          checked={appSettings.startMinimized}
          onChange={(v) => {
            setAppSettings((prev) => ({ ...prev, startMinimized: v }));
            setIsDirty(true);
          }}
          label="Start minimized to system tray"
        />
      </Section>
      <Section title="Update Checks">
        <AppleSwitch
          checked={appSettings.updateChecksEnabled}
          onChange={(v) => {
            setAppSettings((prev) => ({ ...prev, updateChecksEnabled: v }));
            setIsDirty(true);
          }}
          label="Check for updates automatically"
        />
        {appSettings.updateChecksEnabled && (
          <div className="mt-4 space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                Check Interval
              </label>
              <CustomSelect
                value={appSettings.updateCheckIntervalMode}
                onChange={(v) => {
                  setAppSettings((prev) => ({ ...prev, updateCheckIntervalMode: v }));
                  setIsDirty(true);
                }}
                options={['24h', '7d', '28d', 'custom']}
              />
            </div>
            {appSettings.updateCheckIntervalMode === 'custom' && (
              <div>
                <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                  Custom Interval (hours)
                </label>
                <input
                  type="number"
                  min="1"
                  value={appSettings.updateCheckCustomHours}
                  onChange={(e) => {
                    setAppSettings((prev) => ({
                      ...prev,
                      updateCheckCustomHours: Math.max(1, parseInt(e.target.value) || 1),
                    }));
                    setIsDirty(true);
                  }}
                  className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
            )}
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                icon={
                  isCheckingUpdates ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <RotateCw size={14} />
                  )
                }
                disabled={isCheckingUpdates}
                onClick={async () => {
                  const api = window.electronAPI;
                  if (!api?.updates) return;
                  setIsCheckingUpdates(true);
                  try {
                    const status = await api.updates.checkNow();
                    setUpdateStatus(status);
                  } catch {
                    /* ignore */
                  } finally {
                    setIsCheckingUpdates(false);
                  }
                }}
              >
                {isCheckingUpdates ? 'Checking…' : 'Check Now'}
              </Button>
            </div>
            {updateStatus && (
              <div className="space-y-2 rounded-lg border border-white/10 bg-black/30 p-3 text-xs">
                <div className="text-slate-500">
                  Last checked: {new Date(updateStatus.lastChecked).toLocaleString()}
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-16 shrink-0 text-slate-400">Dashboard:</span>
                  {updateStatus.app.error ? (
                    <span className="text-red-400">Error: {updateStatus.app.error}</span>
                  ) : updateStatus.app.updateAvailable ? (
                    <span className="text-accent-cyan">
                      {updateStatus.app.current} → {updateStatus.app.latest}{' '}
                      <span className="ml-1 text-green-400">update available</span>
                    </span>
                  ) : (
                    <span className="text-slate-300">{updateStatus.app.current} — up to date</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-16 shrink-0 text-slate-400">Server:</span>
                  {updateStatus.server.error ? (
                    <span className="text-red-400">Error: {updateStatus.server.error}</span>
                  ) : !updateStatus.server.current ? (
                    <span className="text-slate-500">No local image found</span>
                  ) : updateStatus.server.updateAvailable ? (
                    <span className="text-accent-cyan">
                      {updateStatus.server.current} → {updateStatus.server.latest}{' '}
                      <span className="ml-1 text-green-400">update available</span>
                    </span>
                  ) : (
                    <span className="text-slate-300">
                      {updateStatus.server.current} — up to date
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Section>
    </div>
  );

  const renderClientTab = () => (
    <div className="space-y-6">
      <Section title="Audio">
        <div className="space-y-4">
          <div className="rounded-lg border border-white/5 bg-white/5 p-3 font-mono text-xs text-slate-400">
            Sample Rate: <span className="text-accent-cyan">16000 Hz</span> (Fixed for Whisper)
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-300">
              Live Mode Grace Period (seconds)
            </label>
            <input
              type="number"
              step="0.1"
              value={clientSettings.gracePeriod}
              onChange={(e) =>
                setClientSettings((prev) => ({ ...prev, gracePeriod: parseFloat(e.target.value) }))
              }
              className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
            />
            <p className="mt-1 text-xs text-slate-500">Buffer time before committing a segment.</p>
          </div>
        </div>
      </Section>

      <Section title="Diarization">
        <AppleSwitch
          checked={clientSettings.constrainSpeakers}
          onChange={(v) => setClientSettings((prev) => ({ ...prev, constrainSpeakers: v }))}
          label="Constrain to expected number of speakers"
        />
        <div
          className={`mt-3 transition-opacity duration-200 ${clientSettings.constrainSpeakers ? 'opacity-100' : 'pointer-events-none opacity-50'}`}
        >
          <label className="mb-2 block text-sm font-medium text-slate-300">
            Number of Speakers
          </label>
          <input
            type="number"
            min="1"
            max="10"
            value={clientSettings.numSpeakers}
            onChange={(e) =>
              setClientSettings((prev) => ({ ...prev, numSpeakers: parseInt(e.target.value) }))
            }
            className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
          />
        </div>
      </Section>

      <Section title="HuggingFace Token">
        <p className="mb-3 text-xs text-slate-400">
          Required for speaker diarization. Accept the{' '}
          <a
            href="https://huggingface.co/pyannote/speaker-diarization-3.1"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-cyan hover:underline"
          >
            PyAnnote model terms
          </a>{' '}
          on HuggingFace, then paste your token here.
        </p>
        <div className="relative">
          <input
            type={showHfToken ? 'text' : 'password'}
            value={clientSettings.hfToken}
            onChange={(e) => setClientSettings((prev) => ({ ...prev, hfToken: e.target.value }))}
            placeholder="hf_xxxxxxxxxxxxxxxxxxxx"
            className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-10 font-mono text-sm text-white focus:outline-none"
          />
          <button
            type="button"
            onClick={() => setShowHfToken(!showHfToken)}
            className="absolute top-1/2 right-2 -translate-y-1/2 text-slate-400 transition-colors hover:text-white"
          >
            {showHfToken ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
        {clientSettings.hfToken && (
          <p className="mt-1.5 text-xs text-green-400/70">
            Token will be passed to the container on next start.
          </p>
        )}
      </Section>

      <Section title="Audio Notebook">
        <AppleSwitch
          checked={clientSettings.autoAddNotebook}
          onChange={(v) => setClientSettings((prev) => ({ ...prev, autoAddNotebook: v }))}
          label="Auto-add recordings to Audio Notebook"
        />
      </Section>

      <Section title="Connection">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                Local Host
              </label>
              <input
                type="text"
                value={clientSettings.localHost}
                onChange={(e) =>
                  setClientSettings((prev) => ({ ...prev, localHost: e.target.value }))
                }
                className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
              />
            </div>
            <div className={!clientSettings.useRemote ? 'opacity-50' : ''}>
              <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                Remote Host
              </label>
              <input
                type="text"
                placeholder="e.g. my-server.tail123.ts.net"
                value={clientSettings.remoteHost}
                onChange={(e) =>
                  setClientSettings((prev) => ({ ...prev, remoteHost: e.target.value }))
                }
                disabled={!clientSettings.useRemote}
                className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
              />
            </div>
          </div>

          <AppleSwitch
            checked={clientSettings.useRemote}
            onChange={(v) => setClientSettings((prev) => ({ ...prev, useRemote: v }))}
            label="Use remote server instead of local"
          />

          <div className="my-2 h-px bg-white/5"></div>

          <div>
            <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
              Auth Token
            </label>
            <div className="relative">
              <input
                type={showAuthToken ? 'text' : 'password'}
                value={clientSettings.authToken}
                onChange={(e) =>
                  setClientSettings((prev) => ({ ...prev, authToken: e.target.value }))
                }
                className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-20 font-mono text-sm text-white focus:outline-none"
              />
              <div className="absolute top-2 right-2 flex items-center gap-1">
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(clientSettings.authToken);
                    setTokenCopied(true);
                    setTimeout(() => setTokenCopied(false), 2000);
                  }}
                  className="p-1 text-slate-500 transition-colors hover:text-white"
                  title="Copy token"
                >
                  {tokenCopied ? (
                    <Check size={14} className="text-green-400" />
                  ) : (
                    <Copy size={14} />
                  )}
                </button>
                <button
                  onClick={() => setShowAuthToken(!showAuthToken)}
                  className="p-1 text-slate-500 transition-colors hover:text-white"
                >
                  {showAuthToken ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          </div>

          {/* Token Management Panel */}
          <div className="mt-2">
            <button
              onClick={async () => {
                setShowTokenPanel(!showTokenPanel);
                if (!showTokenPanel && tokens.length === 0) {
                  setTokensLoading(true);
                  try {
                    const res = await apiClient.listTokens();
                    setTokens(res.tokens || []);
                  } catch {
                    /* server may not have TLS enabled */
                  }
                  setTokensLoading(false);
                }
              }}
              className="flex items-center gap-2 text-xs text-slate-400 transition-colors hover:text-white"
            >
              <Shield size={12} />
              <span>Manage Tokens</span>
              <ChevronDown
                size={12}
                className={`transition-transform ${showTokenPanel ? 'rotate-180' : ''}`}
              />
            </button>

            {showTokenPanel && (
              <div className="mt-3 space-y-3 rounded-lg border border-white/10 bg-white/5 p-3">
                {tokensLoading ? (
                  <div className="flex items-center gap-2 text-sm text-slate-400">
                    <Loader2 size={14} className="animate-spin" /> Loading tokens...
                  </div>
                ) : (
                  <>
                    {/* Existing tokens list */}
                    {tokens.length > 0 ? (
                      <div className="max-h-40 space-y-2 overflow-y-auto">
                        {tokens
                          .filter((t) => !t.is_revoked)
                          .map((t) => (
                            <div
                              key={t.token_id}
                              className="flex items-center gap-2 rounded bg-black/20 px-2 py-1.5 text-xs"
                            >
                              <span
                                className={`h-2 w-2 rounded-full ${t.is_admin ? 'bg-amber-400' : 'bg-accent-cyan'}`}
                              />
                              <span className="flex-1 truncate text-white">{t.client_name}</span>
                              <span className="font-mono text-slate-500">
                                {t.token_id.slice(0, 8)}…
                              </span>
                              {t.is_admin && (
                                <span className="text-[9px] font-bold text-amber-400 uppercase">
                                  Admin
                                </span>
                              )}
                              {t.expires_at && (
                                <span className="text-[10px] text-slate-500">
                                  {t.is_expired
                                    ? 'Expired'
                                    : `Expires ${new Date(t.expires_at).toLocaleDateString()}`}
                                </span>
                              )}
                              <button
                                onClick={async () => {
                                  if (!confirm(`Revoke token for "${t.client_name}"?`)) return;
                                  try {
                                    await apiClient.revokeToken(t.token_id);
                                    setTokens((prev) =>
                                      prev.filter((tk) => tk.token_id !== t.token_id),
                                    );
                                  } catch {
                                    alert('Failed to revoke token.');
                                  }
                                }}
                                className="p-0.5 text-slate-500 transition-colors hover:text-red-400"
                                title="Revoke"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">
                        No active tokens. Enable TLS on the server to manage tokens.
                      </p>
                    )}

                    {/* Created token display (shown once after creation) */}
                    {createdTokenPlaintext && (
                      <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-3">
                        <p className="mb-1 text-xs font-semibold text-green-400">
                          New Token Created — Copy Now!
                        </p>
                        <div className="flex items-center gap-2">
                          <code className="flex-1 rounded bg-black/30 px-2 py-1 font-mono text-xs break-all text-white select-all">
                            {createdTokenPlaintext}
                          </code>
                          <button
                            onClick={() => {
                              navigator.clipboard.writeText(createdTokenPlaintext);
                              setCopiedTokenId('new');
                              setTimeout(() => setCopiedTokenId(null), 2000);
                            }}
                            className="p-1 text-green-400 transition-colors hover:text-white"
                          >
                            {copiedTokenId === 'new' ? <Check size={14} /> : <Copy size={14} />}
                          </button>
                        </div>
                        <p className="mt-1 text-[10px] text-slate-500">
                          This token will not be shown again.
                        </p>
                      </div>
                    )}

                    {/* Create new token */}
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        placeholder="Client name..."
                        value={newTokenName}
                        onChange={(e) => setNewTokenName(e.target.value)}
                        className="focus:border-accent-cyan/50 flex-1 rounded border border-white/10 bg-black/20 px-2 py-1 text-xs text-white placeholder-slate-600 focus:outline-none"
                      />
                      <label className="flex items-center gap-1 text-[10px] whitespace-nowrap text-slate-400">
                        <input
                          type="checkbox"
                          checked={newTokenAdmin}
                          onChange={(e) => setNewTokenAdmin(e.target.checked)}
                          className="rounded"
                        />
                        Admin
                      </label>
                      <button
                        onClick={async () => {
                          if (!newTokenName.trim()) return;
                          try {
                            const res = await apiClient.createToken({
                              client_name: newTokenName.trim(),
                              is_admin: newTokenAdmin,
                            });
                            if (res.token) {
                              setCreatedTokenPlaintext(res.token.token);
                              setNewTokenName('');
                              setNewTokenAdmin(false);
                              // Refresh list
                              const list = await apiClient.listTokens();
                              setTokens(list.tokens || []);
                            }
                          } catch {
                            alert('Failed to create token.');
                          }
                        }}
                        disabled={!newTokenName.trim()}
                        className="text-accent-cyan p-1 transition-colors hover:text-white disabled:text-slate-600"
                        title="Create token"
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 items-end gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                Port
              </label>
              <input
                type="number"
                value={clientSettings.port}
                onChange={(e) =>
                  setClientSettings((prev) => ({ ...prev, port: parseInt(e.target.value) }))
                }
                className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
              />
            </div>
            <div className="pb-1">
              <AppleSwitch
                checked={clientSettings.useHttps}
                onChange={(v) => setClientSettings((prev) => ({ ...prev, useHttps: v }))}
                label="Use HTTPS"
              />
            </div>
          </div>
        </div>
      </Section>
    </div>
  );

  const renderServerTab = () => {
    const handleOpenConfigInEditor = async () => {
      const api = (window as any).electronAPI;
      if (api?.app?.openPath) {
        const configPath = `${configDir}/config.yaml`;
        const error = await api.app.openPath(configPath);
        if (error) {
          // Fallback: try opening the directory
          await api.app.openPath(configDir).catch(() => {});
        }
      }
    };

    const handleServerConfigEdit = (
      sectionCategory: string,
      settingKey: string,
      newValue: string,
    ) => {
      const fullKey = `${sectionCategory}.${settingKey}`;
      setServerConfigEdits((prev) => ({ ...prev, [fullKey]: newValue }));
      setIsDirty(true);
    };

    const getServerConfigValue = (
      sectionCategory: string,
      settingKey: string,
      originalValue: string,
    ): string => {
      const fullKey = `${sectionCategory}.${settingKey}`;
      return fullKey in serverConfigEdits ? serverConfigEdits[fullKey] : originalValue;
    };

    return (
      <div className="space-y-6">
        <div className="rounded-xl border border-white/10 bg-white/5 p-4">
          <p className="mb-4 text-sm text-slate-400">
            Server settings are stored in{' '}
            <span className="text-accent-cyan bg-accent-cyan/10 rounded px-1 font-mono">
              config.yaml
            </span>
            . Changes here are for reference — edit the config file directly for persistent changes.
          </p>
          <div className="relative">
            <Search className="absolute top-2.5 left-3 text-slate-500" size={16} />
            <input
              type="text"
              placeholder="Search server settings..."
              value={serverSearch}
              onChange={(e) => setServerSearch(e.target.value)}
              className="focus:ring-accent-magenta w-full rounded-lg border border-white/10 bg-black/30 py-2 pr-4 pl-10 text-sm text-white transition-all focus:ring-1 focus:outline-none"
            />
          </div>
        </div>

        <div className="space-y-4">
          {adminLoading ? (
            <div className="flex items-center justify-center py-8 text-slate-500">
              <Loader2 size={16} className="mr-2 animate-spin" /> Loading server configuration…
            </div>
          ) : serverConfig.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500">
              Could not retrieve server configuration. Is the server running?
            </div>
          ) : (
            serverConfig.map((section) => (
              <CollapsibleSection
                key={section.category}
                title={section.category}
                description={section.description}
              >
                <div className="space-y-3 pt-2">
                  {section.settings
                    .filter((s) => s.key.toLowerCase().includes(serverSearch.toLowerCase()))
                    .map((setting) => {
                      const currentVal = getServerConfigValue(
                        section.category,
                        setting.key,
                        setting.value,
                      );
                      const isBoolean = setting.value === 'true' || setting.value === 'false';
                      return (
                        <div
                          key={setting.key}
                          className="group flex items-center justify-between py-1"
                        >
                          <div>
                            <div className="text-sm font-medium text-slate-300 transition-colors group-hover:text-white">
                              {setting.key
                                .replace(/_/g, ' ')
                                .replace(/\b\w/g, (l) => l.toUpperCase())}
                            </div>
                            <div className="text-xs text-slate-500">{setting.description}</div>
                          </div>
                          <div className="w-32">
                            {isBoolean ? (
                              <AppleSwitch
                                checked={currentVal === 'true'}
                                onChange={(v) =>
                                  handleServerConfigEdit(section.category, setting.key, String(v))
                                }
                                label=""
                              />
                            ) : (
                              <input
                                type="text"
                                value={currentVal}
                                onChange={(e) =>
                                  handleServerConfigEdit(
                                    section.category,
                                    setting.key,
                                    e.target.value,
                                  )
                                }
                                className="focus:ring-accent-cyan/50 focus:border-accent-cyan/30 w-full rounded border border-white/10 bg-black/20 px-2 py-1 text-right font-mono text-xs text-white/80 transition-all hover:border-white/20 focus:ring-1 focus:outline-none"
                              />
                            )}
                          </div>
                        </div>
                      );
                    })}
                  {section.settings.filter((s) =>
                    s.key.toLowerCase().includes(serverSearch.toLowerCase()),
                  ).length === 0 && (
                    <div className="py-2 text-center text-xs text-slate-600 italic">
                      No matches in this section
                    </div>
                  )}
                </div>
              </CollapsibleSection>
            ))
          )}
        </div>

        <Section title="Config File">
          <div className="flex items-center justify-between">
            <div>
              <label className="mb-1 block text-xs font-medium tracking-wider text-slate-500 uppercase">
                File Location
              </label>
              <div className="rounded border border-white/5 bg-black/30 px-2 py-1 font-mono text-xs text-slate-300 select-all">
                {configDir}/config.yaml
              </div>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<FileText size={14} />}
              onClick={handleOpenConfigInEditor}
            >
              Open in Editor
            </Button>
          </div>
        </Section>
      </div>
    );
  };

  const renderNotebookTab = () => (
    <div className="space-y-6">
      <Section title="Database Backup">
        <p className="mb-4 text-xs text-slate-400">Manage local SQLite database backups.</p>
        <div className="mb-4 overflow-hidden rounded-lg border border-white/10 bg-black/30">
          {backupsLoading ? (
            <div className="flex items-center justify-center py-6 text-slate-500">
              <Loader2 size={16} className="mr-2 animate-spin" /> Loading backups…
            </div>
          ) : backups.length === 0 ? (
            <div className="py-6 text-center text-sm text-slate-500">No backups found</div>
          ) : (
            backups.map((backup, i) => (
              <div
                key={backup.filename}
                onClick={() => setSelectedBackup(backup.filename)}
                className={`group flex cursor-pointer items-center justify-between border-b border-white/5 px-4 py-3 transition-colors last:border-0 hover:bg-white/5 ${
                  selectedBackup === backup.filename
                    ? 'bg-accent-cyan/5 border-l-accent-cyan border-l-2'
                    : ''
                }`}
              >
                <div className="flex items-center gap-3">
                  <Database size={16} className="group-hover:text-accent-cyan text-slate-500" />
                  <div>
                    <div className="text-sm font-medium text-slate-300">{backup.filename}</div>
                    <div className="text-xs text-slate-500">
                      {new Date(backup.created_at).toLocaleString()}
                    </div>
                  </div>
                </div>
                <span className="font-mono text-xs text-slate-500">
                  {(backup.size / 1024 / 1024).toFixed(1)} MB
                </span>
              </div>
            ))
          )}
        </div>
        {operationResult && (
          <div
            className={`mb-3 rounded p-2 text-xs ${
              operationResult.includes('success') || operationResult.includes('Success')
                ? 'bg-green-500/10 text-green-400'
                : 'bg-red-500/10 text-red-400'
            }`}
          >
            {operationResult}
          </div>
        )}
        <div className="flex gap-3">
          <Button
            variant="primary"
            size="sm"
            icon={<Save size={14} />}
            onClick={createBackup}
            disabled={operating}
          >
            {operating ? 'Working…' : 'Create Backup'}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={refreshBackups}
          >
            Refresh
          </Button>
        </div>
      </Section>

      <Section title="Database Restore">
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-orange-500/20 bg-orange-500/10 p-4">
          <AlertTriangle size={20} className="shrink-0 text-orange-500" />
          <div className="text-xs text-orange-200">
            <strong className="mb-1 block font-bold text-orange-400">
              Warning: Irreversible Action
            </strong>
            Restoring a backup will overwrite the current database. All changes made since the
            backup will be lost. The application will restart automatically.
          </div>
        </div>
        <Button
          variant="danger"
          className="w-full"
          disabled={!selectedBackup || operating}
          onClick={() => selectedBackup && restoreBackup(selectedBackup)}
        >
          {selectedBackup ? `Restore: ${selectedBackup}` : 'Select a backup above'}
        </Button>
      </Section>
    </div>
  );

  const getIconForTab = (tab: string) => {
    switch (tab) {
      case 'App':
        return <AppWindow size={16} />;
      case 'Client':
        return <Laptop size={16} />;
      case 'Server':
        return <Server size={16} />;
      case 'Notebook':
        return <Database size={16} />;
      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out ${isVisible ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />

      {/* Modal Window */}
      <div
        className={`bg-glass-surface border-glass-border relative flex h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border shadow-2xl backdrop-blur-xl transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-full opacity-0'} `}
      >
        {/* Header */}
        <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button onClick={onClose} className="text-slate-400 transition-colors hover:text-white">
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex flex-none space-x-1 overflow-x-auto border-b border-white/5 px-6 pt-4 select-none">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors ${
                activeTab === tab
                  ? 'border-accent-cyan text-white'
                  : 'rounded-t-lg border-transparent text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`}
            >
              {getIconForTab(tab)}
              {tab}
            </button>
          ))}
        </div>

        {/* Content Area - Entire area is selectable as requested */}
        <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
          <div
            key={activeTab}
            className="animate-in fade-in slide-in-from-right-8 fill-mode-forwards duration-300"
          >
            {activeTab === 'App' && renderAppTab()}
            {activeTab === 'Client' && renderClientTab()}
            {activeTab === 'Server' && renderServerTab()}
            {activeTab === 'Notebook' && renderNotebookTab()}
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleSave}>
            Save Changes
          </Button>
        </div>
      </div>
    </div>
  );
};

// Sub-components
const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="rounded-xl border border-white/10 bg-white/5 p-5 shadow-sm">
    <h3 className="mb-4 flex items-center gap-2 text-xs font-bold tracking-wider text-slate-400 uppercase select-none">
      {title}
      <div className="h-px flex-1 bg-white/10"></div>
    </h3>
    <div className="space-y-4">{children}</div>
  </div>
);

const CollapsibleSection: React.FC<{
  title: string;
  description?: string;
  children: React.ReactNode;
}> = ({ title, description, children }) => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-white/5 transition-all duration-200">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between p-4 text-left transition-colors select-none hover:bg-white/5"
      >
        <div>
          <h3
            className={`text-sm font-semibold transition-colors ${isOpen ? 'text-accent-magenta' : 'text-slate-200'}`}
          >
            {title}
          </h3>
          {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
        </div>
        <div
          className={`rounded-full p-1 text-slate-400 transition-transform duration-200 ${isOpen ? 'rotate-180 bg-white/10 text-white' : ''}`}
        >
          <ChevronDown size={16} />
        </div>
      </button>
      <div
        className={`overflow-hidden transition-all duration-300 ease-in-out ${isOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="border-t border-white/5 p-4 pt-0">{children}</div>
      </div>
    </div>
  );
};
