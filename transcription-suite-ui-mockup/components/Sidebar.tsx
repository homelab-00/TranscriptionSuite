import React, { useState } from 'react';
import { View } from '../types';
import { Mic2, Book, Server, Settings, ChevronLeft, ChevronRight, Info } from 'lucide-react';
import { StatusLight } from './ui/StatusLight';

interface SidebarProps {
  currentView: View;
  onChangeView: (view: View) => void;
  onOpenSettings: () => void;
  onOpenAbout: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onChangeView, onOpenSettings, onOpenAbout }) => {
  const [collapsed, setCollapsed] = useState(false);

  // Top navigation items that get the sliding animation
  const navItems = [
    { id: View.SESSION, label: 'Session', icon: <Mic2 size={20} />, hasClientStatus: true },
    { id: View.NOTEBOOK, label: 'Notebook', icon: <Book size={20} /> },
    { id: View.SERVER, label: 'Server', icon: <Server size={20} />, hasServerStatus: true },
  ];

  const activeIndex = navItems.findIndex(item => item.id === currentView);

  return (
    <div 
      className={`
        bg-glass-surface backdrop-blur-2xl border-r border-glass-border h-full flex flex-col transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] relative
        ${collapsed ? 'w-20' : 'w-[200px]'}
      `}
    >
        {/* Toggle Button */}
        <button 
            onClick={() => setCollapsed(!collapsed)}
            className="absolute -right-3 top-10 bg-slate-800 text-white border border-white/10 rounded-full p-1 shadow-lg hover:bg-accent-cyan hover:text-black transition-colors z-20 outline-none focus:outline-none"
        >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>

      {/* Logo Area */}
      <div className={`p-6 flex items-center ${collapsed ? 'justify-center' : 'gap-3'} transition-all duration-300`}>
        <div className="relative flex-shrink-0">
             <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent-magenta to-accent-orange flex items-center justify-center shadow-lg shadow-accent-magenta/20">
                <Mic2 className="text-white" size={24} />
             </div>
             <div className="absolute -top-1 -right-1 w-3 h-3 bg-accent-cyan rounded-full border-2 border-slate-900"></div>
        </div>
        
        <div className={`overflow-hidden transition-all duration-300 ${collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100'}`}>
            <h1 className="font-bold text-lg leading-tight text-white whitespace-nowrap">Transcription</h1>
            <h2 className="text-xs text-accent-cyan font-bold tracking-widest uppercase">Suite</h2>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-6 flex flex-col gap-2 relative">
        
        {/* Animated Background Pill for Active State */}
        {activeIndex !== -1 && (
            <div 
                className="absolute left-3 right-3 h-12 top-0 rounded-xl bg-gradient-to-r from-white/10 to-transparent border border-white/5 shadow-inner transition-all duration-200 ease-[cubic-bezier(0.25,0.1,0.25,1)] z-0 pointer-events-none"
                style={{
                    // 1.5rem (py-6) + index * (3rem height + 0.5rem gap)
                    transform: `translateY(calc(1.5rem + ${activeIndex} * 3.5rem))`
                }}
            >
                {/* Active Indicator Bar (Cyan) */}
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-accent-cyan rounded-r-full shadow-[0_0_10px_#22d3ee]"></div>
            </div>
        )}

        {navItems.map((item) => {
            const isActive = currentView === item.id;
            return (
                <button
                    key={item.id}
                    onClick={() => onChangeView(item.id)}
                    className={`
                        w-full flex items-center relative z-10 focus:outline-none focus:ring-0
                        ${collapsed ? 'justify-center px-0' : 'px-4'}
                        h-12 rounded-xl transition-colors duration-200
                        ${isActive 
                            ? 'text-white' 
                            : 'text-slate-400 hover:text-white hover:bg-white/5'
                        }
                    `}
                >
                    <div className={`flex items-center gap-4 transition-all duration-200`}>
                        <span className={`transition-colors duration-200 ${isActive ? 'text-accent-cyan' : ''}`}>
                            {item.icon}
                        </span>
                        <span className={`font-medium text-sm whitespace-nowrap transition-all duration-200 ${collapsed ? 'opacity-0 w-0 hidden' : 'opacity-100'}`}>
                            {item.label}
                        </span>
                    </div>

                    {/* Status Dots */}
                    {(item.hasClientStatus || item.hasServerStatus) && (
                        <div className={`absolute transition-all duration-200 ${collapsed ? 'top-2 right-2' : 'right-3 top-1/2 -translate-y-1/2'}`}>
                            <StatusLight status="active" className={collapsed ? 'w-2 h-2' : ''} animate={!collapsed} />
                        </div>
                    )}
                </button>
            );
        })}
      </nav>

      {/* Footer / Settings */}
      <div className="p-4 border-t border-glass-border space-y-1">
         <button 
            onClick={onOpenAbout}
            className={`
                w-full flex items-center h-12 rounded-xl transition-colors text-slate-400 hover:text-white hover:bg-white/5 focus:outline-none focus:ring-0
                ${collapsed ? 'justify-center' : 'px-4 gap-4'}
            `}
         >
            <Info size={20} />
            <span className={`font-medium text-sm whitespace-nowrap transition-all duration-200 ${collapsed ? 'opacity-0 w-0 hidden' : 'opacity-100'}`}>About</span>
         </button>
         
         <button 
            onClick={onOpenSettings}
            className={`
                w-full flex items-center h-12 rounded-xl transition-colors text-slate-400 hover:text-white hover:bg-white/5 focus:outline-none focus:ring-0
                ${collapsed ? 'justify-center' : 'px-4 gap-4'}
            `}
         >
            <Settings size={20} />
            <span className={`font-medium text-sm whitespace-nowrap transition-all duration-200 ${collapsed ? 'opacity-0 w-0 hidden' : 'opacity-100'}`}>Settings</span>
         </button>
      </div>
    </div>
  );
};