import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
}

/** AMD arrow logo — simplified for small sizes, white via currentColor. */
export const AmdIcon: React.FC<IconProps> = ({ size = 14, className = '' }) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="currentColor"
    className={className}
    aria-label="AMD"
  >
    <path d="M2 22 18.5 2h3.5v3.5L5.5 22zm16-5.5L22 12v10h-10l4.5-4H18z" />
  </svg>
);
