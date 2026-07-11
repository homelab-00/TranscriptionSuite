import React, { useEffect, useState } from 'react';
import { AlertTriangle, Check, Copy, Eye, EyeOff } from 'lucide-react';

import { GlassCard } from '../../ui/GlassCard';
import { writeToClipboard } from '../../../src/hooks/useClipboard';
import { DEFAULT_SERVER_PORT } from '../../../src/config/store';

interface RemoteConnectionCardProps {
  title: string;
  /** Firewall check only makes sense once the server is up and healthy. */
  isRunningAndHealthy: boolean;
}

/**
 * Remote Connection card: the credentials a remote client needs — the
 * server auth token and the machine's Tailscale hostname — plus a firewall
 * warning when the remote port looks blocked. Self-contained: loads its own
 * data through the electronAPI bridge.
 */
export function RemoteConnectionCard({ title, isRunningAndHealthy }: RemoteConnectionCardProps) {
  const [authToken, setAuthToken] = useState('');
  const [showAuthToken, setShowAuthToken] = useState(false);
  const [authTokenCopied, setAuthTokenCopied] = useState(false);
  const [tailscaleHostname, setTailscaleHostname] = useState<string | null>(null);
  const [tailscaleHostnameCopied, setTailscaleHostnameCopied] = useState(false);
  const [firewallWarning, setFirewallWarning] = useState<string | null>(null);

  // Re-fetch when the server comes up: the auth token is generated during the
  // first server start, so a mount-only load would miss it until a remount.
  useEffect(() => {
    const api = (window as any).electronAPI;
    api?.config
      ?.get('connection.authToken')
      .then((val: unknown) => {
        if (typeof val === 'string') setAuthToken(val);
      })
      .catch(() => {});
    if (api?.tailscale?.getHostname) {
      api.tailscale
        .getHostname()
        .then((hostname: string | null) => {
          if (hostname) setTailscaleHostname(hostname);
        })
        .catch(() => {});
    }
  }, [isRunningAndHealthy]);

  // Check the firewall when the container becomes healthy in remote mode.
  useEffect(() => {
    if (!isRunningAndHealthy) {
      setFirewallWarning(null);
      return;
    }
    const api = (window as any).electronAPI;
    if (!api?.server?.checkFirewallPort || !api?.config?.get) return;

    api.config
      .get('connection.useRemote')
      .then(async (useRemote: unknown) => {
        const tlsFromCompose = await api.docker
          ?.readComposeEnvValue?.('TLS_ENABLED')
          .catch(() => null);
        const isRemote = useRemote === true || tlsFromCompose === 'true';
        if (!isRemote) return;

        try {
          const port = ((await api.config.get('connection.port')) as number) ?? DEFAULT_SERVER_PORT;
          const result = await api.server.checkFirewallPort(port);
          if (result.firewallSuspect && result.hint) {
            setFirewallWarning(result.hint);
          } else {
            setFirewallWarning(null);
          }
        } catch {
          // Best effort
        }
      })
      .catch(() => {});
  }, [isRunningAndHealthy]);

  return (
    <GlassCard title={title}>
      <div className="space-y-4">
        {authToken ? (
          <div>
            <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
              Auth Token
            </label>
            <div className="relative">
              <input
                type={showAuthToken ? 'text' : 'password'}
                value={authToken}
                readOnly
                className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 pr-20 font-mono text-sm text-white focus:outline-none"
              />
              <div className="absolute top-2 right-2 flex items-center gap-1">
                <button
                  onClick={() => {
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
            <p className="mt-1.5 text-xs text-slate-500">
              Remote clients authenticate with this token.
            </p>
          </div>
        ) : (
          <p className="text-xs text-slate-500 italic">
            The auth token appears here after the server generates one (first start).
          </p>
        )}

        {tailscaleHostname && (
          <div>
            <label className="mb-1.5 block text-xs font-medium tracking-wider text-slate-500 uppercase">
              Tailscale Hostname
            </label>
            <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <span className="flex-1 truncate font-mono text-sm text-slate-300">
                {tailscaleHostname}
              </span>
              <button
                onClick={() => {
                  writeToClipboard(tailscaleHostname).catch(() => {});
                  setTailscaleHostnameCopied(true);
                  setTimeout(() => setTailscaleHostnameCopied(false), 2000);
                }}
                className="shrink-0 p-1 text-slate-500 transition-colors hover:text-white"
                title="Copy Tailscale hostname"
              >
                {tailscaleHostnameCopied ? (
                  <Check size={14} className="text-green-400" />
                ) : (
                  <Copy size={14} />
                )}
              </button>
            </div>
            <p className="mt-1.5 text-xs text-slate-500">
              Use this hostname when configuring remote clients to connect via Tailscale.
            </p>
          </div>
        )}

        {firewallWarning && isRunningAndHealthy && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
            <div className="text-xs text-amber-200">
              <p className="font-medium">Firewall may block remote connections</p>
              <p className="mt-0.5 text-amber-300/80">{firewallWarning}</p>
            </div>
          </div>
        )}
      </div>
    </GlassCard>
  );
}
