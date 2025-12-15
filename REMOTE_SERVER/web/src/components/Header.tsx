import { User } from '../types';

interface HeaderProps {
  user: User;
  activeTab: 'record' | 'upload' | 'admin';
  onTabChange: (tab: 'record' | 'upload' | 'admin') => void;
  onLogout: () => void;
}

export function Header({ user, activeTab, onTabChange, onLogout }: HeaderProps) {
  const tabs = [
    { id: 'record' as const, label: 'Record', icon: '🎤' },
    { id: 'upload' as const, label: 'Upload File', icon: '📁' },
    ...(user.is_admin ? [{ id: 'admin' as const, label: 'Admin', icon: '⚙️' }] : []),
  ];

  return (
    <header className="bg-slate-800 border-b border-slate-700">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                  d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <span className="text-xl font-semibold text-white">Remote Transcription</span>
          </div>

          {/* User info & Logout */}
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-sm font-medium text-white">{user.name}</div>
              {user.is_admin && (
                <div className="text-xs text-primary-400">Admin</div>
              )}
            </div>
            <button
              onClick={onLogout}
              className="px-3 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-700 
                       rounded-lg transition-colors"
            >
              Logout
            </button>
          </div>
        </div>

        {/* Tabs */}
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`px-4 py-3 text-sm font-medium rounded-t-lg transition-colors
                ${activeTab === tab.id 
                  ? 'bg-slate-900 text-white border-t border-x border-slate-700' 
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                }`}
            >
              <span className="mr-2">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
