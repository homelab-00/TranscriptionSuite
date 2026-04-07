import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
}

/** AMD logo — simplified SVG path, white by default via currentColor. */
export const AmdIcon: React.FC<IconProps> = ({ size = 14, className = '' }) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="currentColor"
    className={className}
    aria-label="AMD"
  >
    <path d="M18.324 9.676 21.648 6h-4.569l-3.324 3.676zM0 17.998h3.364l.704-1.726h3.382l.69 1.726H11.6L8.03 10.072H5.468zm4.81-4.252 1.004-2.472 1.004 2.472zm7.174 4.252h3.2V13.47L17.5 10.072h-3.254l2.444 3.304v4.622zm5.72 0H24v-7.926h-3.496l-1.778 4.282-1.778-4.282H12.44v7.926h2.8v-5.226l2.038 5.226h1.336l2.038-5.274v5.274z" />
  </svg>
);
