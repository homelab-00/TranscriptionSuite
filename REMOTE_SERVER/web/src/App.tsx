import { useState } from 'react';
import { useAuth } from './hooks/useAuth';
import { LoginForm } from './components/LoginForm';
import { Header } from './components/Header';
import { RecordPanel } from './components/RecordPanel';
import { FileUploadPanel } from './components/FileUploadPanel';
import { AdminPanel } from './components/AdminPanel';

type Tab = 'record' | 'upload' | 'admin';

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

  // Render main app
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
          {activeTab === 'admin' && user.is_admin && <AdminPanel />}
        </div>
      </main>
    </div>
  );
}

export default App;
