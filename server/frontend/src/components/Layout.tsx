import { useState } from 'react';
import { Calendar, Search, Upload, Menu, X, Mic, Settings } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

interface MenuItem {
  text: string;
  icon: typeof Calendar;
  href: string;  // Full URL path for navigation
}

interface MenuSection {
  items: MenuItem[];
}

// Use full paths since we need to navigate across different basenames
const menuSections: MenuSection[] = [
  {
    items: [
      { text: 'Calendar', icon: Calendar, href: '/notebook/calendar' },
      { text: 'Search', icon: Search, href: '/notebook/search' },
      { text: 'Import', icon: Upload, href: '/notebook/import' },
    ],
  },
  {
    items: [
      { text: 'Record', icon: Mic, href: '/record' },
    ],
  },
  {
    items: [
      { text: 'Admin', icon: Settings, href: '/admin' },
    ],
  },
];

export default function Layout({ children }: LayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  // Use window.location for cross-section navigation (different basenames)
  const handleNavigation = (href: string) => {
    window.location.href = href;
  };

  // Check if current path matches menu item
  const isActive = (href: string): boolean => {
    const currentPath = window.location.pathname;
    // Exact match or starts with (for nested routes)
    if (href === '/notebook/calendar' && (currentPath === '/notebook' || currentPath === '/notebook/')) return true;
    return currentPath === href || currentPath.startsWith(href + '/');
  };

  const allItems = menuSections.flatMap(s => s.items);
  const currentPage = allItems.find((item) => isActive(item.href))?.text || 'Calendar';

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
            <h1 className="text-sm font-semibold text-white leading-tight">Transcription Suite</h1>
            <h1 className="text-xs text-gray-400 leading-tight">Web UI</h1>
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
          {menuSections.map((section, sectionIndex) => (
            <div key={sectionIndex}>
              {/* Divider between sections */}
              {sectionIndex > 0 && (
                <div className="my-3 border-t border-gray-700" />
              )}
              {section.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <button
                    key={item.text}
                    onClick={() => handleNavigation(item.href)}
                    className={`
                      w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium mb-1
                      transition-all duration-200
                      ${active
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
          ))}
        </div>
      </nav>

      {/* Main content */}
      <main className="min-h-screen pt-14 md:pt-0 md:pl-60">
        <div className="h-[calc(100vh-3.5rem)] md:h-screen overflow-y-auto overflow-x-hidden p-4 md:p-8 flex flex-col">
          {children}
        </div>
      </main>
    </>
  );
}
