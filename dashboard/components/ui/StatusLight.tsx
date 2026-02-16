import React, { useLayoutEffect, useState } from 'react';

interface StatusLightProps {
  status: 'active' | 'inactive' | 'warning' | 'error' | 'loading';
  className?: string;
  animate?: boolean;
}

export const StatusLight: React.FC<StatusLightProps> = ({
  status,
  className = '',
  animate = true,
}) => {
  const colors = {
    active: 'bg-green-500 shadow-green-500/50',
    inactive: 'bg-slate-500',
    warning: 'bg-accent-orange shadow-accent-orange/50',
    error: 'bg-red-500 shadow-red-500/50',
    loading: 'bg-blue-400 shadow-blue-400/50',
  };

  // Only 'active' (green) should pulse. 'warning' (orange) glows but does not pulse.
  const shouldPulse = animate && status === 'active';
  const shouldGlow = status !== 'inactive';

  const [syncDelay, setSyncDelay] = useState('0ms');

  // Synchronize animation to the system clock
  useLayoutEffect(() => {
    if (shouldPulse) {
      // Tailwind's 'animate-ping' duration is exactly 1000ms (1s).
      // We calculate how many milliseconds have passed in the current second.
      const duration = 1000;
      const now = Date.now();

      // Calculate a negative delay. This tells CSS:
      // "Start the animation as if it had already been running for X ms."
      // This aligns every single instance to the exact same global heartbeat.
      const timeIntoCycle = now % duration;
      setSyncDelay(`-${timeIntoCycle}ms`);
    }
  }, [shouldPulse]);

  return (
    <span className={`relative flex h-3 w-3 ${className}`}>
      {shouldPulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${colors[status].split(' ')[0]}`}
          style={{ animationDelay: syncDelay }}
        ></span>
      )}
      <span
        className={`relative inline-flex h-3 w-3 rounded-full ${shouldGlow ? 'shadow-lg' : ''} ${colors[status]}`}
      ></span>
    </span>
  );
};
