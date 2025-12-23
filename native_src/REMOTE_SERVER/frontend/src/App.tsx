import { useState } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginForm } from './components/LoginForm';
import { Header } from './components/Header';
import { RecordPanel } from './components/RecordPanel';
import { FileUploadPanel } from './components/FileUploadPanel';
import { AdminPanel } from './components/AdminPanel';

type Tab = 'record' | 'upload';

// Check if we're on the admin page
const isAdminPage = window.location.pathname.startsWith('/admin');

function App() {
  const { user, isLoading, error, isAuthenticated, login, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>('record');

  // Show loading spinner while checking auth
  if (isLoading && !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900">
        <div className="text-center">
          <svg className="animate-spin h-12 w-12 mx-auto text-primary-500 mb-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-slate-400">Loading...</p>
        </div>
      </div>
    );
  }

  // Show login form if not authenticated
  if (!isAuthenticated || !user) {
    return <LoginForm onLogin={login} isLoading={isLoading} error={error} />;
  }

  // Admin page - show only admin panel for admin users
  if (isAdminPage) {
    if (!user.is_admin) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-900">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-red-400 mb-2">Access Denied</h1>
            <p className="text-slate-400 mb-4">You need admin privileges to access this page.</p>
            <a href="/record" className="text-primary-400 hover:text-primary-300">
              Go to Record UI →
            </a>
          </div>
        </div>
      );
    }

    return (
      <div className="min-h-screen flex flex-col bg-slate-900">
        <header className="bg-slate-800 border-b border-slate-700 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-bold text-white">Admin Panel</h1>
              <span className="px-2 py-1 text-xs bg-primary-900/50 text-primary-300 rounded">
                {user.name}
              </span>
            </div>
            <div className="flex items-center gap-4">
              <a href="/record" className="text-sm text-slate-400 hover:text-white transition-colors">
                ← Back to Record
              </a>
              <button
                onClick={logout}
                className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
              >
                Logout
              </button>
            </div>
          </div>
        </header>
        <main className="flex-1 p-6">
          <div className="max-w-6xl mx-auto">
            <AdminPanel />
          </div>
        </main>
      </div>
    );
  }

  // Record page - show record/upload tabs (no admin tab)
  return (
    <div className="min-h-screen flex flex-col bg-slate-900">
      <Header 
        user={user} 
        activeTab={activeTab} 
        onTabChange={setActiveTab} 
        onLogout={logout}
      />

      <main className="flex-1 p-6">
        <div className="max-w-6xl mx-auto h-full">
          {activeTab === 'record' && <RecordPanel />}
          {activeTab === 'upload' && <FileUploadPanel />}
        </div>
      </main>
    </div>
  );
}

export default App;
