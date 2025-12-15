import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import { TokenInfo } from '../types';

export function AdminPanel() {
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTokenName, setNewTokenName] = useState('');
  const [newTokenAdmin, setNewTokenAdmin] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const loadTokens = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await api.listTokens();
      setTokens(result.tokens);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tokens');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTokens();
  }, [loadTokens]);

  const handleCreateToken = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTokenName.trim()) return;

    setIsCreating(true);
    setError(null);

    try {
      await api.createToken(newTokenName.trim(), newTokenAdmin);
      setNewTokenName('');
      setNewTokenAdmin(false);
      await loadTokens();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create token');
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, newTokenAdmin, loadTokens]);

  const handleRevokeToken = useCallback(async (token: string, clientName: string) => {
    if (!confirm(`Revoke token for "${clientName}"? This cannot be undone.`)) {
      return;
    }

    try {
      await api.revokeToken(token);
      await loadTokens();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke token');
    }
  }, [loadTokens]);

  const copyToken = useCallback(async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedToken(token);
      setTimeout(() => setCopiedToken(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, []);

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-white">Token Management</h2>
        <button
          onClick={loadTokens}
          disabled={isLoading}
          className="px-3 py-2 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg 
                   transition-colors flex items-center gap-2"
        >
          <svg className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Create new token form */}
      <div className="bg-slate-800 rounded-xl p-6 border border-slate-700 mb-6">
        <h3 className="text-lg font-medium text-white mb-4">Create New Token</h3>
        <form onSubmit={handleCreateToken} className="flex items-end gap-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Client Name
            </label>
            <input
              type="text"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              placeholder="e.g., my-laptop, phone, etc."
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg 
                       text-white placeholder-slate-400 focus:outline-none focus:ring-2 
                       focus:ring-primary-500"
              disabled={isCreating}
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="admin-checkbox"
              checked={newTokenAdmin}
              onChange={(e) => setNewTokenAdmin(e.target.checked)}
              className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-primary-600"
              disabled={isCreating}
            />
            <label htmlFor="admin-checkbox" className="text-sm text-slate-300">
              Admin
            </label>
          </div>
          <button
            type="submit"
            disabled={isCreating || !newTokenName.trim()}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-600 
                     disabled:cursor-not-allowed text-white rounded-lg transition-colors"
          >
            {isCreating ? 'Creating...' : 'Create Token'}
          </button>
        </form>
      </div>

      {/* Error display */}
      {error && (
        <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg mb-6">
          <p className="text-red-300 text-sm">{error}</p>
        </div>
      )}

      {/* Token list */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Client</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Token</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Created</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Status</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-slate-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                  Loading tokens...
                </td>
              </tr>
            ) : tokens.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                  No tokens found
                </td>
              </tr>
            ) : (
              tokens.map((token) => (
                <tr key={token.full_token} className="hover:bg-slate-700/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-white">{token.client_name}</span>
                      {token.is_admin && (
                        <span className="px-2 py-0.5 text-xs bg-primary-900/50 text-primary-300 rounded">
                          Admin
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <code className="text-sm text-slate-400 font-mono">{token.token}</code>
                      <button
                        onClick={() => copyToken(token.full_token)}
                        className="p-1 hover:bg-slate-600 rounded transition-colors"
                        title="Copy full token"
                      >
                        {copiedToken === token.full_token ? (
                          <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        ) : (
                          <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-400">
                    {formatDate(token.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    {token.is_revoked ? (
                      <span className="px-2 py-1 text-xs bg-red-900/50 text-red-300 rounded">
                        Revoked
                      </span>
                    ) : (
                      <span className="px-2 py-1 text-xs bg-green-900/50 text-green-300 rounded">
                        Active
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!token.is_revoked && (
                      <button
                        onClick={() => handleRevokeToken(token.full_token, token.client_name)}
                        className="px-3 py-1 text-sm text-red-400 hover:text-red-300 
                                 hover:bg-red-900/30 rounded transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-sm text-slate-500">
        <p>⚠️ Tokens never expire automatically. Revoke tokens manually when no longer needed.</p>
        <p className="mt-1">💡 Share tokens securely. Anyone with a token can use your transcription server.</p>
      </div>
    </div>
  );
}
