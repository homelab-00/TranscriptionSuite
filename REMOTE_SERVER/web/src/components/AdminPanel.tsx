import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import { TokenInfo, NewTokenInfo } from '../types';

export function AdminPanel() {
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTokenName, setNewTokenName] = useState('');
  const [newTokenAdmin, setNewTokenAdmin] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  
  // Modal state for showing newly created token
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<NewTokenInfo | null>(null);
  const [tokenCopied, setTokenCopied] = useState(false);

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
      const result = await api.createToken(newTokenName.trim(), newTokenAdmin);
      setNewTokenName('');
      setNewTokenAdmin(false);
      // Show the newly created token in a modal
      setNewlyCreatedToken(result.token);
      setTokenCopied(false);
      await loadTokens();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create token');
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, newTokenAdmin, loadTokens]);

  const handleRevokeToken = useCallback(async (tokenId: string, clientName: string) => {
    if (!confirm(`Revoke token for "${clientName}"? This cannot be undone.`)) {
      return;
    }

    try {
      await api.revokeToken(tokenId);
      await loadTokens();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke token');
    }
  }, [loadTokens]);

  const copyNewToken = useCallback(async () => {
    if (!newlyCreatedToken) return;
    try {
      await navigator.clipboard.writeText(newlyCreatedToken.token);
      setTokenCopied(true);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, [newlyCreatedToken]);

  const closeTokenModal = useCallback(() => {
    if (!tokenCopied) {
      if (!confirm("Are you sure? You haven't copied the token yet. You won't be able to see it again!")) {
        return;
      }
    }
    setNewlyCreatedToken(null);
    setTokenCopied(false);
  }, [tokenCopied]);

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getExpiryStatus = (token: TokenInfo) => {
    if (token.is_revoked) {
      return { text: 'Revoked', className: 'bg-red-900/50 text-red-300' };
    }
    if (token.is_expired) {
      return { text: 'Expired', className: 'bg-orange-900/50 text-orange-300' };
    }
    if (!token.expires_at) {
      return { text: 'Never expires', className: 'bg-green-900/50 text-green-300' };
    }
    return { text: 'Active', className: 'bg-green-900/50 text-green-300' };
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Token Created Modal */}
      {newlyCreatedToken && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-800 rounded-xl border border-slate-700 max-w-lg w-full p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-green-900/50 rounded-lg">
                <svg className="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-white">Token Created!</h3>
            </div>
            
            <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg p-3 mb-4">
              <p className="text-yellow-200 text-sm font-medium">
                ⚠️ Save this token now! It will only be shown once.
              </p>
            </div>

            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">Client Name</label>
              <p className="text-white">{newlyCreatedToken.client_name}</p>
            </div>

            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">Token</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 p-3 bg-slate-900 rounded-lg text-sm text-green-400 font-mono break-all">
                  {newlyCreatedToken.token}
                </code>
                <button
                  onClick={copyNewToken}
                  className={`p-3 rounded-lg transition-colors ${
                    tokenCopied 
                      ? 'bg-green-600 text-white' 
                      : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                  }`}
                  title="Copy token"
                >
                  {tokenCopied ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {newlyCreatedToken.expires_at && (
              <div className="mb-4">
                <label className="block text-sm text-slate-400 mb-1">Expires</label>
                <p className="text-white">{formatDate(newlyCreatedToken.expires_at)}</p>
              </div>
            )}

            <div className="flex justify-end">
              <button
                onClick={closeTokenModal}
                className={`px-4 py-2 rounded-lg transition-colors ${
                  tokenCopied
                    ? 'bg-primary-600 hover:bg-primary-700 text-white'
                    : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                }`}
              >
                {tokenCopied ? 'Done' : 'Close (token not copied)'}
              </button>
            </div>
          </div>
        </div>
      )}

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
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Expires</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-slate-400">Status</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-slate-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  Loading tokens...
                </td>
              </tr>
            ) : tokens.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  No tokens found
                </td>
              </tr>
            ) : (
              tokens.map((token) => {
                const status = getExpiryStatus(token);
                return (
                  <tr key={token.token_id} className="hover:bg-slate-700/50">
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
                      <code className="text-sm text-slate-400 font-mono">{token.token}</code>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400">
                      {formatDate(token.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400">
                      {token.expires_at ? formatDate(token.expires_at) : 'Never'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 text-xs rounded ${status.className}`}>
                        {status.text}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!token.is_revoked && (
                        <button
                          onClick={() => handleRevokeToken(token.token_id, token.client_name)}
                          className="px-3 py-1 text-sm text-red-400 hover:text-red-300 
                                   hover:bg-red-900/30 rounded transition-colors"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-sm text-slate-500">
        <p>🔒 Regular tokens expire after 30 days. Admin tokens never expire.</p>
        <p className="mt-1">💡 Tokens are only shown once at creation - copy them immediately!</p>
      </div>
    </div>
  );
}
