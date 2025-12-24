import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Copy, Check, X } from 'lucide-react';
import { api } from '../services/api';
import { TokenInfo, NewTokenInfo } from '../types';

export default function AdminView() {
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTokenName, setNewTokenName] = useState('');
  const [newTokenAdmin, setNewTokenAdmin] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  
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
      return { text: 'Revoked', className: 'chip-error' };
    }
    if (token.is_expired) {
      return { text: 'Expired', className: 'bg-warning/20 text-warning' };
    }
    if (!token.expires_at) {
      return { text: 'Never expires', className: 'chip-success' };
    }
    return { text: 'Active', className: 'chip-success' };
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold text-white mb-6">Token Management</h1>

      {/* Token Created Modal */}
      {newlyCreatedToken && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="card max-w-lg w-full p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-success/20 rounded-lg">
                <Check size={24} className="text-success" />
              </div>
              <h3 className="text-lg font-semibold text-white">Token Created!</h3>
            </div>
            
            <div className="bg-warning/20 border border-warning/50 rounded-lg p-3 mb-4">
              <p className="text-warning text-sm font-medium">
                ⚠️ Save this token now! It will only be shown once.
              </p>
            </div>

            <div className="mb-4">
              <label className="label">Client Name</label>
              <p className="text-white">{newlyCreatedToken.client_name}</p>
            </div>

            <div className="mb-4">
              <label className="label">Token</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 p-3 bg-background rounded-lg text-sm text-success font-mono break-all">
                  {newlyCreatedToken.token}
                </code>
                <button
                  onClick={copyNewToken}
                  className={`btn-icon ${tokenCopied ? 'text-success' : ''}`}
                  title="Copy token"
                >
                  {tokenCopied ? <Check size={20} /> : <Copy size={20} />}
                </button>
              </div>
            </div>

            {newlyCreatedToken.expires_at && (
              <div className="mb-4">
                <label className="label">Expires</label>
                <p className="text-white">{formatDate(newlyCreatedToken.expires_at)}</p>
              </div>
            )}

            <div className="flex justify-end">
              <button
                onClick={closeTokenModal}
                className={tokenCopied ? 'btn-primary' : 'btn-secondary'}
              >
                {tokenCopied ? 'Done' : 'Close (token not copied)'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header with refresh button */}
      <div className="flex items-center justify-between mb-6">
        <p className="text-gray-400">Manage access tokens for clients</p>
        <button
          onClick={loadTokens}
          disabled={isLoading}
          className="btn-secondary"
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Create new token form */}
      <div className="card p-6 mb-6">
        <h3 className="text-lg font-medium text-white mb-4">Create New Token</h3>
        <form onSubmit={handleCreateToken} className="flex items-end gap-4">
          <div className="flex-1">
            <label className="label">Client Name</label>
            <input
              type="text"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              placeholder="e.g., my-laptop, phone, etc."
              className="input"
              disabled={isCreating}
            />
          </div>
          <div className="flex items-center gap-2 pb-2">
            <input
              type="checkbox"
              id="admin-checkbox"
              checked={newTokenAdmin}
              onChange={(e) => setNewTokenAdmin(e.target.checked)}
              className="w-4 h-4 rounded border-gray-600 bg-surface text-primary"
              disabled={isCreating}
            />
            <label htmlFor="admin-checkbox" className="text-sm text-gray-300">
              Admin
            </label>
          </div>
          <button
            type="submit"
            disabled={isCreating || !newTokenName.trim()}
            className="btn-primary"
          >
            {isCreating ? 'Creating...' : 'Create Token'}
          </button>
        </form>
      </div>

      {/* Error display */}
      {error && (
        <div className="p-3 bg-error/20 border border-error rounded-lg mb-6">
          <p className="text-error text-sm">{error}</p>
        </div>
      )}

      {/* Token list */}
      <div className="card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Client</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Token</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Created</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Expires</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-gray-400">Status</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-gray-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  Loading tokens...
                </td>
              </tr>
            ) : tokens.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  No tokens found
                </td>
              </tr>
            ) : (
              tokens.map((token) => {
                const status = getExpiryStatus(token);
                return (
                  <tr key={token.token_id} className="hover:bg-surface-light">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-white">{token.client_name}</span>
                        {token.is_admin && (
                          <span className="chip-primary">Admin</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <code className="text-sm text-gray-400 font-mono">{token.token}</code>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-400">
                      {formatDate(token.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-400">
                      {token.expires_at ? formatDate(token.expires_at) : 'Never'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`chip ${status.className}`}>
                        {status.text}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!token.is_revoked && (
                        <button
                          onClick={() => handleRevokeToken(token.token_id, token.client_name)}
                          className="btn-icon text-error hover:bg-error/20"
                        >
                          <X size={16} />
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

      <div className="mt-4 text-sm text-gray-500">
        <p>🔒 Regular tokens expire after 30 days. Admin tokens never expire.</p>
        <p className="mt-1">💡 Tokens are only shown once at creation - copy them immediately!</p>
      </div>
    </div>
  );
}
