import React, { useCallback, useLayoutEffect, useRef, useState, useEffect } from 'react';
import { View, NotebookTab, SessionTab } from '../types';
import {
  Mic2,
  Book,
  Server,
  Library,
  Settings,
  ChevronLeft,
  ChevronRight,
  Info,
  Terminal,
  Search,
  Upload,
  Bug,
  Download,
} from 'lucide-react';
import logoUrl from '../../docs/assets/logo.png';
import { StatusLight } from './ui/StatusLight';

interface SidebarProps {
  currentView: View;
  onChangeView: (view: View) => void;
  notebookTab: NotebookTab;
  onChangeNotebookTab: (tab: NotebookTab) => void;
  sessionTab: SessionTab;
  onChangeSessionTab: (tab: SessionTab) => void;
  onOpenSettings: () => void;
  onOpenAbout: () => void;
  onOpenBugReport: () => void;
  containerRunning: boolean;
  containerExists: boolean;
  containerHealth?: string;
  clientRunning: boolean;
  gpuError?: string;
  runtimeProfile?: 'gpu' | 'cpu' | 'vulkan' | 'metal';
  serverReachable?: boolean;
  mlxProcessAlive?: boolean;
}

const SIDEBAR_COLLAPSED_WIDTH_PX = 80;
const SIDEBAR_EXPANDED_BASE_WIDTH_PX = 192;
const SIDEBAR_LOGO_HORIZONTAL_PADDING_PX = 24;
const SIDEBAR_LOGO_COMFORT_BUFFER_PX = 16;

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onChangeView,
  notebookTab,
  onChangeNotebookTab,
  sessionTab,
  onChangeSessionTab,
  onOpenSettings,
  onOpenAbout,
  onOpenBugReport,
  containerRunning,
  containerExists,
  containerHealth,
  clientRunning,
  gpuError,
  runtimeProfile,
  serverReachable,
  mlxProcessAlive,
}) => {
  const isMetal = runtimeProfile === 'metal';
  const [collapsed, setCollapsed] = useState(false);
  const [expandedWidthPx, setExpandedWidthPx] = useState(SIDEBAR_EXPANDED_BASE_WIDTH_PX);
  const logoContentRef = useRef<HTMLDivElement | null>(null);
  const hasElectronApi = typeof window !== 'undefined' && Boolean((window as any).electronAPI);
  const useMockupStatusFallback = !hasElectronApi;

  const updateExpandedWidth = useCallback(() => {
    if (collapsed || !logoContentRef.current) return;

    const logoContentWidth = Math.ceil(logoContentRef.current.getBoundingClientRect().width);
    const minComfortableWidth =
      logoContentWidth + SIDEBAR_LOGO_HORIZONTAL_PADDING_PX * 2 + SIDEBAR_LOGO_COMFORT_BUFFER_PX;
    const nextWidth = Math.max(SIDEBAR_EXPANDED_BASE_WIDTH_PX, minComfortableWidth);

    setExpandedWidthPx((previousWidth) =>
      previousWidth === nextWidth ? previousWidth : nextWidth,
    );
  }, [collapsed]);

  useLayoutEffect(() => {
    updateExpandedWidth();
  }, [updateExpandedWidth]);

  useLayoutEffect(() => {
    if (typeof window === 'undefined') return;

    const handleViewportChange = () => {
      updateExpandedWidth();
    };

    window.addEventListener('resize', handleViewportChange);
    return () => {
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [updateExpandedWidth]);

  useLayoutEffect(() => {
    if (typeof ResizeObserver === 'undefined' || !logoContentRef.current) return;

    const logoResizeObserver = new ResizeObserver(() => {
      updateExpandedWidth();
    });

    logoResizeObserver.observe(logoContentRef.current);
    return () => {
      logoResizeObserver.disconnect();
    };
  }, [updateExpandedWidth]);

  // Derive status for each sidebar item from Docker + client state
  // Issue 17 — Session: pulsing green when server AND client running AND healthy, orange when container exists, gray otherwise
  // For bare-metal mode, use server reachability instead of Docker container state.
  // mlxProcessAlive shows orange (warning) when the server process is alive but not yet accepting connections.
  const sessionStatus: 'active' | 'warning' | 'inactive' | 'error' = gpuError
    ? 'error'
    : useMockupStatusFallback
      ? 'active'
      : isMetal
        ? serverReachable
          ? 'active'
          : mlxProcessAlive
            ? 'warning'
            : 'inactive'
        : containerRunning && clientRunning && containerHealth === 'healthy'
          ? 'active'
          : containerExists
            ? 'warning'
            : 'inactive';
  // Issue 18 — Server: pulsing green when server running AND healthy, orange when container exists, gray otherwise
  const serverSidebarStatus: 'active' | 'warning' | 'inactive' | 'error' = gpuError
    ? 'error'
    : useMockupStatusFallback
      ? 'active'
      : isMetal
        ? serverReachable
          ? 'active'
          : mlxProcessAlive
            ? 'warning'
            : 'inactive'
        : containerRunning && containerHealth === 'healthy'
          ? 'active'
          : containerExists
            ? 'warning'
            : 'inactive';

  // Top navigation items that get the sliding animation
  const navItems = [
    {
      id: View.SESSION,
      label: 'Session',
      icon: <Mic2 size={20} />,
      status: sessionStatus as 'active' | 'warning' | 'inactive' | 'error',
    },
    {
      id: View.NOTEBOOK,
      label: 'Notebook',
      icon: <Book size={20} />,
      status: serverSidebarStatus as 'active' | 'warning' | 'inactive' | 'error',
    },
    {
      id: View.SERVER,
      label: 'Server',
      icon: <Server size={20} />,
      status: serverSidebarStatus as 'active' | 'warning' | 'inactive' | 'error',
    },
    {
      id: View.MODEL_MANAGER,
      label: 'Models',
      icon: <Library size={20} />,
    },
    {
      id: View.ACTIVITY,
      label: 'Activity',
      icon: <Download size={20} />,
    },
    {
      id: View.LOGS,
      label: 'Logs',
      icon: <Terminal size={20} />,
    },
  ];

  // Sub-items shown indented below the Notebook nav item
  const notebookSubItems = [
    { id: NotebookTab.SEARCH, icon: <Search size={14} />, label: 'Search' },
    { id: NotebookTab.IMPORT, icon: <Upload size={14} />, label: 'Import' },
  ];

  // Sub-items shown indented below the Session nav item
  const sessionSubItems = [{ id: SessionTab.IMPORT, icon: <Upload size={14} />, label: 'Import' }];

  const activeIndex = navItems.findIndex((item) => item.id === currentView);

  // Ref-based pill positioning — measures actual button positions
  // so the sliding pill works correctly with always-visible sub-tabs.
  const navRef = useRef<HTMLElement>(null);
  const buttonRefs = useRef<Map<View, HTMLButtonElement>>(new Map());
  const [pillTop, setPillTop] = useState<number | null>(null);

  const measurePillPosition = useCallback(() => {
    const btn = buttonRefs.current.get(currentView);
    if (btn) setPillTop(btn.offsetTop);
  }, [currentView]);

  useLayoutEffect(() => {
    measurePillPosition();
  }, [measurePillPosition]);

  // Re-measure on window resize (sidebar width changes affect layout)
  useEffect(() => {
    window.addEventListener('resize', measurePillPosition);
    return () => window.removeEventListener('resize', measurePillPosition);
  }, [measurePillPosition]);

  const sidebarWidthPx = collapsed ? SIDEBAR_COLLAPSED_WIDTH_PX : expandedWidthPx;

  return (
    <div
      className={`bg-glass-surface border-glass-border relative flex h-full shrink-0 flex-col border-r backdrop-blur-2xl transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] ${collapsed ? 'w-20' : 'w-48'} `}
      style={{
        width: sidebarWidthPx,
      }}
    >
      {/* Toggle Button */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="hover:bg-accent-cyan absolute top-10 -right-3 z-20 rounded-full border border-white/10 bg-slate-800 p-1 text-white shadow-lg transition-colors outline-none hover:text-black focus:outline-none"
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>

      {/* Logo Area */}
      <div className={`flex p-6 ${collapsed ? 'justify-center' : ''} transition-all duration-300`}>
        <div
          ref={logoContentRef}
          className={`inline-flex shrink-0 items-center transition-all duration-300 ${collapsed ? '' : 'gap-3'}`}
        >
          <div className="relative shrink-0">
            <img
              src={logoUrl}
              alt="TranscriptionSuite"
              className="h-10 w-10 rounded-xl shadow-lg"
              draggable={false}
            />
          </div>

          <div
            className={`overflow-hidden transition-all duration-300 ${collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100'}`}
          >
            <h1 className="text-lg leading-tight font-bold whitespace-nowrap text-white">
              Transcription
            </h1>
            <h2 className="text-accent-cyan text-xs font-bold tracking-widest uppercase">Suite</h2>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav ref={navRef} className="relative flex flex-1 flex-col gap-2 px-3 py-6">
        {/* Animated Background Pill for Active State */}
        {activeIndex !== -1 && pillTop !== null && (
          <div
            className="pointer-events-none absolute top-0 right-3 left-3 z-0 h-12 rounded-xl border border-white/5 bg-linear-to-r from-white/10 to-transparent shadow-inner transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)]"
            style={{
              transform: `translateY(${pillTop}px)`,
            }}
          >
            {/* Active Indicator Bar (Cyan) */}
            <div className="bg-accent-cyan absolute top-1/2 left-0 h-6 w-1 -translate-y-1/2 rounded-r-full shadow-[0_0_10px_#22d3ee]"></div>
          </div>
        )}

        {navItems.map((item) => {
          const isActive = currentView === item.id;
          return (
            <React.Fragment key={item.id}>
              <button
                ref={(el) => {
                  if (el) buttonRefs.current.set(item.id, el);
                }}
                onClick={() => {
                  onChangeView(item.id);
                  if (item.id === View.NOTEBOOK) onChangeNotebookTab(NotebookTab.CALENDAR);
                  if (item.id === View.SESSION) onChangeSessionTab(SessionTab.MAIN);
                }}
                className={`relative z-10 flex w-full items-center focus:ring-0 focus:outline-none ${collapsed ? 'justify-center px-0' : 'px-4'} h-12 rounded-xl transition-colors duration-200 ${
                  isActive ? 'text-white' : 'text-slate-400 hover:bg-white/5 hover:text-white'
                } `}
              >
                <div className={`flex items-center gap-4 transition-all duration-200`}>
                  <span
                    className={`transition-colors duration-200 ${isActive ? 'text-accent-cyan' : ''}`}
                  >
                    {item.icon}
                  </span>
                  <span
                    className={`text-sm font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
                  >
                    {item.label}
                  </span>
                </div>

                {/* Status Dots */}
                {item.status && (
                  <div
                    className={`absolute transition-all duration-200 ${collapsed ? 'top-2 right-2' : 'top-1/2 right-3 -translate-y-1/2'}`}
                  >
                    <StatusLight
                      status={item.status}
                      className={collapsed ? 'h-2 w-2' : ''}
                      animate={!collapsed}
                    />
                  </div>
                )}
              </button>

              {/* Session sub-tabs: always visible */}
              {item.id === View.SESSION && (
                <div className="flex flex-col gap-2">
                  {sessionSubItems.map((subItem) => {
                    const isSubActive = currentView === View.SESSION && sessionTab === subItem.id;
                    return (
                      <button
                        key={subItem.id}
                        onClick={() => {
                          onChangeView(View.SESSION);
                          onChangeSessionTab(subItem.id);
                        }}
                        className={`relative z-10 flex w-full items-center focus:ring-0 focus:outline-none ${collapsed ? 'justify-center px-0' : 'pr-4 pl-9'} h-9 rounded-xl transition-colors duration-200 ${
                          isSubActive
                            ? 'bg-white/6 text-slate-200'
                            : 'text-slate-500 hover:bg-white/5 hover:text-slate-400'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span
                            className={`transition-colors duration-200 ${isSubActive ? 'text-accent-cyan/70' : ''}`}
                          >
                            {subItem.icon}
                          </span>
                          <span
                            className={`text-xs font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
                          >
                            {subItem.label}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Notebook sub-tabs: always visible */}
              {item.id === View.NOTEBOOK && (
                <div className="flex flex-col gap-2">
                  {notebookSubItems.map((subItem) => {
                    const isSubActive = currentView === View.NOTEBOOK && notebookTab === subItem.id;
                    return (
                      <button
                        key={subItem.id}
                        onClick={() => {
                          onChangeView(View.NOTEBOOK);
                          onChangeNotebookTab(subItem.id);
                        }}
                        className={`relative z-10 flex w-full items-center focus:ring-0 focus:outline-none ${collapsed ? 'justify-center px-0' : 'pr-4 pl-9'} h-9 rounded-xl transition-colors duration-200 ${
                          isSubActive
                            ? 'bg-white/6 text-slate-200'
                            : 'text-slate-500 hover:bg-white/5 hover:text-slate-400'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span
                            className={`transition-colors duration-200 ${isSubActive ? 'text-accent-cyan/70' : ''}`}
                          >
                            {subItem.icon}
                          </span>
                          <span
                            className={`text-xs font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
                          >
                            {subItem.label}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </nav>

      {/* Bug Report - above the separator */}
      <div className="px-3 pb-2">
        <button
          onClick={onOpenBugReport}
          className={`flex h-12 w-full items-center rounded-xl text-slate-400 transition-colors hover:bg-white/5 hover:text-white focus:ring-0 focus:outline-none ${collapsed ? 'justify-center' : 'gap-4 px-4'} `}
        >
          <Bug size={20} />
          <span
            className={`text-sm font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
          >
            Bug Report
          </span>
        </button>
      </div>

      {/* Footer / Settings */}
      <div className="border-glass-border space-y-1 border-t p-4">
        <button
          onClick={onOpenAbout}
          className={`flex h-12 w-full items-center rounded-xl text-slate-400 transition-colors hover:bg-white/5 hover:text-white focus:ring-0 focus:outline-none ${collapsed ? 'justify-center' : 'gap-4 px-4'} `}
        >
          <Info size={20} />
          <span
            className={`text-sm font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
          >
            About
          </span>
        </button>

        <button
          onClick={onOpenSettings}
          className={`flex h-12 w-full items-center rounded-xl text-slate-400 transition-colors hover:bg-white/5 hover:text-white focus:ring-0 focus:outline-none ${collapsed ? 'justify-center' : 'gap-4 px-4'} `}
        >
          <Settings size={20} />
          <span
            className={`text-sm font-medium whitespace-nowrap transition-all duration-200 ${collapsed ? 'hidden w-0 opacity-0' : 'opacity-100'}`}
          >
            Settings
          </span>
        </button>
      </div>
    </div>
  );
};
