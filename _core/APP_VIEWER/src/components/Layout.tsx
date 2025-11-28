import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Calendar, Search, Upload, Menu, X, Mic } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

const menuItems = [
  { text: 'Calendar', icon: Calendar, path: '/' },
  { text: 'Search', icon: Search, path: '/search' },
  { text: 'Import', icon: Upload, path: '/import' },
];

export default function Layout({ children }: LayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleNavigation = (path: string) => {
    navigate(path);
    setMobileOpen(false);
  };

  const currentPage = menuItems.find((item) => item.path === location.pathname)?.text || 'Recording';

  return (
    <>
      {/* Mobile header */}
      <header className="fixed top-0 left-0 right-0 z-40 h-14 bg-surface border-b border-gray-800 flex items-center px-4 md:hidden">
        <button
          onClick={handleDrawerToggle}
          className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-surface-light transition-colors"
        >
          <Menu size={24} />
        </button>
        <h1 className="ml-4 text-lg font-semibold text-white">{currentPage}</h1>
      </header>

      {/* Mobile drawer backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden animate-fade-in"
          onClick={handleDrawerToggle}
        />
      )}

      {/* Sidebar */}
      <nav
        className={`
          fixed top-0 left-0 h-full w-60 bg-surface border-r border-gray-800 z-50
          transform transition-transform duration-300 ease-in-out
          md:translate-x-0
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo/Brand */}
        <div className="h-16 px-4 flex items-center gap-3 border-b border-gray-800">
          <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
            <Mic size={20} className="text-primary" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-white leading-tight">Audio</h1>
            <h1 className="text-base font-semibold text-white leading-tight">Notebook</h1>
          </div>
          {/* Mobile close button */}
          <button
            onClick={handleDrawerToggle}
            className="ml-auto p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-surface-light transition-colors md:hidden"
          >
            <X size={20} />
          </button>
        </div>

        {/* Navigation items */}
        <div className="py-4 px-3">
          {menuItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <button
                key={item.text}
                onClick={() => handleNavigation(item.path)}
                className={`
                  w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium mb-1
                  transition-all duration-200
                  ${isActive
                    ? 'bg-primary/20 text-primary'
                    : 'text-gray-400 hover:text-white hover:bg-surface-light'
                  }
                `}
              >
                <Icon size={20} />
                {item.text}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Main content */}
      <main className="min-h-screen pt-14 md:pt-0 md:pl-60">
        <div className="h-[calc(100vh-3.5rem)] md:h-screen flex items-start justify-center p-4 md:p-6">
          {children}
        </div>
      </main>
    </>
  );
}
