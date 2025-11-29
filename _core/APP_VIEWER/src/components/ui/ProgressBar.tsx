interface ProgressBarProps {
  value?: number;
  indeterminate?: boolean;
  className?: string;
}

export function ProgressBar({ value = 0, indeterminate = false, className = '' }: ProgressBarProps) {
  return (
    <div className={`h-1 bg-gray-700 rounded-full overflow-hidden ${className}`}>
      {indeterminate ? (
        <div className="h-full bg-primary animate-pulse w-full" />
      ) : (
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      )}
    </div>
  );
}
