import type Store from 'electron-store';

type AnyStore = Store<any>;

export type IdleResult = { idle: true } | { idle: false; reason: string };

function getServerUrl(store: AnyStore): string {
  const useRemote = (store.get('connection.useRemote') as boolean) ?? false;
  const remoteProfile =
    (store.get('connection.remoteProfile') as 'tailscale' | 'lan') ?? 'tailscale';
  const remoteHost = ((store.get('connection.remoteHost') as string) ?? '').trim();
  const lanHost = ((store.get('connection.lanHost') as string) ?? '').trim();
  const localHost =
    (store.get('connection.localHost') as string) ??
    (store.get('server.host') as string) ??
    'localhost';
  const host = useRemote
    ? (remoteProfile === 'lan' ? lanHost : remoteHost) || 'localhost'
    : localHost;
  const port =
    (store.get('connection.port') as number) ?? (store.get('server.port') as number) ?? 9786;
  const https =
    (store.get('connection.useHttps') as boolean) ??
    (store.get('server.https') as boolean) ??
    false;
  const protocol = https ? 'https' : 'http';
  return `${protocol}://${host}:${port}`;
}

function getAuthToken(store: AnyStore): string | null {
  const token = (store.get('connection.authToken') as string) ?? '';
  return token || null;
}

export interface AppStateModule {
  isAppIdle(timeoutMs?: number): Promise<IdleResult>;
}

export function createAppState(store: AnyStore): AppStateModule {
  return {
    async isAppIdle(timeoutMs = 5000): Promise<IdleResult> {
      const url = `${getServerUrl(store)}/api/admin/status`;
      const token = getAuthToken(store);
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      try {
        const resp = await fetch(url, {
          method: 'GET',
          headers,
          signal: AbortSignal.timeout(timeoutMs),
        });
        if (!resp.ok) {
          // 401/403 distinguished so consumers can tell "we can't probe" (auth)
          // from "we can't reach the server" (network). Both are fail-closed
          // for the install gate; shutdown treats both as "proceed with quit".
          if (resp.status === 401 || resp.status === 403) {
            return { idle: false, reason: 'auth-error' };
          }
          return { idle: false, reason: 'server-unreachable' };
        }
        const body = (await resp.json()) as {
          models?: { job_tracker?: { is_busy?: boolean; active_user?: string | null } };
        };
        const jt = body?.models?.job_tracker;
        if (!jt || typeof jt.is_busy !== 'boolean') {
          return { idle: false, reason: 'unknown' };
        }
        if (!jt.is_busy) return { idle: true };
        const who = jt.active_user;
        return {
          idle: false,
          reason: `active transcription${who ? ` (${who})` : ''}`,
        };
      } catch {
        return { idle: false, reason: 'server-unreachable' };
      }
    },
  };
}

export type InstallRequestResult = {
  ok: boolean;
  reason?: string;
  detail?: string;
};

export interface InstallGateOptions {
  idleCheck: () => Promise<IdleResult>;
  onReady: () => void;
  doInstall: () => Promise<{ ok: boolean; reason?: string }>;
  pollMs?: number;
}

export class InstallGate {
  private pending: { timer: ReturnType<typeof setInterval> } | null = null;
  // True while requestInstall awaits its initial idleCheck. Prevents a
  // concurrent second call from racing past the pending null-check and
  // orphaning the first caller's interval.
  private requesting = false;
  // True while a poll tick awaits idleCheck. Prevents overlapping ticks
  // from issuing concurrent fetches.
  private tickInFlight = false;
  private destroyed = false;
  private readonly pollMs: number;

  constructor(private readonly opts: InstallGateOptions) {
    this.pollMs = opts.pollMs ?? 30_000;
  }

  async requestInstall(): Promise<InstallRequestResult> {
    if (this.pending || this.requesting) {
      return { ok: false, reason: 'already-deferred' };
    }
    this.requesting = true;
    try {
      const status = await this.opts.idleCheck();
      if (this.destroyed) {
        return { ok: false, reason: 'destroyed' };
      }
      if (status.idle === true) {
        return this.opts.doInstall();
      }
      const detail = status.reason;
      const timer = setInterval(() => {
        void this.tick();
      }, this.pollMs);
      this.pending = { timer };
      return { ok: false, reason: 'deferred-until-idle', detail };
    } finally {
      this.requesting = false;
    }
  }

  cancelPending(): { ok: true } {
    if (this.pending) {
      clearInterval(this.pending.timer);
      this.pending = null;
    }
    return { ok: true };
  }

  isPending(): boolean {
    return this.pending !== null;
  }

  destroy(): void {
    this.destroyed = true;
    this.cancelPending();
  }

  private async tick(): Promise<void> {
    if (this.tickInFlight || !this.pending) return;
    this.tickInFlight = true;
    try {
      const status = await this.opts.idleCheck();
      if (!this.pending) return;
      if (status.idle === true) {
        this.cancelPending();
        this.opts.onReady();
      }
    } finally {
      this.tickInFlight = false;
    }
  }
}
