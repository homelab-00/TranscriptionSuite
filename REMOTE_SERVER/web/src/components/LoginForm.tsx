import { useState } from 'react';

interface LoginFormProps {
  onLogin: (token: string) => Promise<boolean>;
  isLoading: boolean;
  error: string | null;
}

export function LoginForm({ onLogin, isLoading, error }: LoginFormProps) {
  const [token, setToken] = useState('');
  const [rememberToken, setRememberToken] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;

    const success = await onLogin(token.trim());
    if (!success && !rememberToken) {
      setToken('');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800 p-4">
      <div className="w-full max-w-md">
        <div className="bg-slate-800 rounded-2xl shadow-xl p-8 border border-slate-700">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-600 rounded-full mb-4">
              <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                  d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-white">Remote Transcription</h1>
            <p className="text-slate-400 mt-2">Enter your authentication token</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="token" className="block text-sm font-medium text-slate-300 mb-2">
                Token
              </label>
              <input
                type="password"
                id="token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Enter your token..."
                className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg 
                         text-white placeholder-slate-400 focus:outline-none focus:ring-2 
                         focus:ring-primary-500 focus:border-transparent transition-all"
                disabled={isLoading}
                autoFocus
              />
            </div>

            {error && (
              <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg">
                <p className="text-red-300 text-sm">{error}</p>
              </div>
            )}

            <div className="flex items-center">
              <input
                type="checkbox"
                id="remember"
                checked={rememberToken}
                onChange={(e) => setRememberToken(e.target.checked)}
                className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-primary-600 
                         focus:ring-primary-500 focus:ring-offset-slate-800"
              />
              <label htmlFor="remember" className="ml-2 text-sm text-slate-300">
                Remember token
              </label>
            </div>

            <button
              type="submit"
              disabled={isLoading || !token.trim()}
              className="w-full py-3 px-4 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-600 
                       disabled:cursor-not-allowed text-white font-medium rounded-lg 
                       transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 
                       focus:ring-offset-2 focus:ring-offset-slate-800"
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Authenticating...
                </span>
              ) : (
                'Login'
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-slate-500 text-sm mt-6">
          Contact your administrator if you don't have a token
        </p>
      </div>
    </div>
  );
}
