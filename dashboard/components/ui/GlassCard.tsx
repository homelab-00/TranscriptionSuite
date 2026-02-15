
import React from 'react';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  title?: React.ReactNode;
  action?: React.ReactNode;
}

export const GlassCard: React.FC<GlassCardProps> = ({ children, className = '', title, action }) => {
  return (
    <div className={`bg-linear-to-br from-glass-200 to-glass-100 backdrop-blur-xl border border-glass-border rounded-2xl shadow-xl overflow-hidden flex flex-col ${className}`}>
      {(title || action) && (
        <div className="h-14 px-5 border-b border-glass-border flex justify-between items-center bg-white/5 shrink-0">
          {title && <div className="text-sm font-semibold text-white/90 tracking-wide flex items-center">{title}</div>}
          {action && <div>{action}</div>}
        </div>
      )}
      <div className="p-5 flex-1 flex flex-col min-h-0">
        {children}
      </div>
    </div>
  );
};
