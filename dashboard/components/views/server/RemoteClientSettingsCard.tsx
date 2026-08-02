import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Eye, EyeOff, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';

import { GlassCard } from '../../ui/GlassCard';
import { Button } from '../../ui/Button';
import { CustomSelect } from '../../ui/CustomSelect';
import { StatusLight } from '../../ui/StatusLight';
import { apiClient } from '../../../src/api/client';
import { writeToClipboard } from '../../../src/hooks/useClipboard';
import { useServerStatus } from '../../../src/hooks/useServerStatus';
import { getConfig, setConfig, DEFAULT_SERVER_PORT } from '../../../src/config/store';

interface RemoteClientSettingsCardProps {
  title: string;
}

const REMOTE_PROFILE_OPTIONS = ['Tailscale', 'LAN'] as const;

/**
 * Client-side remote connection settings, shown in place of the host-side
 * RemoteConnectionCard while the Remote runtime tile is selected. Holds the
 * fields that used to live in Settings > Client > Connection: remote profile
 * (Tailscale/LAN), host, auth token and port. HTTPS is not offered as a
 * choice — remote profiles force it so token auth stays on the wire encrypted
 * (same invariant SettingsModal enforced).
 *
 * Nothing is persisted until Apply: the handler validates, writes the
 * connection.* keys, then runs the same re-sync contract as
 * SettingsModal.handleSave / SessionView.handleStartClientRemote —
 * apiClient.syncFromConfig() + setAuthToken + query-cache sync — so the
 * running app switches target immediately, without a restart.
 */
export function RemoteClientSettingsCard({ title }: RemoteClientSettingsCardProps) {
  const queryClient = useQueryClient();
  const serverConnection = useServerStatus();

  const [remoteProfile, setRemoteProfile] = useState<'tailscale' | 'lan'>('tailscale');
  const [remoteHost, setRemoteHost] = useState('');
  const [lanHost, setLanHost] = useState('');
  const [authToken, setAuthToken] = useState('');
  const [port, setPort] = useState<number>(DEFAULT_SERVER_PORT);
  const [hydrated, setHydrated] = useState(false);
  const [applying, setApplying] = useState(false);
  const [showAuthToken, setShowAuthToken] = useState(false);
  const [authTokenCopied, setAuthTokenCopied] = useState(false);
  // True while the token field holds unapplied user typing — the query-cache
  // mirror below must not clobber it (e.g. the stale-token guard clearing the
  // cache mid-edit would otherwise wipe the token being entered).
  const tokenDirtyRef = useRef(false);

  // Load persisted connection settings once per mount.
  useEffect(() => {
    let active = true;
    Promise.all([
      getConfig<'tailscale' | 'lan'>('connection.remoteProfile'),
      getConfig<string>('connection.remoteHost'),
      getConfig<string>('connection.lanHost'),
      getConfig<string>('connection.authToken'),
      getConfig<number>('connection.port'),
    ])
      .then(([storedProfile, storedRemoteHost, storedLanHost, storedToken, storedPort]) => {
        if (!active) return;
        setRemoteProfile(storedProfile === 'lan' ? 'lan' : 'tailscale');
        if (typeof storedRemoteHost === 'string') setRemoteHost(storedRemoteHost);
        if (typeof storedLanHost === 'string') setLanHost(storedLanHost);
        if (typeof storedToken === 'string') setAuthToken(storedToken);
        if (typeof storedPort === 'number' && Number.isFinite(storedPort)) setPort(storedPort);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setHydrated(true);
      });
    return () => {
      active = false;
    };
  }, []);

  // Mirror SettingsModal: follow the centralized ['authToken'] query cache so
  // this field does not fight useAuthTokenSync (stale-token clears, manual
  // edits saved elsewhere). Unapplied user typing always wins over the cache.
  useEffect(() => {
    const syncToken = (token: string | undefined) => {
      if (tokenDirtyRef.current) return;
      const value = token ?? '';
      setAuthToken((prev) => (prev === value ? prev : value));
    };
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event?.query?.queryKey?.[0] !== 'authToken') return;
      const token = queryClient.getQueryData<string>(['authToken']);
      if (token !== undefined) syncToken(token);
    });
    const cached = queryClient.getQueryData<string>(['authToken']);
    if (cached) syncToken(cached);
    return unsubscribe;
  }, [queryClient]);

  const activeHost = remoteProfile === 'lan' ? lanHost : remoteHost;
  const trimmedHost = activeHost.trim();
  const looksLikeBareTailnet =
    remoteProfile === 'tailscale' && /^[^.]+\.ts\.net$/i.test(remoteHost.trim());

  const handleApply = useCallback(async () => {
    // Same validation SettingsModal.handleSave enforced for remote saves.
    if (remoteProfile === 'tailscale' && !remoteHost.trim()) {
      toast.error('Tailscale remote mode requires a host or IP address.');
      return;
    }
    if (remoteProfile === 'lan' && !lanHost.trim()) {
      toast.error('LAN remote mode requires a host or IP address.');
      return;
    }
    const normalizedPort = Number.isFinite(port) ? Math.trunc(port) : NaN;
    if (!Number.isInteger(normalizedPort) || normalizedPort < 1 || normalizedPort > 65535) {
      toast.error('Port must be a number between 1 and 65535.');
      return;
    }

    setApplying(true);
    try {
      const normalizedToken = authToken.trim();
      await Promise.all([
        setConfig('connection.remoteProfile', remoteProfile),
        setConfig('connection.remoteHost', remoteHost.trim()),
        setConfig('connection.lanHost', lanHost.trim()),
        setConfig('connection.authToken', normalizedToken),
        setConfig('connection.port', normalizedPort),
        setConfig('connection.useHttps', true),
        setConfig('connection.useRemote', true),
      ]);
      await apiClient.syncFromConfig();
      apiClient.setAuthToken(normalizedToken || null);
      queryClient.setQueryData(['authToken'], normalizedToken);
      tokenDirtyRef.current = false;
      await queryClient.invalidateQueries({ queryKey: ['adminStatus'] });
      serverConnection.refresh();
      toast.success('Remote connection settings applied.');
    } catch {
      toast.error('Could not save the remote connection settings.');
    } finally {
      setApplying(false);
    }
  }, [remoteProfile, remoteHost, lanHost, authToken, port, queryClient, serverConnection]);

  return (
    <GlassCard title={title}>
      <div className="space-y-4">
        {/* Connection status — polls whatever target is currently applied. */}
        <div className="flex items-center gap-3 border-b border-white/5 pb-3">
          <StatusLight
            status={serverConnection.serverStatus}
            animate={serverConnection.serverStatus === 'active'}
          />
          <span className="font-mono text-sm text-slate-300">{serverConnection.serverLabel}</span>
        </div>

        {!trimmedHost && hydrated && (
          <p className="text-xs text-amber-300/80">
            Enter the remote server&apos;s hostname and auth token, then press Apply. Both are shown
            on the host machine&apos;s Server tab.
          </p>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] md:items-end">
          <div>
            <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
              Remote Profile
            </label>
            <CustomSelect
              value={remoteProfile === 'lan' ? 'LAN' : 'Tailscale'}
              onChange={(value) => setRemoteProfile(value === 'LAN' ? 'lan' : 'tailscale')}
              options={[...REMOTE_PROFILE_OPTIONS]}
              className="h-10 rounded-lg border border-white/10 bg-black/20 px-3 text-sm text-white"
            />
          </div>
          <p className="text-xs text-slate-400">
            {remoteProfile === 'lan'
              ? 'LAN mode uses the same HTTPS + token auth as remote mode, but targets a local-network host/IP instead of a Tailnet DNS name.'
              : 'Tailscale mode uses your Tailnet hostname and the existing HTTPS + token auth flow.'}
          </p>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
            {remoteProfile === 'lan' ? 'LAN Host / IP' : 'Tailscale Host'}
          </label>
          <input
            type="text"
            placeholder={
              remoteProfile === 'lan'
                ? 'e.g. 192.168.1.50 or k8s-gpu.local'
                : 'e.g. my-server.tail123.ts.net'
            }
            value={activeHost}
            onChange={(e) =>
              remoteProfile === 'lan' ? setLanHost(e.target.value) : setRemoteHost(e.target.value)
            }
            className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none"
          />
          {looksLikeBareTailnet && (
            <p className="mt-1.5 text-xs text-amber-300/80">
              This looks like a tailnet name. The hostname should include the machine name, e.g.{' '}
              <span className="font-mono">machine-name.{remoteHost.trim()}</span>
            </p>
          )}
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
            Auth Token
          </label>
          <div className="relative">
            <input
              type={showAuthToken ? 'text' : 'password'}
              value={authToken}
              onChange={(e) => {
                tokenDirtyRef.current = true;
                setAuthToken(e.target.value);
              }}
              placeholder="Paste the token from the host machine"
              className="focus:border-accent-cyan/50 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-20 font-mono text-sm text-white focus:outline-none"
            />
            <div className="absolute top-2 right-2 flex items-center gap-1">
              <button
                onClick={() => {
                  if (!authToken) return;
                  writeToClipboard(authToken).catch(() => {});
                  setAuthTokenCopied(true);
                  setTimeout(() => setAuthTokenCopied(false), 2000);
                }}
                className="p-1 text-slate-500 transition-colors hover:text-white"
                title="Copy token"
              >
                {authTokenCopied ? (
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

        <div className="grid grid-cols-2 items-end gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
              Port
            </label>
            <input
              type="number"
              value={port}
              onChange={(e) => setPort(parseInt(e.target.value))}
              className="focus:border-accent-cyan/50 w-full [appearance:textfield] rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white focus:outline-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
          </div>
          <div className="flex justify-end pb-1">
            <Button
              variant="secondary"
              className="h-9 px-4 whitespace-nowrap"
              onClick={handleApply}
              disabled={applying || !hydrated}
            >
              {applying ? <Loader2 size={14} className="animate-spin" /> : 'Apply'}
            </Button>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          HTTPS is always used for remote profiles (Tailscale and LAN) to keep token auth enabled.
        </p>
      </div>
    </GlassCard>
  );
}
