import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
}

/** Intel arc logo — simplified for small sizes, white via currentColor. */
export const IntelIcon: React.FC<IconProps> = ({ size = 14, className = '' }) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="currentColor"
    className={className}
    aria-label="Intel"
  >
    <circle cx="18" cy="5" r="2" />
    <path d="M18 9c-4.97 0-9 4.03-9 9h2.5a6.5 6.5 0 0 1 6.5-6.5z" />
    <path d="M18 13a5 5 0 0 0-5 5h2.5a2.5 2.5 0 0 1 2.5-2.5z" />
    <rect x="4" y="5" width="2.5" height="13" rx="1.25" />
  </svg>
);
