import React from 'react';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  title?: React.ReactNode;
  action?: React.ReactNode;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  className = '',
  title,
  action,
}) => {
  return (
    <div
      className={`from-glass-200 to-glass-100 border-glass-border flex flex-col overflow-hidden rounded-2xl border bg-linear-to-br shadow-xl backdrop-blur-xl ${className}`}
    >
      {(title || action) && (
        <div className="border-glass-border flex h-14 shrink-0 items-center justify-between border-b bg-white/5 px-5">
          {title && (
            <div className="flex items-center text-sm font-semibold tracking-wide text-white/90">
              {title}
            </div>
          )}
          {action && <div>{action}</div>}
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col p-5">{children}</div>
    </div>
  );
};
