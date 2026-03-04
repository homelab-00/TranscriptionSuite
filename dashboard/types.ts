export enum View {
  SESSION = 'SESSION',
  NOTEBOOK = 'NOTEBOOK',
  SERVER = 'SERVER',
  MODEL_MANAGER = 'MODEL_MANAGER',
  LOGS = 'LOGS',
}

export enum NotebookTab {
  CALENDAR = 'CALENDAR',
  SEARCH = 'SEARCH',
  IMPORT = 'IMPORT',
}

export interface StatusIndicatorProps {
  status: 'active' | 'inactive' | 'warning' | 'error' | 'loading';
  label?: string;
}

export interface NavItem {
  id: View;
  label: string;
  icon: any; // Lucide icon type
  hasStatus?: boolean;
}
