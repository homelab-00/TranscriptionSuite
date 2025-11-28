import { useEffect, useRef } from 'react';

interface ContextMenuProps {
  open: boolean;
  onClose: () => void;
  position: { x: number; y: number } | null;
  children: React.ReactNode;
}

export function ContextMenu({ open, onClose, position, children }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleScroll = () => {
      onClose();
    };

    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('scroll', handleScroll, true);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('scroll', handleScroll, true);
    };
  }, [open, onClose]);

  if (!open || !position) return null;

  return (
    <div
      ref={menuRef}
      className="fixed z-50 py-1 bg-surface border border-gray-700 rounded-lg shadow-xl min-w-[160px] animate-fade-in"
      style={{ top: position.y, left: position.x }}
    >
      {children}
    </div>
  );
}

interface ContextMenuItemProps {
  onClick: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

export function ContextMenuItem({ onClick, icon, children, danger = false, disabled = false }: ContextMenuItemProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full flex items-center gap-3 px-3 py-2 text-sm text-left transition-colors
        ${danger ? 'text-red-400 hover:bg-red-500/10' : 'text-gray-300 hover:bg-surface-light'}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      {icon && <span className="w-4 h-4">{icon}</span>}
      {children}
    </button>
  );
}
