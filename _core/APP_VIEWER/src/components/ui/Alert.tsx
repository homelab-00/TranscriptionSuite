import { AlertCircle, CheckCircle, Info, XCircle, X } from 'lucide-react';

interface AlertProps {
  severity: 'error' | 'success' | 'warning' | 'info';
  children: React.ReactNode;
  onClose?: () => void;
  className?: string;
}

const severityConfig = {
  error: {
    icon: XCircle,
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    textColor: 'text-red-400',
    iconColor: 'text-red-400',
  },
  success: {
    icon: CheckCircle,
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/30',
    textColor: 'text-green-400',
    iconColor: 'text-green-400',
  },
  warning: {
    icon: AlertCircle,
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-yellow-500/30',
    textColor: 'text-yellow-400',
    iconColor: 'text-yellow-400',
  },
  info: {
    icon: Info,
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    textColor: 'text-blue-400',
    iconColor: 'text-blue-400',
  },
};

export function Alert({ severity, children, onClose, className = '' }: AlertProps) {
  const config = severityConfig[severity];
  const Icon = config.icon;

  return (
    <div
      className={`flex items-start gap-3 p-3 rounded-lg border ${config.bgColor} ${config.borderColor} ${className}`}
    >
      <Icon size={20} className={`${config.iconColor} flex-shrink-0 mt-0.5`} />
      <div className={`flex-1 text-sm ${config.textColor}`}>{children}</div>
      {onClose && (
        <button
          onClick={onClose}
          className={`p-0.5 rounded ${config.textColor} hover:bg-white/10 transition-colors`}
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}
