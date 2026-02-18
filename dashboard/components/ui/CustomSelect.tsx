import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';

interface CustomSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  className?: string;
  placeholder?: string;
  accentColor?: 'cyan' | 'magenta';
}

export const CustomSelect: React.FC<CustomSelectProps> = ({
  value,
  onChange,
  options,
  className = '',
  placeholder = 'Select...',
  accentColor = 'cyan',
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const updateCoords = useCallback(() => {
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setCoords({
        top: rect.bottom + 4, // 4px offset
        left: rect.left,
        width: rect.width,
      });
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      // Add listeners for scroll/resize to update position while open
      window.addEventListener('scroll', updateCoords, true);
      window.addEventListener('resize', updateCoords);

      return () => {
        window.removeEventListener('scroll', updateCoords, true);
        window.removeEventListener('resize', updateCoords);
      };
    }
  }, [isOpen, updateCoords]);

  // Click outside logic
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;

      // Close if click is outside both trigger container and dropdown menu
      const clickedOutsideContainer =
        containerRef.current && !containerRef.current.contains(target);
      const clickedOutsideDropdown = dropdownRef.current && !dropdownRef.current.contains(target);

      if (clickedOutsideContainer && clickedOutsideDropdown) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const toggleOpen = () => {
    if (!isOpen) {
      // Calculate coords immediately before opening to prevent flash at 0,0
      updateCoords();
    }
    setIsOpen(!isOpen);
  };

  // Heuristics to pass layout classes to the container
  const isFlex = className.includes('flex-1');
  const heightClass = className.match(/h-\w+|h-\[.*\]/)?.[0] || '';
  const widthClass = className.match(/w-\w+|w-\[.*\]/)?.[0] || '';
  const minWidthClass = className.match(/min-w-\w+|min-w-\[.*\]/)?.[0] || '';
  const maxWidthClass = className.match(/max-w-\w+|max-w-\[.*\]/)?.[0] || '';

  // The container needs to participate in the layout (flex, width) properly.
  // We extract width-related classes from className to apply to the container.
  // Note: We leave the original className on the button as well for bg, padding, border, etc.
  const containerClasses = `relative min-w-0 ${isFlex ? 'flex-1' : ''} ${heightClass} ${widthClass} ${minWidthClass} ${maxWidthClass}`;

  // Styles based on accentColor
  const activeItemClass =
    accentColor === 'magenta'
      ? 'bg-accent-magenta/10 text-accent-magenta'
      : 'bg-accent-cyan/10 text-accent-cyan';

  const dotClass =
    accentColor === 'magenta'
      ? 'bg-accent-magenta shadow-[0_0_5px_rgba(217,70,239,0.5)]'
      : 'bg-accent-cyan shadow-[0_0_5px_rgba(34,211,238,0.5)]';

  return (
    <div className={containerClasses} ref={containerRef}>
      <button
        type="button"
        onClick={toggleOpen}
        title={value || placeholder}
        className={`flex h-full w-full min-w-0 items-center justify-between text-left ${className}`}
      >
        <span className="mr-2 truncate">{value || placeholder}</span>
        <ChevronDown
          size={14}
          className={`shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''} opacity-50`}
        />
      </button>

      {isOpen &&
        createPortal(
          <div
            ref={dropdownRef}
            style={{
              top: coords.top,
              left: coords.left,
              width: coords.width,
            }}
            className="animate-in fade-in zoom-in-95 fixed z-9999 overflow-hidden rounded-xl border border-white/10 bg-slate-900 shadow-2xl ring-1 ring-white/5 duration-100"
          >
            <div className="custom-scrollbar max-h-60 overflow-y-auto py-1">
              {options.map((option) => (
                <div
                  key={option}
                  onClick={() => {
                    onChange(option);
                    setIsOpen(false);
                  }}
                  title={option}
                  className={`flex min-w-0 cursor-pointer items-center justify-between px-4 py-2 text-sm transition-colors ${option === value ? activeItemClass : 'text-slate-300 hover:bg-white/5 hover:text-white'} `}
                >
                  <span className="mr-2 truncate">{option}</span>
                  {option === value && (
                    <div className={`h-1.5 w-1.5 rounded-full ${dotClass}`}></div>
                  )}
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
};
